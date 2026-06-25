"""OpenAI-compatible ASR shim for NVIDIA Canary (NeMo backend).

An ASR-only alternative to the MERaLiON-3 shim, for A/B comparison. Canary is a
top NVIDIA multilingual ASR/AST model but does NOT produce paralinguistics
(emotion/tone) — so when this backend is active, the sentiment tool falls back to
text-only sentiment over the transcript.

Default model: nvidia/canary-1b-v2 (multilingual ASR + speech translation).
Alt: nvidia/canary-qwen-2.5b (English, SoTA on the HF Open ASR leaderboard).

Exposes the same /v1/chat/completions contract as the other servers so the app's
audio_client() needs no changes.

    MODEL=nvidia/canary-1b-v2 PORT=8004 python serving/canary_shim.py
"""
from __future__ import annotations

import base64
import os
import tempfile
import time
import uuid

from fastapi import FastAPI
from pydantic import BaseModel

MODEL = os.getenv("MODEL", "nvidia/canary-1b-v2")
SERVED = os.getenv("SERVED_NAME", "audio")
PORT = int(os.getenv("PORT", "8004"))

app = FastAPI(title="Canary ASR shim")
_state: dict = {}


def _load():
    if "model" in _state:
        return
    from nemo.collections.asr.models import ASRModel

    _state["model"] = ASRModel.from_pretrained(model_name=MODEL).eval()


def _audio_to_tmp(messages: list[dict]) -> str | None:
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            for part in content:
                if part.get("type") == "input_audio":
                    data = base64.b64decode(part["input_audio"]["data"])
                    fmt = part["input_audio"].get("format", "wav")
                    tmp = tempfile.NamedTemporaryFile(suffix=f".{fmt}", delete=False)
                    tmp.write(data)
                    tmp.close()
                    return tmp.name
    return None


class ChatRequest(BaseModel):
    model: str | None = None
    messages: list[dict]
    max_tokens: int = 2048
    temperature: float = 0.0
    extra_body: dict | None = None


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": SERVED, "object": "model"}]}


@app.post("/v1/chat/completions")
def chat(req: ChatRequest):
    _load()
    path = _audio_to_tmp(req.messages)
    text = ""
    if path:
        out = _state["model"].transcribe([path])
        # NeMo returns list[str] or list[Hypothesis] depending on version.
        first = out[0] if out else ""
        text = getattr(first, "text", first)
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": SERVED,
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": text}}],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
