"""audio-extract — ASR + paralinguistics from statements/口供 (MERaLiON-3).

Replaces the click-through "Statement Analyzer". MERaLiON-3 transcribes AND reports
paralinguistic cues (tone, rhythm, emotion). The transcript then feeds
text-extract so spoken entities/relationships reach the graph.
"""
from __future__ import annotations

import base64
from pathlib import Path

from ..llm import audio_client, complete, structured_complete, text_client
from ..models import ExtractionResult, Modality, TranscriptResult
from .text_extract import extract_text

# MERaLiON returns free text (the Transformers shim can't do guided JSON), so we
# ask it to transcribe + annotate cues, then structure the result with the text
# model. This also works unchanged once MERaLiON gets native vLLM support.
SPEECH_PROMPT = (
    "Transcribe this statement accurately. Segment by speaker. For each segment, "
    "note paralinguistic cues in brackets: emotion, tone (tense/calm), and rhythm "
    "(e.g. rushed/hesitant). Preserve the spoken language."
)

STRUCT_SYSTEM = (
    "Convert the annotated transcript into a TranscriptResult. Each segment's "
    "bracketed cues map to the emotion/tone fields. Set asset_id as given."
)


def _audio_part(path: str) -> dict:
    raw = Path(path).read_bytes()
    fmt = Path(path).suffix.lstrip(".").lower() or "wav"
    b64 = base64.b64encode(raw).decode()
    return {"type": "input_audio", "input_audio": {"data": b64, "format": fmt}}


def transcribe_audio(asset_id: str, path: str) -> TranscriptResult:
    # 1. MERaLiON-3: audio -> annotated free-text transcript.
    aclient, amodel = audio_client()
    raw = complete(
        aclient, amodel,
        messages=[{"role": "user",
                   "content": [{"type": "text", "text": SPEECH_PROMPT}, _audio_part(path)]}],
        temperature=0.1, max_tokens=3072,
    )
    # 2. Text model: structure it (guided JSON).
    tclient, tmodel = text_client()
    result = structured_complete(
        tclient, tmodel,
        messages=[{"role": "system", "content": STRUCT_SYSTEM},
                  {"role": "user", "content": f"asset_id: {asset_id}\n\n{raw}"}],
        schema=TranscriptResult, max_tokens=3072,
    )
    result.asset_id = asset_id
    if not result.full_text:
        result.full_text = raw if not result.segments else " ".join(s.text for s in result.segments)
    return result


def extract_audio(asset_id: str, path: str) -> ExtractionResult:
    """Full pipeline: transcribe (MERaLiON) -> extract entities (Qwen3)."""
    transcript = transcribe_audio(asset_id, path)
    extraction = extract_text(asset_id, transcript.full_text)
    extraction.modality = Modality.audio
    extraction.summary = (
        f"Statement transcript ({transcript.language}); "
        f"{len(transcript.segments)} segments. " + extraction.summary
    )
    return extraction
