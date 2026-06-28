"""
Sherlock Workbench — FastAPI backend (Phase 8)
Proxies to AI-Q (:8100), Neo4j (:7687), and serves case files.
Port: 8200
"""
import json
import os
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
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
            label = row["labels"][0] if row["labels"] else "Unknown"
            node_name = props.get("name") or props.get("id") or "?"
            node_id = f"{label}_{node_name}"
            if node_id in seen_nodes:
                continue
            seen_nodes.add(node_id)
            display_props = {
                k: v
                for k, v in props.items()
                if k not in ("case_id", "source") and v is not None
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
            al = row["al"][0] if row["al"] else "Unknown"
            bl = row["bl"][0] if row["bl"] else "Unknown"
            src = f"{al}_{a.get('name') or a.get('id') or '?'}"
            tgt = f"{bl}_{b.get('name') or b.get('id') or '?'}"
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

_ALLOWED_SUFFIXES = {".txt", ".json", ".md"}
_TEXT_FILES = {"case_report.txt", "witness_statement.txt", "lab_report.txt",
               "whatsapp_chat.txt", "audio_analysis.txt", "metadata.json"}


@app.get("/api/cases/{case_id}/evidence")
def list_evidence(case_id: str):
    case_dir = CASES_DIR / case_id
    if not case_dir.exists():
        raise HTTPException(404, "Case not found")
    files = []
    for f in sorted(case_dir.iterdir()):
        if f.is_file() and f.suffix in _ALLOWED_SUFFIXES:
            files.append({"name": f.name, "size": f.stat().st_size})
    return files


@app.get("/api/cases/{case_id}/evidence/{filename}")
def get_evidence_file(case_id: str, filename: str):
    if "/" in filename or ".." in filename:
        raise HTTPException(400, "Invalid filename")
    file_path = CASES_DIR / case_id / filename
    if not file_path.exists():
        raise HTTPException(404, "File not found")
    if file_path.suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(403, "File type not allowed")
    return {"content": file_path.read_text(errors="replace"), "filename": filename}


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
            async with httpx.AsyncClient(timeout=120.0) as client:
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
