"""Case-file RAG. Milvus (cuVS GPU) is the default; Chroma is a no-GPU fallback.

Milvus embeddings come from a NeMo Retriever embedding endpoint (OpenAI-compatible,
configurable). Chroma uses its bundled MiniLM so the dev fallback runs with zero
extra services.
"""
from __future__ import annotations

from functools import lru_cache

from .settings import get_settings

COLLECTION_DIM = 1024  # NeMo Retriever (llama-embed / e5) family default


# ── Embeddings (Milvus path) ──────────────────────────────────────────────
def _embed(texts: list[str]) -> list[list[float]]:
    from openai import OpenAI

    s = get_settings()
    client = OpenAI(base_url=s.text_base_url, api_key=s.serving_api_key)
    # Point EMBED at a NeMo Retriever NIM in production; here we reuse the
    # serving stack's embeddings route.
    resp = client.embeddings.create(model="nemo-retriever-embed", input=texts)
    return [d.embedding for d in resp.data]


# ── Milvus backend ─────────────────────────────────────────────────────────
class _Milvus:
    def __init__(self):
        from pymilvus import MilvusClient

        s = get_settings()
        self.client = MilvusClient(uri=s.milvus_uri)

    def _ensure(self, name: str):
        if not self.client.has_collection(name):
            # GPU CAGRA (cuVS) index for ANN.
            self.client.create_collection(name, dimension=COLLECTION_DIM, metric_type="COSINE")

    def add(self, case_id: str, docs: list[dict]):
        name = f"case_{case_id}"
        self._ensure(name)
        vecs = _embed([d["text"] for d in docs])
        rows = [
            {"id": i, "vector": v, "text": d["text"], "source": d.get("source", "")}
            for i, (v, d) in enumerate(zip(vecs, docs))
        ]
        self.client.insert(name, rows)

    def search(self, case_id: str, query: str, k: int) -> list[dict]:
        name = f"case_{case_id}"
        if not self.client.has_collection(name):
            return []
        qv = _embed([query])[0]
        hits = self.client.search(name, data=[qv], limit=k, output_fields=["text", "source"])
        return [
            {"text": h["entity"]["text"], "source": h["entity"]["source"], "score": h["distance"]}
            for h in hits[0]
        ]


# ── Chroma backend (dev fallback) ──────────────────────────────────────────
class _Chroma:
    def __init__(self):
        import chromadb

        s = get_settings()
        self.client = chromadb.PersistentClient(path=s.chroma_path)

    def add(self, case_id: str, docs: list[dict]):
        col = self.client.get_or_create_collection(f"case_{case_id}")
        col.add(
            ids=[f"{case_id}-{i}" for i in range(len(docs))],
            documents=[d["text"] for d in docs],
            metadatas=[{"source": d.get("source", "")} for d in docs],
        )

    def search(self, case_id: str, query: str, k: int) -> list[dict]:
        try:
            col = self.client.get_collection(f"case_{case_id}")
        except Exception:
            return []
        res = col.query(query_texts=[query], n_results=k)
        out = []
        for doc, meta, dist in zip(
            res["documents"][0], res["metadatas"][0], res["distances"][0]
        ):
            out.append({"text": doc, "source": meta.get("source", ""), "score": dist})
        return out


@lru_cache
def _store():
    return _Milvus() if get_settings().vector_backend == "milvus" else _Chroma()


def add_documents(case_id: str, docs: list[dict]) -> int:
    _store().add(case_id, docs)
    return len(docs)


def search(case_id: str, query: str, k: int = 5) -> list[dict]:
    return _store().search(case_id, query, k)
