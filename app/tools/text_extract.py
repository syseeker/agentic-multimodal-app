"""text-extract — entities + relationships from chat/text (Qwen3).

Replaces the click-through "Chat Log Analyzer". Returns schema-valid ExtractionResult.
"""
from __future__ import annotations

from ..llm import structured_complete, text_client
from ..models import ExtractionResult, Modality

SYSTEM = (
    "You are a forensic text analyst. Extract entities (people, orgs, phones, "
    "accounts, money, locations, items, events) and the relationships between "
    "them from the provided messages. Use stable ids like 'person:john-tan'. "
    "Every relationship must quote the supporting text in 'evidence' and set "
    "'source' to the given asset id. Do not invent facts."
)


def extract_text(asset_id: str, content: str) -> ExtractionResult:
    client, model = text_client()
    messages = [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": (
                f"asset_id: {asset_id}\n"
                f"modality: text\n\n"
                f"--- MESSAGES ---\n{content}\n--- END ---\n\n"
                "Return an ExtractionResult."
            ),
        },
    ]
    result = structured_complete(client, model, messages, ExtractionResult, max_tokens=3072)
    # Enforce invariants the model occasionally drifts on.
    result.asset_id = asset_id
    result.modality = Modality.text
    return result
