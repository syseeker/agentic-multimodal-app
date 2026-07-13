# Swapping the Graph DB: Neo4j (default) → FalkorDB (alternative)

**Status:** documented migration path (not applied — Neo4j remains the default).
**Audience:** a developer who wants to run Sherlock's case graph on FalkorDB instead of Neo4j.
**Scope:** this is the *graph* store only (entity/relationship graph per `case_id`). The
vector store (Elasticsearch) is a separate swap — see
[SWAP_VECTOR_DB_ELASTICSEARCH_TO_CHROMADB.md](SWAP_VECTOR_DB_ELASTICSEARCH_TO_CHROMADB.md).

---

## TL;DR

| | |
|---|---|
| **Effort** | Medium — a **driver swap** (protocol change), not a config toggle. |
| **Files that connect to the graph** | 3: [graph/tools.py](../graph/tools.py), [mcp/sherlock_mcp.py](../mcp/sherlock_mcp.py), [ui/server.py](../ui/server.py) |
| **Biggest change** | Neo4j speaks **Bolt** (`neo4j` Python driver); FalkorDB speaks the **Redis protocol** (`falkordb` Python client). `GraphDatabase.driver()/session()/run()` must be rewritten. |
| **Free win** | The code uses **no** APOC/GDS procedures — all graph algorithms run in Python (NetworkX / nx-cuGraph). So there are no in-database procedures to port. |
| **Query language** | Both speak Cypher (FalkorDB = OpenCypher). Most query bodies port unchanged; a few DDL/function forms need edits (see §4). |
| **Result-object shape** | The neo4j driver's `Record`/`Node` objects differ from FalkorDB's `result_set`. The result-handling code needs a thin shim (see §3). |

> **Why FalkorDB?** It's a lightweight, Redis-based graph DB (single small container, low memory) with OpenCypher support — attractive when you don't need Neo4j's Enterprise features and want a smaller footprint (e.g. on a memory-constrained box like the DGX Spark). Sherlock never uses Neo4j's heavyweight features, so the fit is good.

---

## 1. What connects to the graph today

All three consumers use the **Bolt** driver (`from neo4j import GraphDatabase`). Nothing uses
Neo4j's HTTP API (`:7474`) except the container healthcheck.

| Component | File | Connection code | Purpose |
|---|---|---|---|
| Graph tools library | [graph/tools.py](../graph/tools.py) | `tools.py:18` import, `:34-35` `_neo4j_driver()` | write/read/analyze the case graph |
| Entity ingest CLI | [graph/ingest_entities.py](../graph/ingest_entities.py) | imports `graph.tools` | batch entity extraction → graph |
| Schema/constraints | [graph/schema.py](../graph/schema.py) | Cypher DDL strings, run by `init_schema()` | constraints + indexes |
| MCP server | [mcp/sherlock_mcp.py](../mcp/sherlock_mcp.py) | `:36` import, `:142-146` direct driver in `list_cases` | exposes graph tools to AI-Q |
| Workbench backend | [ui/server.py](../ui/server.py) | `:20` import, `:43` singleton `get_neo4j()` | graph viz + health probe |

Connection values come from **env vars with in-code defaults** (there are no `NEO4J_*` keys in
`.env`/`.env.example`):

```python
NEO4J_URI  = os.getenv("NEO4J_URI",  "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASS", "sherlock_dev")   # note: NEO4J_PASS, not NEO4J_PASSWORD
```

Compose injects the container hostname:
- [deploy/compose.sherlock_mcp.yaml](../deploy/compose.sherlock_mcp.yaml)`:13-15` → `NEO4J_URI: bolt://amms-neo4j:7687`
- [deploy/compose.workbench.yaml](../deploy/compose.workbench.yaml)`:18-20` → `NEO4J_URI: bolt://amms-neo4j:7687`

The AI-Q agent never talks to the graph directly — only through the MCP server.

---

## 2. Replace the container

