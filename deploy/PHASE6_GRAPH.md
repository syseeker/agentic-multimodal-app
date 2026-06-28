# Phase 6 — Non-video ER → Shared Neo4j; cuGraph as AI-Q Tool

Custom proposal (no skill). Follows DESIGN.md §5.

## What Phase 6 delivers

1. **Neo4j Community** — shared graph store for all entity/relation data
2. **`extract_entities` tool** — LLM-driven ER from any text content → Neo4j
3. **`graph_query` tool** — retrieve entities/relations for a case
4. **`graph_analyze` tool** — cuGraph/NetworkX algorithms (centrality, communities, shortest path)
5. **Ingest wiring** — ER runs automatically after case text is ingested to RAG-BP

## Architecture

```
Evidence files (text/chat/transcript/caption)
        │
        ▼
graph/ingest_entities.py   ← called by ingest_cases.sh
        │
        ▼ LLM API (Nemotron Nano 9B via integrate.api.nvidia.com)
        │   structured JSON: entities + relations
        ▼
Neo4j (:7687)
  (:Case {case_id})
  (:Person {name, role, nationality, age, case_id})
  (:Organization {name, org_type, case_id})
  (:Location {name, district, case_id})
  (:Evidence {id, description, evidence_type, case_id})
  [SUSPECT_IN, WITNESS_IN, VICTIM_IN, ASSOCIATED_WITH, LOCATED_AT, MEMBER_OF, IMPLICATES]
        │
        ▼
graph/tools.py → graph_query() + graph_analyze()
        │
        ▼ (Phase 7)
AI-Q custom tools (registered as skills)
```

## Files

| File | Purpose |
|---|---|
| `deploy/compose.neo4j.yaml` | Neo4j Community service (amms project) |
| `graph/schema.py` | Node/relation schema + ER extraction system prompt |
| `graph/tools.py` | Three tools: extract_entities, graph_query, graph_analyze |
| `graph/ingest_entities.py` | Batch ingest runner; called by ingest_cases.sh |
| `data/sim/ingest_cases.sh` | Updated: triggers ER after RAG-BP ingest |

## Commands

```bash
# Start Neo4j
docker compose -p amms -f deploy/compose.neo4j.yaml up -d

# Run ER ingest for all cases
python3 graph/ingest_entities.py

# Run for a single case
python3 graph/ingest_entities.py --case SC-2024-03C5F0E4

# Query the graph
python3 -c "
from graph.tools import graph_query, graph_analyze
print(graph_query('SC-2024-03C5F0E4', 'suspects'))
print(graph_analyze('SC-2024-03C5F0E4', 'centrality'))
"
```

## Verification (2026-06-28)

Single case test (SC-2024-03C5F0E4):
- 15 entities, 12 relations written from 3 of 5 files
- Suspects query returns: Tan Wei Jie (Chinese national, age 23)
- Centrality correctly ranks Tan Wei Jie as highest-centrality node
- Relationships show: SUSPECT_IN, ASSOCIATED_WITH, LOCATED_AT, IMPLICATES edges

Full 20-case ingest (2026-06-28, bugs fixed — Case label + null-name entities):
- 20 cases, 457 entities, 436 relations written to Neo4j
- Zero errors across all 20 cases after fixes applied to graph/tools.py

## Neo4j access

- Browser: http://localhost:7474 (login: neo4j / sherlock_dev)
- Bolt: bolt://localhost:7687
- Query all suspects across all cases:
  ```cypher
  MATCH (p:Person)-[:SUSPECT_IN]->(c:Case)
  RETURN p.name, p.nationality, c.case_id ORDER BY c.case_id
  ```

## Design decisions (confirmed before implementation)

- **Neo4j Community** — free, single DB, namespaced by case_id node property
- **LLM-driven ER** — Nemotron Nano 9B via integrate.api.nvidia.com; no new NIM needed
- **ER at ingest time** — graph populated when evidence submitted (not on-demand)
  - Rationale: investigator queries graph immediately; no cold-start wait
  - Same pattern as RAG-BP (ingest → index, then query)
- **nx-cugraph CPU** now — identical NetworkX API; swap to GPU cuGraph at Phase 9
- **VSS Neo4j alignment** deferred to Phase 7 — VSS CA-RAG uses ES; schema matching done during MCP wiring

## Known limitations

- `case_report.txt` sometimes returns 0 entities — LLM returns JSON with empty arrays on very
  structured/header-heavy content. Acceptable: other files (witness_statement, lab_report,
  chat) cover the key entities.
- `audio_analysis.txt` is sparse until Phase 4 audio is processed for a case.
- Graph grows richer as more modalities are added (images → captions → entities in Phase 7/8).
