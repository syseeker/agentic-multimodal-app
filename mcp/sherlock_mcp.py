#!/usr/bin/env python3
"""
Sherlock MCP server — exposes graph and audio tools to AI-Q via MCP.

Runs on :9901 (streamable-http). AI-Q connects via mcp_client in config YAML.

Graph tools:
  graph_query        — retrieve entities/relations for a case from Neo4j
  graph_analyze      — run centrality/communities/shortest_path algorithms
  extract_entities   — LLM-driven ER: extract entities from text → Neo4j
  list_cases         — list all case IDs with entity counts in Neo4j

Audio tools:
  list_audio_files   — list audio evidence files and transcript/paralinguistics status
  get_audio_analysis — return full transcripts + MERaLiON paralinguistics for a case
  analyze_audio      — transcribe one audio file (Parakeet ASR) + paralinguistics (MERaLiON-3-10B)
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


# ── Audio tools ───────────────────────────────────────────────────────────────

CASES_DIR = REPO_ROOT / "data" / "cases"
AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".wma"}


@mcp.tool
def list_audio_files(case_id: str) -> str:
    """
    List audio evidence files for a case and their transcript status.

    Use before analyze_audio to see what audio evidence is available
    and whether it has already been processed.

    Args:
        case_id: Case identifier, e.g. "SC-2024-03C5F0E4"

    Returns:
        JSON list of {filename, has_transcript, has_paralinguistics} objects.
    """
    audio_dir = CASES_DIR / case_id / "audio"
    if not audio_dir.exists():
        return json.dumps({"error": f"No audio dir for case {case_id}"})
    files = []
    for f in sorted(audio_dir.iterdir()):
        if f.suffix.lower() in AUDIO_EXTS and not f.name.startswith("."):
            transcript_path = audio_dir / f"{f.stem}_transcript.txt"
            has_transcript = transcript_path.exists()
            has_para = False
            if has_transcript:
                content = transcript_path.read_text(encoding="utf-8")
                has_para = '"status": "ok"' in content or '"emotion"' in content
            files.append({
                "filename": f.name,
                "has_transcript": has_transcript,
                "has_paralinguistics": has_para,
            })
    return json.dumps(files, indent=2)


@mcp.tool
def get_audio_analysis(case_id: str) -> str:
    """
    Return the full audio analysis for a case (transcripts + paralinguistics).

    This returns the aggregated audio_analysis.txt content. If it doesn't exist,
    returns {available: false} — use analyze_audio to process audio files first.

    Args:
        case_id: Case identifier, e.g. "SC-2024-03C5F0E4"

    Returns:
        JSON with {available, transcript, paralinguistics_entries} or {available: false}.
    """
    analysis_file = CASES_DIR / case_id / "audio_analysis.txt"
    if not analysis_file.exists():
        return json.dumps({"available": False, "case_id": case_id})
    content = analysis_file.read_text(encoding="utf-8")

    # Also gather per-file paralinguistics from individual transcript files
    audio_dir = CASES_DIR / case_id / "audio"
    para_entries = []
    for tf in sorted(audio_dir.glob("*_transcript.txt")) if audio_dir.exists() else []:
        tc = tf.read_text(encoding="utf-8")
        import re as _re
        m = _re.search(r'Paralinguistics:\s*(\{.*?\})', tc, _re.DOTALL)
        if m:
            try:
                para = json.loads(m.group(1))
                source = tf.stem.replace("_transcript", "")
                para_entries.append({"source": source, "analysis": para})
            except Exception:
                pass
    return json.dumps({
        "available": True,
        "case_id": case_id,
        "transcript": content,
        "paralinguistics_entries": para_entries,
    }, indent=2)


@mcp.tool
def analyze_audio(case_id: str, filename: str) -> str:
    """
    Transcribe an audio file AND run paralinguistic analysis on it.

    Runs the full forensic audio pipeline:
      1. Parakeet RNNT Multilingual (cloud ASR) → transcript text
      2. MERaLiON-3-10B (local GPU) → language, emotion, stress level, confidence,
         speech pattern notes (Singlish markers, code-switching, hesitations)

    Use when: a specific audio file has not been processed yet, or when the investigator
    asks "what did the witness say?", "what was the suspect's emotional state?",
    "was the speaker stressed?", "what language was spoken?".

    First call loads MERaLiON-3-10B (~20 GB VRAM, ~2 min). Subsequent calls are faster.
    Falls back to transcript-only if GPU or HF_TOKEN unavailable.

    Args:
        case_id:  Case identifier, e.g. "SC-2024-03C5F0E4"
        filename: Audio filename in the case audio/ dir, e.g. "witness_interview.wav"

    Returns:
        JSON with {transcript, paralinguistics: {language, emotion, stress_level,
        confidence, notes}, transcript_file}.
    """
    import subprocess as _sp
    result = _sp.run(
        [
            sys.executable, str(REPO_ROOT / "data" / "audio" / "process_audio.py"),
            "--case-id", case_id,
            "--file", filename,
        ],
        capture_output=True, text=True, timeout=300, cwd=str(REPO_ROOT),
    )
    if result.returncode != 0:
        return json.dumps({"error": result.stderr.strip() or "process_audio.py failed"})
    try:
        # process_audio.py --file prints JSON to stdout
        out = result.stdout.strip()
        # Find last JSON object in output (there may be progress prints before it)
        last_brace = out.rfind("{")
        if last_brace >= 0:
            return out[last_brace:]
        return json.dumps({"error": "No JSON in output", "raw": out[:500]})
    except Exception as e:
        return json.dumps({"error": str(e), "raw": result.stdout[:500]})


if __name__ == "__main__":
    init_schema()
    print("Sherlock MCP server starting on http://0.0.0.0:9901/mcp", flush=True)
    mcp.run(transport="streamable-http", host="0.0.0.0", port=9901, allowed_hosts=["*"])