Swap the Neo4j service ([deploy/compose.neo4j.yaml](../deploy/compose.neo4j.yaml)) for FalkorDB.
Drop the APOC/GDS plugin env — **the code never calls them** (see §4).

```yaml
# deploy/compose.falkordb.yaml  (replaces compose.neo4j.yaml)
services:
  falkordb:
    image: falkordb/falkordb:latest        # pin a tag for reproducibility, e.g. v4.x
    container_name: amms-falkordb
    ports:
      - "6379:6379"                          # Redis protocol (Cypher over RESP)
      - "3000:3000"                          # FalkorDB Browser UI (optional; was 7474 in Neo4j)
    environment:
      # FalkorDB auth is Redis-style. To require a password:
      #   REDIS_ARGS: "--requirepass sherlock_dev"
      FALKORDB_ARGS: ""
    volumes:
      - amms-falkordb-data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 15s
      timeout: 10s
      retries: 10
      start_period: 20s
    restart: unless-stopped

volumes:
  amms-falkordb-data:
```

Then update the two consumer compose files to point at it. FalkorDB has no `bolt://` scheme, so
introduce host/port vars instead of `NEO4J_URI`:

```yaml
# compose.sherlock_mcp.yaml and compose.workbench.yaml
environment:
  FALKORDB_HOST: amms-falkordb
  FALKORDB_PORT: "6379"
  FALKORDB_GRAPH: sherlock          # one FalkorDB "graph key" holds all cases (case_id property namespaces them, as today)
# and add falkordb to the runtime pip install in compose.sherlock_mcp.yaml:
#   pip install --quiet fastmcp falkordb openai networkx     # was: neo4j
```

Point `start_all.sh` / the phase scripts at `compose.falkordb.yaml` instead of
`compose.neo4j.yaml`, and drop the `wget http://localhost:7474` waits (use `redis-cli ping`).

---

## 3. Rewrite the driver calls (the real work)

FalkorDB is **not** Bolt-compatible, so the `neo4j` driver API must be replaced with the
`falkordb` client in **three** files. The pattern maps cleanly:

| Neo4j (`neo4j` driver) | FalkorDB (`falkordb` client) |
|---|---|
| `from neo4j import GraphDatabase` | `from falkordb import FalkorDB` |
| `GraphDatabase.driver(uri, auth=(u,p))` | `FalkorDB(host=H, port=P, password=p)` |
| `driver.session()` | `db.select_graph("sherlock")` |
| `session.run(cypher, **params)` | `graph.query(cypher, params)` |
| iterate `Record`; `row["n"]`, `dict(row["n"])`, `row["labels"]` | iterate `result.result_set` (list of rows); nodes are `falkordb.Node` with `.labels`, `.properties` |

**Recommended approach — a thin adapter, not a scatter-rewrite.** Add one helper module
(`graph/graphdb.py`) that exposes a `run(cypher, **params) -> list[dict]` returning plain dicts,
and have `graph/tools.py`, `mcp/sherlock_mcp.py`, and `ui/server.py` call *that* instead of the
raw driver. This isolates the protocol difference in a single place and keeps the query strings
untouched.

The result-shape mismatch is the fiddly part. Today's code relies on the neo4j `Record`/`Node` API:
- [ui/server.py](../ui/server.py)`:108` `dict(row["n"])`, `:109` `row["labels"]`
- [graph/tools.py](../graph/tools.py)`:216` `properties(n) AS props`, whole-node returns

FalkorDB returns `Node` objects with `.properties` (a dict) and `.labels` (a list) instead — the
adapter should normalize a returned node to `{**node.properties, "_labels": node.labels}` so the
call sites keep working with minimal edits.

---

## 4. Cypher portability — what ports, what needs editing

