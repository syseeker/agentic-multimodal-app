"""
Sherlock Workbench — FastAPI backend (Phase 8)
Proxies to AI-Q (:8100), Neo4j (:7687), and serves case files.
Port: 8200
"""
import json
import os
import re
import secrets
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from neo4j import GraphDatabase

REPO_ROOT = Path(__file__).parent.parent
CASES_DIR = REPO_ROOT / "data" / "cases"
AIQ_URL = os.getenv("AIQ_URL", "http://localhost:8100")
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASS", "sherlock_dev")

app = FastAPI(title="Sherlock Workbench API", docs_url="/api/docs")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_neo4j = None


def get_neo4j():
    global _neo4j
    if _neo4j is None:
        _neo4j = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    return _neo4j


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

@app.get("/api/cases")
def list_cases():
    cases = []
    if not CASES_DIR.exists():
        return cases
    for case_dir in sorted(CASES_DIR.iterdir()):
        if not case_dir.is_dir():
            continue
        meta_file = case_dir / "metadata.json"
        meta = {}
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text())
            except Exception:
                pass
        cases.append({"case_id": case_dir.name, **meta})
    return cases


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

_NODE_COLORS = {
    "Person": "#3b82f6",
    "Organization": "#f59e0b",
    "Location": "#22c55e",
    "Evidence": "#ef4444",
    "Case": "#8b5cf6",
}


_LABEL_PRIORITY = ("Person", "Organization", "Location", "Evidence")


def _pick_label(labels: list) -> str:
    """Return a deterministic label regardless of Neo4j's label ordering."""
    for preferred in _LABEL_PRIORITY:
        if preferred in labels:
            return preferred
    return sorted(labels)[0] if labels else "Unknown"


@app.get("/api/cases/{case_id}/graph")
def get_case_graph(case_id: str):
    driver = get_neo4j()
    elements = []
    seen_nodes: set = set()
    seen_edges: set = set()

    with driver.session() as session:
        node_rows = session.run(
            "MATCH (n {case_id: $case_id}) WHERE NOT n:Case "
            "RETURN n, labels(n) AS labels",
            case_id=case_id,
        )
        for row in node_rows:
            props = dict(row["n"])
            label = _pick_label(row["labels"])
            node_name = props.get("name") or props.get("id") or "?"
            node_id = f"{label}_{node_name}"
            if node_id in seen_nodes:
                continue
            seen_nodes.add(node_id)
            display_props = {
                k: v
                for k, v in props.items()
                # exclude fields already captured as id/label, and internal fields
                if k not in ("case_id", "source", "id", "name") and v is not None
            }
            elements.append({
                "data": {
                    "id": node_id,
                    "label": node_name,
                    "type": label,
                    "color": _NODE_COLORS.get(label, "#64748b"),
                    **display_props,
                }
            })

        edge_rows = session.run(
            "MATCH (a {case_id: $case_id})-[r]->(b {case_id: $case_id}) "
            "WHERE NOT a:Case AND NOT b:Case "
            "RETURN a, labels(a) AS al, type(r) AS rel, b, labels(b) AS bl",
            case_id=case_id,
        )
        for row in edge_rows:
            a = dict(row["a"])
            b = dict(row["b"])
            src = f"{_pick_label(row['al'])}_{a.get('name') or a.get('id') or '?'}"
            tgt = f"{_pick_label(row['bl'])}_{b.get('name') or b.get('id') or '?'}"
            rel = row["rel"]
            key = (src, tgt, rel)
            if key in seen_edges or src not in seen_nodes or tgt not in seen_nodes:
                continue
            seen_edges.add(key)
            elements.append({
                "data": {
                    "id": f"{src}__{rel}__{tgt}",
                    "source": src,
                    "target": tgt,
                    "label": rel.replace("_", " "),
                }
            })

    return {"elements": elements, "node_count": len(seen_nodes), "edge_count": len(seen_edges)}


# ---------------------------------------------------------------------------
# Evidence files
# ---------------------------------------------------------------------------

