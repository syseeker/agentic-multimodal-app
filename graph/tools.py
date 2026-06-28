"""
Sherlock graph tools — callable by AI-Q agent (Phase 7) or directly from ingest pipeline.

Three tools:
  extract_entities(case_id, content, content_type, source_file)
      LLM → structured entities+relations → write to Neo4j
  graph_query(case_id, query_type)
      Read entities/relations from Neo4j for a case
  graph_analyze(case_id, algorithm)
      Run NetworkX/cuGraph algorithms on the case subgraph
"""

from __future__ import annotations
import json
import os
import re
import networkx as nx
from neo4j import GraphDatabase
from openai import OpenAI

from graph.schema import EXTRACTION_SYSTEM_PROMPT, CONSTRAINTS

# ── Connection ────────────────────────────────────────────────────────────────

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASS", "sherlock_dev")

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://integrate.api.nvidia.com/v1")
LLM_MODEL = os.getenv("LLM_NAME", "nvidia/nvidia-nemotron-nano-9b-v2")
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")


def _neo4j_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))


def _llm_client():
    return OpenAI(base_url=LLM_BASE_URL, api_key=NVIDIA_API_KEY)


def init_schema():
    """Create constraints and indexes. Idempotent — safe to call on every startup."""
    with _neo4j_driver() as driver:
        with driver.session() as session:
            for stmt in CONSTRAINTS:
                session.run(stmt)


# ── Tool 1: extract_entities ──────────────────────────────────────────────────

def extract_entities(
    case_id: str,
    content: str,
    content_type: str = "text",
    source_file: str = "",
) -> dict:
    """
    Extract entities and relations from content, write to Neo4j.

    Args:
        case_id:      e.g. "SC-2024-03C5F0E4"
        content:      raw text (case report, transcript, chat, image caption, etc.)
        content_type: "text" | "transcript" | "chat" | "image_caption" | "video_caption"
        source_file:  original filename for provenance

    Returns:
        {"entities_written": int, "relations_written": int, "entities": [...], "relations": [...]}
    """
    client = _llm_client()
    user_prompt = f"Case ID: {case_id}\nContent type: {content_type}\nSource: {source_file}\n\n---\n{content[:6000]}"

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=4096,
    )

    raw = response.choices[0].message.content or ""
    # Strip markdown fences
    raw = re.sub(r"```(?:json)?|```", "", raw).strip()
    # Find JSON object boundaries
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        return {"entities_written": 0, "relations_written": 0, "entities": [], "relations": [], "warning": "No JSON in response"}
    raw = raw[start:end]
    try:
        extracted = json.loads(raw)
    except json.JSONDecodeError as e:
        return {"entities_written": 0, "relations_written": 0, "entities": [], "relations": [], "warning": f"JSON parse error: {e}"}

    entities = extracted.get("entities", [])
    relations = extracted.get("relations", [])

    _write_to_neo4j(case_id, entities, relations, source_file)

    return {
        "entities_written": len(entities),
        "relations_written": len(relations),
        "entities": entities,
        "relations": relations,
    }


def _write_to_neo4j(case_id: str, entities: list, relations: list, source_file: str):
    with _neo4j_driver() as driver:
        with driver.session() as session:
            # Ensure Case node exists
            session.run(
                "MERGE (c:Case {case_id: $case_id}) SET c.updated = timestamp()",
                case_id=case_id,
            )
            # Write entities
            for ent in entities:
                label = ent.get("label", "Unknown")
                if label == "Case":
                    continue  # Case node already MERGEd above; skip to avoid uniqueness constraint violation
                name = ent.get("name") or ent.get("id") or ""
                if not name:
                    continue  # skip entities with no name/id — MERGE requires non-null
                props = {k: v for k, v in ent.items() if k != "label" and v is not None}
                props["case_id"] = case_id
                props["source"] = source_file
                session.run(
                    f"MERGE (n:{label} {{name: $name, case_id: $case_id}}) SET n += $props",
                    name=name,
                    case_id=case_id,
                    props=props,
                )
            # Write relations
            for rel in relations:
                fl, fn = rel.get("from_label", "Person"), rel.get("from_name", "")
                tl, tn = rel.get("to_label", "Case"), rel.get("to_name", case_id)
                rtype = rel.get("relation", "RELATED_TO").upper().replace(" ", "_")
                ctx = rel.get("context", "")
                if not fn or not tn:
                    continue
                session.run(
                    f"""
                    MATCH (a:{fl} {{case_id: $case_id}})
                    WHERE a.name = $from_name OR a.id = $from_name
                    MATCH (b:{tl})
                    WHERE b.name = $to_name OR b.id = $to_name OR b.case_id = $to_name
                    MERGE (a)-[r:{rtype}]->(b)
                    SET r.context = $ctx, r.source = $source
                    """,
                    case_id=case_id,
                    from_name=fn,
                    to_name=tn,
                    ctx=ctx,
                    source=rel.get("source_file", ""),
                )


# ── Tool 2: graph_query ───────────────────────────────────────────────────────