**Good news:** the app uses **no** APOC procedures, **no** GDS/cuGraph *in-database*, **no**
full-text indexes, and **no** vector indexes. Graph algorithms (centrality, communities,
shortest-path) run in Python via NetworkX / nx-cuGraph ([graph/tools.py](../graph/tools.py)`:240-286`),
loaded from the DB with plain `MATCH`. So the DB is used only as a Cypher property graph — exactly
FalkorDB's sweet spot.

### Ports unchanged (standard Cypher / OpenCypher)
`MATCH`, `OPTIONAL MATCH`, `MERGE`, `SET`, `WHERE`, `RETURN`, `LIMIT`, `count(DISTINCT …)`,
`labels()`, `type()`, dynamic labels/rel-types via f-string (`MERGE (n:{label} …)`), and the read
queries in `graph/tools.py`, `mcp/sherlock_mcp.py:149-157`, `ui/server.py:103-134`.

### Needs editing / verification
| Item | Where | Action for FalkorDB |
|---|---|---|
| `CREATE CONSTRAINT … REQUIRE … IS UNIQUE` | [graph/schema.py](../graph/schema.py)`:22` | FalkorDB uses `GRAPH.CONSTRAINT CREATE` (a separate command / client call), not Neo4j 5.x `REQUIRE … IS UNIQUE` grammar. Rewrite in `init_schema()`. |
| Composite `CREATE INDEX … ON (n.a, n.b)` | `graph/schema.py:23-26` | FalkorDB index DDL is single-property `CREATE INDEX FOR (n:L) ON (n.a)`; split composites and drop the `name IF NOT EXISTS` form. |
| `timestamp()` | [graph/tools.py](../graph/tools.py)`:118` | Verify FalkorDB's `timestamp()`; if absent, pass an epoch-ms value in as a param. |
| `SET n += $props` (map-merge) | `graph/tools.py:133,152` | Verify `+=` map-merge support; otherwise expand to explicit `SET n.k = $v` per key. |
| Whole-node / `properties(n)` returns | `graph/tools.py:216,297`, `ui/server.py:108` | Handled by the §3 adapter (normalize Node → dict). |

---

## 5. Data migration

There's no automatic Neo4j→FalkorDB dump import. Since Sherlock rebuilds the graph from source
evidence, the simplest path is to **re-ingest**: bring up FalkorDB, run `init_schema()`, then
`python3 graph/ingest_entities.py` (re-extracts entities from `data/cases/*` into the new graph).
No historical graph state is lost that can't be regenerated from the case files.

---

## 6. Verification checklist

1. `docker compose -f deploy/compose.falkordb.yaml up -d` → `redis-cli -h localhost ping` returns `PONG`.
2. `init_schema()` runs without error (constraints/indexes created via the FalkorDB DDL).
3. `python3 graph/ingest_entities.py --case <id>` populates the graph (check `GRAPH.QUERY sherlock "MATCH (n) RETURN count(n)"`).
4. Workbench `GET /api/cases/<id>/graph` returns nodes/edges (proves `ui/server.py` reads work).
5. Workbench `GET /api/health` shows the graph reachable (adapt the `RETURN 1` probe at `ui/server.py:525`).
6. MCP `list_cases` + `graph_query_tool` return data (proves the MCP path + AI-Q "Case Graph" data source).
7. Ask Sherlock a graph question in the workbench and confirm a cited graph answer.

---

## 7. Effort summary

- **Swap driver** (`neo4j` → `falkordb`) behind a `graph/graphdb.py` adapter — 3 call sites.
- **Rewrite DDL** in `graph/schema.py` (5 statements) for FalkorDB's constraint/index API.
- **Replace the container** (`compose.neo4j.yaml` → `compose.falkordb.yaml`); drop unused APOC/GDS.
- **Re-plumb env** (`NEO4J_URI` bolt → `FALKORDB_HOST`/`PORT`) in 2 compose files + code defaults.
- **Re-ingest** the graph; run the §6 checklist.

No architectural change, no data model change, no loss of graph-algorithm capability (those live in
Python). The migration is mechanical once the driver adapter is in place.