_TEXT_SUFFIXES  = {".txt", ".json", ".md", ".csv"}
_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".wma"}
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
_VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
_MEDIA_SUFFIXES = _AUDIO_SUFFIXES | _IMAGE_SUFFIXES | _VIDEO_SUFFIXES
_ALL_SUFFIXES   = _TEXT_SUFFIXES | _MEDIA_SUFFIXES

_MIME = {
    ".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
    ".ogg": "audio/ogg", ".flac": "audio/flac", ".aac": "audio/aac",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp",
    ".mp4": "video/mp4", ".mov": "video/quicktime", ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska", ".webm": "video/webm", ".m4v": "video/mp4",
}


def _file_type(suffix: str) -> str:
    if suffix in _AUDIO_SUFFIXES: return "audio"
    if suffix in _IMAGE_SUFFIXES: return "image"
    if suffix in _VIDEO_SUFFIXES: return "video"
    return "text"


def _walk_evidence(case_dir: Path):
    """Yield (relative_subpath, absolute_path) for all evidence files."""
    # Root-level text files
    for f in sorted(case_dir.iterdir()):
        if f.is_file() and f.suffix.lower() in _ALL_SUFFIXES:
            yield f.name, f
    # Media subdirectories
    for subdir in ("audio", "images", "video"):
        d = case_dir / subdir
        if d.is_dir():
            for f in sorted(d.iterdir()):
                if f.is_file() and f.suffix.lower() in _ALL_SUFFIXES:
                    yield f"{subdir}/{f.name}", f


@app.get("/api/cases/{case_id}/evidence")
def list_evidence(case_id: str):
    case_dir = CASES_DIR / case_id
    if not case_dir.exists():
        raise HTTPException(404, "Case not found")
    files = []
    for subpath, f in _walk_evidence(case_dir):
        suffix = f.suffix.lower()
        files.append({
            "name": f.name,
            "subpath": subpath,
            "size": f.stat().st_size,
            "type": _file_type(suffix),
            "mime": _MIME.get(suffix, "application/octet-stream"),
        })
    return files


@app.get("/api/cases/{case_id}/evidence/{filename}")
def get_evidence_file(case_id: str, filename: str):
    """Return text content for text files."""
    if ".." in filename:
        raise HTTPException(400, "Invalid filename")
    file_path = CASES_DIR / case_id / filename
    if not file_path.exists():
        raise HTTPException(404, "File not found")
    if file_path.suffix.lower() not in _TEXT_SUFFIXES:
        raise HTTPException(403, "Use /media/ endpoint for binary files")
    return {"content": file_path.read_text(errors="replace"), "filename": filename}


@app.get("/api/cases/{case_id}/media/{subpath:path}")
def get_media_file(case_id: str, subpath: str):
    """Stream audio/image/video files with Range support."""
    if ".." in subpath:
        raise HTTPException(400, "Invalid path")
    file_path = CASES_DIR / case_id / subpath
    # Resolve and verify still inside case dir
    try:
        file_path = file_path.resolve()
        case_root = (CASES_DIR / case_id).resolve()
        file_path.relative_to(case_root)
    except ValueError:
        raise HTTPException(403, "Access denied")
    if not file_path.exists():
        raise HTTPException(404, "File not found")
    if file_path.suffix.lower() not in _MEDIA_SUFFIXES:
        raise HTTPException(403, "Not a media file")
    mime = _MIME.get(file_path.suffix.lower(), "application/octet-stream")
    return FileResponse(str(file_path), media_type=mime)


# ---------------------------------------------------------------------------
# Sentiment (audio_analysis.txt parser)
# ---------------------------------------------------------------------------

