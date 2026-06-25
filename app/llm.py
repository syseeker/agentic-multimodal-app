"""OpenAI-compatible clients for the local vLLM servers + structured-output helper.

We use vLLM's guided decoding (`guided_json`) so tools get schema-valid JSON back,
matching the original app's Pydantic/JSON-mode contract.
"""
from __future__ import annotations

import json
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel

from .settings import get_settings

T = TypeVar("T", bound=BaseModel)


def _client(base_url: str) -> OpenAI:
    s = get_settings()
    return OpenAI(base_url=base_url, api_key=s.serving_api_key)


def text_client() -> tuple[OpenAI, str]:
    s = get_settings()
    return _client(s.text_base_url), s.text_served


def vlm_client() -> tuple[OpenAI, str]:
    s = get_settings()
    return _client(s.vlm_base_url), s.vlm_served


def audio_client() -> tuple[OpenAI, str]:
    s = get_settings()
    return _client(s.audio_base_url), s.audio_served


def structured_complete(
    client: OpenAI,
    model: str,
    messages: list[dict],
    schema: type[T],
    temperature: float = 0.1,
    max_tokens: int = 2048,
) -> T:
    """Chat completion constrained to `schema`.

    Works across providers via `STRUCT_MODE` (see settings): local vLLM
    (`guided_json`), NVIDIA NIM (`nvext`), or OpenAI-style `response_format`.
    A schema hint is always added to the prompt so even `prompt` mode degrades
    gracefully, and parsing is defensive.
    """
    mode = get_settings().struct_mode
    schema_json = schema.model_json_schema()

    aug = list(messages) + [{
        "role": "system",
        "content": (
            "Respond with ONLY a single JSON object matching this schema "
            f"(no prose, no markdown fences): {json.dumps(schema_json)}"
        ),
    }]

    kwargs: dict = dict(model=model, messages=aug, temperature=temperature, max_tokens=max_tokens)
    if mode == "guided_json":
        kwargs["extra_body"] = {"guided_json": schema_json}
    elif mode == "nvext":
        kwargs["extra_body"] = {"nvext": {"guided_json": schema_json}}
    elif mode == "json_schema":
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": schema.__name__, "schema": schema_json},
        }
    elif mode == "json_object":
        kwargs["response_format"] = {"type": "json_object"}
    # mode == "prompt": rely on the schema hint above only.

    resp = client.chat.completions.create(**kwargs)
    content = resp.choices[0].message.content or "{}"
    try:
        return schema.model_validate_json(content)
    except Exception:
        return schema.model_validate(safe_json(content))


def complete(
    client: OpenAI,
    model: str,
    messages: list[dict],
    temperature: float = 0.2,
    max_tokens: int = 1024,
) -> str:
    resp = client.chat.completions.create(
        model=model, messages=messages, temperature=temperature, max_tokens=max_tokens
    )
    return resp.choices[0].message.content or ""


def safe_json(text: str) -> dict:
    """Best-effort parse for non-guided responses."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
    return {}
