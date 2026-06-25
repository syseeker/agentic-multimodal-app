"""image-extract — OCR / scene / entities from photos (Qwen3-VL).

Replaces ad-hoc image inspection. Handles screenshots (chat captures, bank
transfers), photos of documents, and scene photos from seized devices.
"""
from __future__ import annotations

import base64
from pathlib import Path

from ..llm import structured_complete, vlm_client
from ..models import ExtractionResult, Modality

SYSTEM = (
    "You are a forensic vision analyst. Read all visible text (OCR) and describe "
    "relevant objects/people/places in the image. Extract entities and any "
    "relationships implied by the image (e.g. a bank-transfer screenshot implies "
    "a money transfer between accounts). Quote OCR'd text as 'evidence'; set "
    "'source' to the asset id. Do not speculate beyond what is visible."
)


def _data_url(path: str) -> str:
    raw = Path(path).read_bytes()
    ext = Path(path).suffix.lstrip(".").lower() or "png"
    b64 = base64.b64encode(raw).decode()
    return f"data:image/{ext};base64,{b64}"


def extract_image(asset_id: str, path: str) -> ExtractionResult:
    client, model = vlm_client()
    messages = [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": f"asset_id: {asset_id}\nReturn an ExtractionResult."},
                {"type": "image_url", "image_url": {"url": _data_url(path)}},
            ],
        },
    ]
    result = structured_complete(client, model, messages, ExtractionResult, max_tokens=2560)
    result.asset_id = asset_id
    result.modality = Modality.image
    return result
