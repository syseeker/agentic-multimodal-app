"""FastAPI server exposing the agent to the UI.

Phase-explicit endpoints (plan → investigate → finalize) so the UI can gate each
phase behind human approval. Sessions are held in-memory keyed by case_id.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .engines import get_engine
from .models import Asset, Modality
from .orchestrator import CaseSession
from .settings import get_settings

app = FastAPI(title="Agentic Multimodal App", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


@app.on_event("startup")
def _startup() -> None:
    from .tracing import setup_tracing

    setup_tracing()

SESSIONS: dict[str, CaseSession] = {}
DATA_DIR = Path("data")


# ── request bodies ──────────────────────────────────────────────────────────
class CreateCase(BaseModel):
    case_id: str
    objective: str
    assets: list[Asset] = []
    load_dir: str | None = None  # data/generated/<case>; reads manifest.json


class Investigate(BaseModel):
    approved_asset_ids: list[str] | None = None


class ChatBody(BaseModel):
    message: str
    history: list[dict] = []


# ── helpers ─────────────────────────────────────────────────────────────────
def _load_dir(load_dir: str) -> list[Asset]:
    manifest = Path(load_dir) / "manifest.json"
    if not manifest.exists():
        raise HTTPException(404, f"no manifest.json in {load_dir}")
    data = json.loads(manifest.read_text())
    return [
        Asset(
            asset_id=a["asset_id"],
            modality=Modality(a["modality"]),
            path=str(Path(load_dir) / a["path"]),
            label=a.get("label", ""),
        )
        for a in data["assets"]
    ]


def _session(case_id: str) -> CaseSession:
    s = SESSIONS.get(case_id)
    if not s:
        raise HTTPException(404, f"case {case_id} not found; create it first")
    return s


# ── endpoints ────────────────────────────────────────────────────────────────
@app.get("/health")
def health() -> dict:
    s = get_settings()
    return {"status": "ok", "engine": s.agent_engine, "vector": s.vector_backend}


@app.post("/cases")
def create_case(body: CreateCase) -> dict:
    assets = list(body.assets)
    if body.load_dir:
        assets += _load_dir(body.load_dir)
    if not assets:
        raise HTTPException(400, "no assets provided")
    SESSIONS[body.case_id] = CaseSession(body.case_id, assets, body.objective)
    return {"case_id": body.case_id, "assets": len(assets)}


@app.post("/cases/{case_id}/plan")
def plan(case_id: str) -> dict:
    return _session(case_id).make_plan().model_dump()


@app.post("/cases/{case_id}/investigate")
def investigate(case_id: str, body: Investigate) -> dict:
    return _session(case_id).investigate(body.approved_asset_ids)


@app.post("/cases/{case_id}/finalize")
def finalize(case_id: str) -> dict:
    return _session(case_id).finalize().model_dump()


@app.get("/cases/{case_id}/graph")
def graph(case_id: str) -> dict:
    from .tools import graph_view

    _session(case_id)  # ensure exists
    return graph_view(case_id)


@app.get("/cases/{case_id}/log")
def log(case_id: str) -> dict:
    return {"log": _session(case_id).log}


@app.post("/cases/{case_id}/chat")
def chat(case_id: str, body: ChatBody) -> dict:
    _session(case_id)
    answer = get_engine().chat(case_id, body.message, body.history)
    return {"answer": answer}


@app.post("/upload")
async def upload(case_id: str, modality: str, file: UploadFile) -> dict:
    dest_dir = DATA_DIR / "uploads" / case_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / file.filename
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return {
        "asset": Asset(
            asset_id=Path(file.filename).stem,
            modality=Modality(modality),
            path=str(dest),
            label=file.filename,
        ).model_dump()
    }
