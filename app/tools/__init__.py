"""Agent tools — the former linear 'skills', now callable by the orchestrator."""
from __future__ import annotations

from ..models import Asset, ExtractionResult, Modality, SentimentResult
from .audio_extract import extract_audio, transcribe_audio
from .graph_rag import build_graph, graph_view, index_documents, query_case
from .image_extract import extract_image
from .sentiment import analyze_audio_sentiment, analyze_text_sentiment
from .text_extract import extract_text


def ingest_asset(asset: Asset) -> ExtractionResult:
    """Dispatch an asset to the right extractor by modality."""
    if asset.modality == Modality.text:
        from pathlib import Path

        content = Path(asset.path).read_text(encoding="utf-8", errors="ignore")
        return extract_text(asset.asset_id, content)
    if asset.modality == Modality.image:
        return extract_image(asset.asset_id, asset.path)
    if asset.modality == Modality.audio:
        return extract_audio(asset.asset_id, asset.path)
    raise ValueError(f"unknown modality: {asset.modality}")


def asset_sentiment(asset: Asset) -> SentimentResult:
    if asset.modality == Modality.audio:
        return analyze_audio_sentiment(asset.asset_id, asset.path)
    from pathlib import Path

    content = Path(asset.path).read_text(encoding="utf-8", errors="ignore")
    return analyze_text_sentiment(asset.asset_id, content)


__all__ = [
    "ingest_asset", "asset_sentiment",
    "extract_text", "extract_image", "extract_audio", "transcribe_audio",
    "analyze_text_sentiment", "analyze_audio_sentiment",
    "build_graph", "index_documents", "query_case", "graph_view",
]
