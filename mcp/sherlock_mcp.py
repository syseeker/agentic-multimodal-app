#!/usr/bin/env python3
"""
Sherlock MCP server — exposes graph and audio tools to AI-Q via MCP.

Runs on :9901 (streamable-http). AI-Q connects via mcp_client in config YAML.

Tools exposed:
  graph_query        — retrieve entities/relations for a case from Neo4j
  graph_analyze      — run centrality/communities/shortest_path algorithms
  extract_entities   — LLM-driven ER: extract entities from text → Neo4j
  list_cases         — list all case IDs with entity counts in Neo4j
"""
import json
import os
import sys
from pathlib import Path

# Load .env from repo root before importing graph tools
REPO_ROOT = Path(__file__).parent.parent
env_file = REPO_ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        val = val.split("#")[0].strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val

sys.path.insert(0, str(REPO_ROOT))

from graph.tools import extract_entities, graph_query, graph_analyze, init_schema
from neo4j import GraphDatabase

import fastmcp

mcp = fastmcp.FastMCP(
    "sherlock-tools",
    instructions=(
        "Forensic investigation tools for the Sherlock case analysis system. "
        "Use graph_query to retrieve entities and suspects from a case. "
        "Use graph_analyze to find key actors via centrality or community detection. "
        "Use extract_entities to index new evidence text into the case graph. "
        "All tools require a case_id (format: SC-YYYY-XXXXXXXX)."
    ),
)


@mcp.tool
def graph_query_tool(
    case_id: str,
    query_type: str = "all_entities",
) -> str:
    """
    Query the forensic entity graph for a case.

    Use this to retrieve persons of interest, suspects, witnesses, organizations,
    locations, and evidence items associated with a Singapore Police Force case.

    Args:
        case_id:    Case identifier, e.g. "SC-2024-03C5F0E4"
        query_type: One of:
                      "all_entities"   — all nodes in the case graph
                      "persons"        — all persons (suspects, witnesses, victims)
                      "suspects"       — persons with SUSPECT_IN relation
                      "associates"     — persons with ASSOCIATED_WITH relation
                      "relationships"  — all relationships between entities

    Returns:
        JSON string with query results.
    """
    result = graph_query(case_id, query_type)
    return json.dumps(result, indent=2)


@mcp.tool
def graph_analyze_tool(
    case_id: str,
    algorithm: str = "centrality",
) -> str:
    """
    Run a graph algorithm to identify key entities in a forensic case.

    Use this to find the most connected actors (centrality), detect groups or
    networks (communities), or find the shortest link between two persons.

    Args:
        case_id:   Case identifier, e.g. "SC-2024-03C5F0E4"
        algorithm: One of:
                     "centrality"     — rank entities by connection count (finds key actors)
                     "communities"    — detect groups/networks of related entities
                     "shortest_path"  — shortest link between any two key persons

    Returns:
        JSON string with algorithm results including key_entities ranked by importance.
    """
    result = graph_analyze(case_id, algorithm)
    return json.dumps(result, indent=2)


@mcp.tool
def extract_entities_tool(
    case_id: str,
    content: str,
    content_type: str = "text",
    source_file: str = "",
) -> str:
    """
    Extract entities and relationships from evidence text and store in the case graph.

    Use this when new evidence (a document, witness statement, or chat log) has been
    submitted and needs to be indexed into the forensic entity graph. The LLM extracts
    persons, organizations, locations, and evidence items with their relationships.

    Args:
        case_id:      Case identifier, e.g. "SC-2024-03C5F0E4"
        content:      Raw text content (case report, transcript, WhatsApp chat, etc.)
        content_type: One of "text", "transcript", "chat", "image_caption"
        source_file:  Original filename for provenance (e.g. "witness_statement.txt")

    Returns:
        JSON string with counts of entities and relations written to Neo4j.
    """
    result = extract_entities(case_id, content, content_type, source_file)
    return json.dumps(result, indent=2)


@mcp.tool
def list_cases() -> str:
    """
    List all forensic cases in the graph database with entity counts.

    Use this to discover which cases are available before querying a specific case,
    or to get an overview of the investigation workload.

    Returns:
        JSON string with list of {case_id, entity_count, relation_count} objects.
    """
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    pw = os.environ.get("NEO4J_PASS", "sherlock_dev")
    try:
        with GraphDatabase.driver(uri, auth=(user, pw)) as driver:
            with driver.session() as session:
                rows = session.run(
                    """
                    MATCH (c:Case)
                    OPTIONAL MATCH (n {case_id: c.case_id}) WHERE NOT n:Case
                    OPTIONAL MATCH (c)-[r]-()
                    RETURN c.case_id AS case_id,
                           count(DISTINCT n) AS entities,
                           count(DISTINCT r) AS relations
                    ORDER BY c.case_id
                    """
                ).data()
        return json.dumps(rows, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


if __name__ == "__main__":
    init_schema()
    print("Sherlock MCP server starting on http://0.0.0.0:9901/mcp", flush=True)
    mcp.run(transport="streamable-http", host="0.0.0.0", port=9901)