@app.get("/api/cases/{case_id}/sentiment")
def get_sentiment(case_id: str):
    file_path = CASES_DIR / case_id / "audio_analysis.txt"
    if not file_path.exists():
        return {"available": False, "entries": []}

    content = file_path.read_text()
    entries = []
    current_source = None
    current_lines: list = []

    for line in content.splitlines():
        if line.startswith("SOURCE:"):
            if current_source is not None:
                entries.append({
                    "source": current_source,
                    "analysis": "\n".join(current_lines).strip(),
                })
            current_source = line.removeprefix("SOURCE:").strip()
            current_lines = []
        elif current_source is not None:
            current_lines.append(line)

    if current_source is not None:
        entries.append({
            "source": current_source,
            "analysis": "\n".join(current_lines).strip(),
        })

    return {"available": bool(entries), "entries": entries, "raw": content}


# ---------------------------------------------------------------------------
# Case upload — create a new case from any mix of file types
# ---------------------------------------------------------------------------

# File type routing
_TEXT_EXTS  = {".txt", ".pdf", ".json", ".csv", ".md", ".doc", ".docx"}
_AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".wma"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"}
_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".mts", ".m4v"}

INGESTOR_URL = os.getenv("INGESTOR_URL", "http://localhost:8082")
RAG_COLLECTION = os.getenv("RAG_COLLECTION", "multimodal_data")


