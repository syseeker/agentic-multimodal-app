"""sentiment — fused text + paralinguistic sentiment.

Text sentiment via Qwen3; audio sentiment fuses MERaLiON-3 paralinguistic cues
(tone, rhythm, emotion) with the transcript. This is the "synthesize statements
with paralinguistic analysis" capability, now callable by the agent.
"""
from __future__ import annotations

from ..llm import structured_complete, text_client
from ..models import Modality, SentimentResult
from .audio_extract import transcribe_audio

_SYS = (
    "You are a forensic sentiment analyst. Judge the affect of the content and, "
    "when paralinguistic cues are provided, weigh them. Return a SentimentResult "
    "with label, score in [-1,1], the paralinguistic dict, and a short rationale."
)


def analyze_text_sentiment(asset_id: str, content: str) -> SentimentResult:
    client, model = text_client()
    messages = [
        {"role": "system", "content": _SYS},
        {"role": "user", "content": f"asset_id: {asset_id}\nmodality: text\n\n{content}"},
    ]
    r = structured_complete(client, model, messages, SentimentResult, max_tokens=768)
    r.asset_id, r.modality, r.source = asset_id, Modality.text, asset_id
    return r


def analyze_audio_sentiment(asset_id: str, path: str) -> SentimentResult:
    transcript = transcribe_audio(asset_id, path)
    cues = [
        {"emotion": s.emotion, "tone": s.tone}
        for s in transcript.segments
        if s.emotion or s.tone
    ]
    client, model = text_client()
    messages = [
        {"role": "system", "content": _SYS},
        {
            "role": "user",
            "content": (
                f"asset_id: {asset_id}\nmodality: audio\n\n"
                f"Transcript:\n{transcript.full_text}\n\n"
                f"Paralinguistic cues (from MERaLiON-3): {cues}"
            ),
        },
    ]
    r = structured_complete(client, model, messages, SentimentResult, max_tokens=768)
    r.asset_id, r.modality, r.source = asset_id, Modality.audio, asset_id
    # Surface the strongest cue if the model left the dict empty.
    if not r.paralinguistic and cues:
        r.paralinguistic = {k: v for k, v in cues[0].items() if v}
    return r
