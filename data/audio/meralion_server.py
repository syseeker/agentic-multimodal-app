#!/usr/bin/env python3
"""OpenAI-compatible HTTP service for MERaLiON-3-10B.

Phase 4 infrastructure, not benchmark scaffolding: deployed by deploy/phase4_audio.sh and
consumed by process_audio.py and the analyze_audio MCP tool. Phase 9 only measures it.

MERaLiON loads in-process inside `data/audio/process_audio.py`, so aiperf — which drives
OpenAI HTTP endpoints — cannot reach it. This wraps it in a FastAPI service: load once at
startup, serve many requests.

In-process loading means the model cannot be shared, pooled, or scaled, and forces every
caller to hold ~20 GB of VRAM — so this exists for production reasons first. It also
happens to make the model reachable by aiperf, which cannot drive an in-process model.

    pip install fastapi uvicorn soundfile librosa transformers==4.50.1 torch
    HF_TOKEN=... python3 data/audio/meralion_server.py --port 8500

    GET  /v1/health/ready
    GET  /v1/models
    POST /v1/chat/completions   OpenAI chat shape; audio via an `input_audio` content part
                                (base64) or {"type":"audio_path","audio_path":"..."}.

Deliberately NOT vLLM: MERaLiON needs `trust_remote_code=True` and a custom
`MERaLiON3Config` whose `pad_token_id` must be patched before `from_pretrained`, so it is
not a drop-in vLLM architecture. Wrap transformers directly.
"""
from __future__ import annotations

import argparse
import base64
import io
import os
import time
import uuid

MODEL_ID = os.environ.get("MERALION_MODEL", "MERaLiON/MERaLiON-3-10B")
TARGET_SR = 16_000
# Whisper encoder hard limit per forward pass. Longer audio is WINDOWED and aggregated,
# matching data/audio/process_audio.py — a benchmark that truncated while production
# chunked would measure the wrong thing (and constant latency regardless of input length).
WINDOW_S = 30.0
MIN_TAIL_S = 3.0

_model = None
_processor = None


def _load():
    """Load once. Raises loudly — a shim that silently serves a stub is worse than a crash."""
    global _model, _processor
    if _model is not None:
        return
    import torch
    from transformers import AutoConfig, AutoModelForSpeechSeq2Seq, AutoProcessor

    if not torch.cuda.is_available():
        raise RuntimeError("no CUDA device — MERaLiON needs a GPU")
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise RuntimeError("HF_TOKEN not set — MERaLiON is a gated model")

    _processor = AutoProcessor.from_pretrained(MODEL_ID, trust_remote_code=True, token=token)
    cfg = AutoConfig.from_pretrained(MODEL_ID, trust_remote_code=True, token=token)
    # MERaLiON3Config does not define pad_token_id; from_pretrained raises without this.
    if getattr(cfg, "pad_token_id", None) is None:
        cfg.pad_token_id = getattr(_processor.tokenizer, "pad_token_id", 0) or 0
    _model = AutoModelForSpeechSeq2Seq.from_pretrained(
        MODEL_ID, config=cfg,
        torch_dtype=torch.bfloat16, attn_implementation="sdpa",
        trust_remote_code=True, token=token,
    ).to("cuda").eval()


def _decode_audio(raw: bytes):
    """bytes -> (mono float32 @ 16 kHz, original_seconds)"""
    import librosa
    import numpy as np
    import soundfile as sf

    audio, sr = sf.read(io.BytesIO(raw), dtype="float32", always_2d=False)
    if getattr(audio, "ndim", 1) > 1:
        audio = audio.mean(axis=1)
    orig_s = len(audio) / sr
    if sr != TARGET_SR:
        audio = librosa.resample(audio, orig_sr=sr, target_sr=TARGET_SR)
    return np.asarray(audio, dtype="float32"), orig_s


def _windows(audio):
    """Split into <=WINDOW_S windows; fold a short tail into the previous one."""
    win, min_tail = int(WINDOW_S * TARGET_SR), int(MIN_TAIL_S * TARGET_SR)
    out, start = [], 0
    while start < len(audio):
        end = min(start + win, len(audio))
        if out and (end - start) < min_tail:
            out[-1] = (out[-1][0], end)
        else:
            out.append((start, end))
        start = end
    return out


def _extract(messages):
    """Pull (prompt, audio_bytes) out of an OpenAI messages array."""
    prompt, raw = "", None
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            prompt += content
            continue
        for part in content or []:
            t = part.get("type")
            if t == "text":
                prompt += part.get("text", "")
            elif t == "input_audio":
                raw = base64.b64decode(part["input_audio"]["data"])
            elif t == "audio_path":  # convenience for local benchmark runs
                with open(part["audio_path"], "rb") as fh:
                    raw = fh.read()
    return prompt or "Describe the speaker's emotion, stress level and language.", raw


def build_app():
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import JSONResponse

    app = FastAPI(title="meralion-shim")

    @app.on_event("startup")
    def _startup():
        _load()

    @app.get("/v1/health/ready")
    def ready():
        return {"ready": _model is not None}

    @app.get("/v1/models")
    def models():
        return {"object": "list", "data": [{"id": MODEL_ID, "object": "model"}]}

    @app.post("/v1/chat/completions")
    def chat(body: dict):
        import torch

        prompt, raw = _extract(body.get("messages", []))
        if raw is None:
            raise HTTPException(400, "no audio in request (input_audio or audio_path)")
        audio, orig_s = _decode_audio(raw)
        bounds = _windows(audio)

        parts, n_in_total, n_out_total = [], 0, 0
        text = _processor.tokenizer.apply_chat_template(
            [{"role": "user", "content": prompt}], tokenize=False, add_generation_prompt=True)
        for a, b in bounds:
            inputs = _processor(text=text, audios=[audio[a:b]], sampling_rate=TARGET_SR,
                                return_tensors="pt")
            inputs = {k: (v.to("cuda", torch.bfloat16)
                          if getattr(v, "is_floating_point", lambda: False)()
                          else v.to("cuda")) if hasattr(v, "to") else v
                      for k, v in inputs.items()}
            n_in = int(inputs["input_ids"].shape[-1]) if "input_ids" in inputs else 0
            with torch.no_grad():
                out = _model.generate(**inputs,
                                      max_new_tokens=int(body.get("max_tokens", 256)),
                                      do_sample=False)
            new = out[0][n_in:] if out.shape[-1] > n_in else out[0]
            parts.append({
                "start_s": round(a / TARGET_SR, 1),
                "end_s": round(b / TARGET_SR, 1),
                "text": _processor.tokenizer.decode(new, skip_special_tokens=True),
            })
            n_in_total += n_in
            n_out_total += int(len(new))
        answer = "\n".join(f"[{p['start_s']}-{p['end_s']}s] {p['text']}" for p in parts) \
            if len(parts) > 1 else parts[0]["text"]
        n_in, new = n_in_total, range(n_out_total)

        return JSONResponse({
            "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": MODEL_ID,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": answer}}],
            "usage": {"prompt_tokens": n_in, "completion_tokens": n_out_total,
                      "total_tokens": n_in + n_out_total},
            # Non-standard, deliberately surfaced: the whole recording is analysed, so
            # latency scales with duration. windows>1 means this request did N forward
            # passes -- do not compare it against a 1-window request as if equal work.
            "meralion": {"input_seconds": round(orig_s, 1),
                         "analysed_seconds": round(orig_s, 1),
                         "windows": len(bounds),
                         "segments": parts},
        })

    return app


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8500)
    a = ap.parse_args()
    import uvicorn
    uvicorn.run(build_app(), host=a.host, port=a.port, log_level="info")
