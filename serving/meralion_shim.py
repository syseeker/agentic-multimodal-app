"""OpenAI-compatible serving shim for MERaLiON-3 (Transformers backend).

MERaLiON-3 has no vLLM support yet (model card: "vLLM coming soon") and no
quantized checkpoint, so we serve it with Transformers behind a minimal
OpenAI-compatible /v1/chat/completions endpoint. The rest of the app then talks
to it exactly like the vLLM servers (see app/llm.py: audio_client()).

Accepts OpenAI multimodal messages with an `input_audio` part:
    {"type": "input_audio", "input_audio": {"data": "<base64>", "format": "wav"}}

Follows the MERaLiON-3 usage pattern from the model card; verify against the
exact card revision at deploy time. bf16 weights (~20 GB) fit RTX PRO 6000 / GB10.

    MODEL=MERaLiON/MERaLiON-3-10B PORT=8003 python serving/meralion_shim.py
"""
from __future__ import annotations

import base64
import io
import os
import time
import uuid

import soundfile as sf
import torch
from fastapi import FastAPI
from pydantic import BaseModel
from transformers import AutoModelForCausalLM, AutoProcessor

MODEL = os.getenv("MODEL", "MERaLiON/MERaLiON-3-10B")
SERVED = os.getenv("SERVED_NAME", "audio")
PORT = int(os.getenv("PORT", "8003"))
TARGET_SR = 16000

app = FastAPI(title="MERaLiON-3 shim")
_state: dict = {}


def _load():
    if "model" in _state:
        return
    dtype = torch.bfloat16
    _state["processor"] = AutoProcessor.from_pretrained(MODEL, trust_remote_code=True)
    _state["model"] = AutoModelForCausalLM.from_pretrained(
        MODEL, use_safetensors=True, trust_remote_code=True,
        torch_dtype=dtype, device_map="cuda",
    ).eval()


def _decode_audio(b64: str):
    import numpy as np  # noqa: F401  (soundfile returns ndarray)

    wav, sr = sf.read(io.BytesIO(base64.b64decode(b64)))
    if getattr(wav, "ndim", 1) > 1:  # stereo -> mono
        wav = wav.mean(axis=1)
    if sr != TARGET_SR:
        # Lightweight linear resample; swap for torchaudio/librosa for quality.
        import numpy as np

        n = int(len(wav) * TARGET_SR / sr)
        wav = np.interp(np.linspace(0, len(wav), n, endpoint=False),
                        np.arange(len(wav)), wav)
    return wav


def _split(messages: list[dict]) -> tuple[str, list]:
    """Pull the text prompt and audio waveforms out of OpenAI-style messages."""
    text_parts, audios = [], []
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            text_parts.append(content)
        elif isinstance(content, list):
            for part in content:
                if part.get("type") == "text":
                    text_parts.append(part["text"])
                elif part.get("type") == "input_audio":
                    audios.append(_decode_audio(part["input_audio"]["data"]))
    return "\n".join(text_parts), audios


class ChatRequest(BaseModel):
    model: str | None = None
    messages: list[dict]
    max_tokens: int = 2048
    temperature: float = 0.1
    # vLLM-only knobs the app may send; accepted and ignored here.
    extra_body: dict | None = None


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": SERVED, "object": "model"}]}


@app.post("/v1/chat/completions")
def chat(req: ChatRequest):
    _load()
    proc, model = _state["processor"], _state["model"]
    prompt, audios = _split(req.messages)

    # MERaLiON uses an audio placeholder in its chat template.
    conversation = [{"role": "user", "content": "<SpeechHere>\n" + prompt}]
    chat_prompt = proc.tokenizer.apply_chat_template(
        conversation, tokenize=False, add_generation_prompt=True
    )
    inputs = proc(text=chat_prompt, audios=audios or None, return_tensors="pt")
    inputs = {k: v.to("cuda") for k, v in inputs.items()}

    with torch.no_grad():
        out = model.generate(
            **inputs, max_new_tokens=req.max_tokens,
            do_sample=req.temperature > 0, temperature=max(req.temperature, 1e-5),
        )
    gen = out[:, inputs["input_ids"].shape[1]:]
    text = proc.tokenizer.batch_decode(gen, skip_special_tokens=True)[0]

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