def graph_query(case_id: str, query_type: str = "all_entities") -> dict:
    """
    Query Neo4j for a case's entity graph.

    query_type options:
      "all_entities"    — all nodes for this case
      "persons"         — only Person nodes with roles
      "relationships"   — all relationships between entities
      "suspects"        — persons with SUSPECT_IN relation
      "associates"      — ASSOCIATED_WITH pairs
    """
    with _neo4j_driver() as driver:
        with driver.session() as session:
            if query_type == "persons":
                result = session.run(
                    "MATCH (p:Person {case_id: $cid}) RETURN p.name AS name, p.role AS role, p.nationality AS nationality, p.age AS age",
                    cid=case_id,
                )
                return {"persons": [dict(r) for r in result]}

            elif query_type == "suspects":
                result = session.run(
                    "MATCH (p:Person)-[:SUSPECT_IN]->(c:Case {case_id: $cid}) RETURN p.name AS name, p.nationality AS nationality, p.age AS age",
                    cid=case_id,
                )
                return {"suspects": [dict(r) for r in result]}

            elif query_type == "associates":
                result = session.run(
                    "MATCH (a:Person {case_id: $cid})-[r:ASSOCIATED_WITH]->(b:Person {case_id: $cid}) RETURN a.name AS person_a, b.name AS person_b, r.context AS context",
                    cid=case_id,
                )
                return {"associates": [dict(r) for r in result]}

            elif query_type == "relationships":
                result = session.run(
                    """
                    MATCH (a {case_id: $cid})-[r]->(b)
                    WHERE b.case_id = $cid OR b.case_id IS NULL
                    RETURN labels(a)[0] AS from_type, a.name AS from_name,
                           type(r) AS relation,
                           labels(b)[0] AS to_type, b.name AS to_name,
                           r.context AS context
                    LIMIT 200
                    """,
                    cid=case_id,
                )
                return {"relationships": [dict(r) for r in result]}

            else:  # all_entities
                result = session.run(
                    """
                    MATCH (n {case_id: $cid})
                    RETURN labels(n)[0] AS type, n.name AS name, properties(n) AS props
                    """,
                    cid=case_id,
                )
                return {"entities": [dict(r) for r in result]}


# ── Tool 3: graph_analyze ─────────────────────────────────────────────────────

def graph_analyze(case_id: str, algorithm: str = "centrality") -> dict:
    """
    Run graph algorithms on the case entity graph.

    algorithm options:
      "centrality"      — degree + betweenness centrality (key players)
      "communities"     — community detection (cliques/groups)
      "shortest_path"   — shortest path between all suspect pairs
    """
    G = _build_networkx_graph(case_id)
    if G.number_of_nodes() == 0:
        return {"error": f"No graph data found for case {case_id}"}

    if algorithm == "centrality":
        degree = nx.degree_centrality(G)
        try:
            betweenness = nx.betweenness_centrality(G)
        except Exception:
            betweenness = {}
        ranked = sorted(
            [(n, degree.get(n, 0), betweenness.get(n, 0)) for n in G.nodes()],
            key=lambda x: x[1] + x[2],
            reverse=True,
        )
        return {
            "algorithm": "centrality",
            "key_entities": [
                {"name": n, "degree_centrality": round(d, 3), "betweenness_centrality": round(b, 3)}
                for n, d, b in ranked[:10]
            ],
        }

    elif algorithm == "communities":
        undirected = G.to_undirected()
        try:
            communities = list(nx.community.greedy_modularity_communities(undirected))
            return {
                "algorithm": "communities",
                "num_communities": len(communities),
                "communities": [
                    {"id": i, "members": list(c), "size": len(c)}
                    for i, c in enumerate(communities)
                ],
            }
        except Exception as e:
            return {"algorithm": "communities", "error": str(e)}

    elif algorithm == "shortest_path":
        # Find shortest paths between all suspect pairs
        suspects = [n for n, d in G.nodes(data=True) if d.get("role") == "suspect"]
        paths = []
        undirected = G.to_undirected()
        for i, s1 in enumerate(suspects):
            for s2 in suspects[i + 1 :]:
                try:
                    path = nx.shortest_path(undirected, s1, s2)
                    paths.append({"from": s1, "to": s2, "path": path, "hops": len(path) - 1})
                except nx.NetworkXNoPath:
                    paths.append({"from": s1, "to": s2, "path": None, "hops": -1})
        return {"algorithm": "shortest_path", "suspect_paths": paths}

    return {"error": f"Unknown algorithm: {algorithm}"}


def _build_networkx_graph(case_id: str) -> nx.DiGraph:
    """Pull case graph from Neo4j into NetworkX."""
    G = nx.DiGraph()
    with _neo4j_driver() as driver:
        with driver.session() as session:
            nodes = session.run(
                "MATCH (n {case_id: $cid}) RETURN n.name AS name, labels(n)[0] AS label, properties(n) AS props",
                cid=case_id,
            )
            for rec in nodes:
                name = rec["name"]
                if name:
                    G.add_node(name, label=rec["label"], **{k: v for k, v in rec["props"].items() if k != "case_id"})

            rels = session.run(
                """
                MATCH (a {case_id: $cid})-[r]->(b)
                RETURN a.name AS from_name, type(r) AS rel_type, b.name AS to_name
                """,
                cid=case_id,
            )
            for rec in rels:
                if rec["from_name"] and rec["to_name"]:
                    G.add_edge(rec["from_name"], rec["to_name"], relation=rec["rel_type"])
    return G
