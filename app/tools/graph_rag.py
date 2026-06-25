"""graph-build + rag — load extractions into the graph, analyze it, retrieve.

This is the CA-RAG-style layer: a FalkorDB graph for structured relations + a
vector store for free-text recall, plus cuGraph analytics to surface key players.
"""
from __future__ import annotations

from ..graph import analytics, falkor
from ..models import ExtractionResult, GraphStats
from ..retrieval import add_documents, search


def build_graph(case_id: str, extractions: list[ExtractionResult]) -> GraphStats:
    """Load all extractions into the case graph and run GPU analytics."""
    n_e = n_r = 0
    for ex in extractions:
        counts = falkor.upsert_extraction(case_id, ex)
        n_e += counts["entities"]
        n_r += counts["relationships"]
    a = analytics.analyze(case_id)
    return GraphStats(
        nodes=n_e, edges=n_r,
        key_players=a["key_players"], communities=a["communities"],
    )


def index_documents(case_id: str, extractions: list[ExtractionResult]) -> int:
    """Index extraction summaries + relationship evidence for RAG recall."""
    docs: list[dict] = []
    for ex in extractions:
        if ex.summary:
            docs.append({"text": ex.summary, "source": ex.asset_id})
        for r in ex.relationships:
            docs.append({"text": f"{r.relation}: {r.evidence}", "source": r.source})
    return add_documents(case_id, docs) if docs else 0


def query_case(case_id: str, question: str, k: int = 5) -> list[dict]:
    """Vector recall over the indexed case material."""
    return search(case_id, question, k)


def graph_view(case_id: str) -> dict:
    return falkor.fetch_graph(case_id)
