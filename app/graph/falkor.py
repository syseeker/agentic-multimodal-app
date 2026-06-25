"""FalkorDB graph store for the entity-relationship network (per case)."""
from __future__ import annotations

from functools import lru_cache

from ..models import ExtractionResult, Relationship
from ..settings import get_settings


@lru_cache
def _db():
    from falkordb import FalkorDB

    s = get_settings()
    return FalkorDB(host=s.falkordb_host, port=s.falkordb_port)


def _g(case_id: str):
    # FalkorDB graph names can't contain ':' etc.; normalize.
    return _db().select_graph(f"case_{case_id.replace('-', '_')}")


def _esc(v: str) -> str:
    return (v or "").replace("\\", "\\\\").replace("'", "\\'")


def upsert_extraction(case_id: str, ex: ExtractionResult) -> dict:
    """MERGE entities and relationships from one extraction into the case graph."""
    g = _g(case_id)
    for e in ex.entities:
        g.query(
            "MERGE (n:Entity {id:$id}) "
            "SET n.name=$name, n.type=$type, n.source=$source, "
            "    n.confidence=$conf, n.aliases=$aliases",
            {
                "id": e.id, "name": e.name, "type": e.type.value,
                "source": e.source, "conf": e.confidence,
                "aliases": ",".join(e.aliases),
            },
        )
    for r in ex.relationships:
        g.query(
            "MATCH (a:Entity {id:$src}) MATCH (b:Entity {id:$tgt}) "
            "MERGE (a)-[rel:REL {relation:$relation}]->(b) "
            "SET rel.evidence=$evidence, rel.source=$source, rel.confidence=$conf",
            {
                "src": r.source_id, "tgt": r.target_id, "relation": r.relation,
                "evidence": r.evidence, "source": r.source, "conf": r.confidence,
            },
        )
    return {"entities": len(ex.entities), "relationships": len(ex.relationships)}


def fetch_graph(case_id: str) -> dict:
    """Return nodes + edges for the UI graph viz."""
    g = _g(case_id)
    nodes = g.query("MATCH (n:Entity) RETURN n.id, n.name, n.type, n.confidence")
    edges = g.query(
        "MATCH (a:Entity)-[r:REL]->(b:Entity) "
        "RETURN a.id, b.id, r.relation, r.evidence, r.confidence"
    )
    return {
        "nodes": [
            {"id": r[0], "name": r[1], "type": r[2], "confidence": r[3]}
            for r in nodes.result_set
        ],
        "edges": [
            {"source": r[0], "target": r[1], "relation": r[2],
             "evidence": r[3], "confidence": r[4]}
            for r in edges.result_set
        ],
    }


def edgelist(case_id: str) -> list[tuple[str, str]]:
    g = _g(case_id)
    res = g.query("MATCH (a:Entity)-[:REL]->(b:Entity) RETURN a.id, b.id")
    return [(r[0], r[1]) for r in res.result_set]


def reset(case_id: str) -> None:
    try:
        _g(case_id).delete()
    except Exception:
        pass