def _classify(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in _AUDIO_EXTS: return "audio"
    if ext in _IMAGE_EXTS: return "image"
    if ext in _VIDEO_EXTS: return "video"
    return "text"


def _spawn(*cmd, cwd=None):
    """Fire-and-forget a subprocess. Never blocks the request."""
    try:
        subprocess.Popen(
            list(cmd),
            cwd=str(cwd or REPO_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


async def _ingest_to_rag(case_id: str, file_path: Path):
    """POST a single text file to the RAG ingestor (non-blocking best-effort)."""
    unique_name = f"{case_id}_{file_path.name}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.post(
                f"{INGESTOR_URL}/documents",
                files={"documents": (unique_name, file_path.read_bytes(), "text/plain")},
                data={"data": json.dumps({
                    "collection_name": RAG_COLLECTION,
                    "blocking": False,
                })},
            )
    except Exception:
        pass  # RAG ingest is best-effort; entity graph will still work


@app.post("/api/cases/upload")
async def upload_case(
    files: List[UploadFile] = File(...),
    case_type: str = Form("unknown"),
    district: str = Form("unknown"),
    suspect_name: str = Form(""),
    assigned_officer: str = Form(""),
):
    """
    Accept any mix of evidence files (text, audio, image, video).
    Routes each file to the right subdirectory and triggers the
    appropriate pipeline automatically:

      text/pdf/doc  → root dir → RAG ingest + entity extraction
      audio         → audio/   → Parakeet ASR → audio_analysis.txt → entity extraction
      image         → images/  → (VLM caption when GPU available) → entity extraction
      video         → video/   → (VSS ingestion when GPU available)
    """
    year = datetime.now().year
    hex_id = secrets.token_hex(4).upper()
    case_id = f"SC-{year}-{hex_id}"
    case_dir = CASES_DIR / case_id
    for sub in ("", "audio", "images", "video"):
        (case_dir / sub).mkdir(parents=True, exist_ok=True)

    # Write metadata
    meta = {
        "case_id": case_id,
        "incident_date": datetime.now().strftime("%Y-%m-%d"),
        "case_type": case_type,
        "district": district,
        "case_status": "under_investigation",
        "suspect_name": suspect_name,
        "assigned_officer": assigned_officer,
        "evidence_ids": [],
    }
    (case_dir / "metadata.json").write_text(json.dumps(meta, indent=2))

    saved: list = []
    pipelines_triggered: list = []
    has_text = False
    has_audio = False
    has_image = False
    has_video = False

    for uf in files:
        filename = Path(uf.filename).name
        if not filename or ".." in filename:
            continue

        file_type = _classify(filename)
        subdir = {"text": "", "audio": "audio", "image": "images", "video": "video"}[file_type]
        dest = case_dir / subdir / filename if subdir else case_dir / filename
        dest.write_bytes(await uf.read())
        saved.append({"name": filename, "type": file_type})

        if file_type == "text":   has_text = True
        if file_type == "audio":  has_audio = True
        if file_type == "image":  has_image = True
        if file_type == "video":  has_video = True

    # ── Pipeline dispatch ─────────────────────────────────────────────────────

    if has_text:
        # Ingest each text file to RAG (non-blocking)
        text_files = [f for f in case_dir.iterdir()
                      if f.is_file() and f.suffix.lower() in _TEXT_EXTS
                      and f.name != "metadata.json"]
        for tf in text_files:
            await _ingest_to_rag(case_id, tf)
        pipelines_triggered.append("rag_ingest")

    if has_audio:
        # Parakeet ASR → audio_analysis.txt → then entity extraction picks it up
        _spawn(
            "python3", str(REPO_ROOT / "data" / "audio" / "process_audio.py"),
            "--case-id", case_id,
            cwd=REPO_ROOT,
        )
        pipelines_triggered.append("audio_asr")

    if has_image:
        # VLM captioning (stub — runs when GPU/NIM is available)
        # Writes image_captions.txt to case root, then entity extraction picks it up
        _spawn(
            "python3", str(REPO_ROOT / "data" / "image" / "caption_images.py"),
            "--case", case_id,
            cwd=REPO_ROOT,
        )
        pipelines_triggered.append("image_caption_stub")

    if has_video:
        # VSS ingestion (stub — runs when GPU + LVS_ENABLE_MCP=true)
        pipelines_triggered.append("video_vss_pending_gpu")

    # Entity extraction runs last — picks up text files + any transcripts written
    # by the audio/image pipelines (they write .txt files to the case root)
    _spawn(
        "python3", str(REPO_ROOT / "graph" / "ingest_entities.py"),
        "--case", case_id,
        cwd=REPO_ROOT,
    )
    pipelines_triggered.append("entity_extraction")

    counts = {
        "text": sum(1 for f in saved if f["type"] == "text"),
        "audio": sum(1 for f in saved if f["type"] == "audio"),
        "image": sum(1 for f in saved if f["type"] == "image"),
        "video": sum(1 for f in saved if f["type"] == "video"),
    }

    return {
        "case_id": case_id,
        "files_saved": saved,
        "file_counts": counts,
        "pipelines_triggered": pipelines_triggered,
        "status": "created",
        "message": (
            f"Case {case_id} created. "
            f"{len(saved)} file(s): "
            + ", ".join(f"{v} {k}" for k, v in counts.items() if v)
            + ". Pipelines: " + ", ".join(pipelines_triggered) + "."
        ),
    }


# ---------------------------------------------------------------------------
# Chat proxy (SSE stream from AI-Q)
# ---------------------------------------------------------------------------

@app.post("/api/chat")
async def chat_proxy(payload: dict):
    """
    Proxy POST /api/chat → AI-Q POST /v1/chat/stream
    Payload must include 'messages' list (OpenAI format).
    Returns text/event-stream.
    """
    payload.setdefault("stream", True)

    async def stream_gen():
        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                async with client.stream(
                    "POST",
                    f"{AIQ_URL}/v1/chat/stream",
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "text/event-stream",
                    },
                ) as resp:
                    async for chunk in resp.aiter_bytes():
                        yield chunk
        except Exception as exc:
            err = json.dumps({"error": str(exc)})
            yield f"data: {err}\n\ndata: [DONE]\n\n".encode()

    return StreamingResponse(
        stream_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    aiq_ok = False
    neo4j_ok = False

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{AIQ_URL}/health")
            aiq_ok = r.status_code == 200
    except Exception:
        pass

    try:
        driver = get_neo4j()
        with driver.session() as s:
            s.run("RETURN 1")
        neo4j_ok = True
    except Exception:
        pass

    return {"aiq": aiq_ok, "neo4j": neo4j_ok}


# ---------------------------------------------------------------------------
# Serve built Svelte SPA (production)
# ---------------------------------------------------------------------------

DIST = Path(__file__).parent / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(DIST / "assets")), name="assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404)
        index = DIST / "index.html"
        return FileResponse(str(index))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8200, log_level="info")
