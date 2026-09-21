#!/usr/bin/env bash
# Phase 6 — Neo4j + entity extraction ingest
# See PHASE6_GRAPH.md for full context.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# ── 1. Start Neo4j ────────────────────────────────────────────────────────────
echo "Starting Neo4j..."
docker compose -p amms -f "$REPO_ROOT/deploy/compose.neo4j.yaml" up -d

echo "Waiting for Neo4j to be healthy..."
until docker inspect amms-neo4j --format '{{.State.Health.Status}}' 2>/dev/null | grep -q healthy; do
    sleep 5
done
echo "✅ Neo4j healthy — browser at http://localhost:7474"

# ── 2. Graph deps via uv ──────────────────────────────────────────────────────
# System Python 3.12 is externally-managed (PEP 668) and lacks pip/venv/ensurepip
# on this box, so use uv to provide neo4j/openai/networkx on demand (no sudo).
export PATH="$HOME/.local/bin:$PATH"
command -v uv >/dev/null || { echo "ERROR: uv not found (needed for graph deps)"; exit 1; }
runpy() { uv run --with neo4j --with openai --with networkx python "$@"; }
echo "✓ graph deps resolved via uv"

# ── 3. Run entity extraction ──────────────────────────────────────────────────
# GRAPH_CASE_LIMIT: max number of cases to process (default: all).
# Set to a small number for quick testing: GRAPH_CASE_LIMIT=5 bash deploy/phase6_graph.sh
GRAPH_CASE_LIMIT="${GRAPH_CASE_LIMIT:-0}"

cd "$REPO_ROOT"

if [ "${GRAPH_CASE_LIMIT}" -gt 0 ]; then
    CASE_LIST=$(ls -d data/cases/SC-*/ 2>/dev/null | head -n "$GRAPH_CASE_LIMIT" | xargs -I{} basename {})
    CASE_COUNT=$(echo "$CASE_LIST" | wc -l)
    echo ""
    echo "Running entity extraction for $CASE_COUNT case(s) (GRAPH_CASE_LIMIT=${GRAPH_CASE_LIMIT})..."
    for case_id in $CASE_LIST; do
        echo "  → $case_id"
        runpy graph/ingest_entities.py --case "$case_id"
    done
else
    echo ""
    echo "Running entity extraction for all cases..."
    runpy graph/ingest_entities.py
fi

# ── 4. Smoke test ─────────────────────────────────────────────────────────────
echo ""
echo "Smoke test — querying first case..."
runpy -c "
import sys, os
sys.path.insert(0, '.')
for line in open('.env').readlines():
    line=line.strip()
    if line and not line.startswith('#') and '=' in line:
        k,_,v=line.partition('='); v=v.split('#')[0].strip().strip('\"').strip(\"'\")
        os.environ.setdefault(k.strip(), v)
from graph.tools import graph_query, graph_analyze
import json
cases = sorted([d.name for d in __import__('pathlib').Path('data/cases').iterdir() if d.is_dir()])
cid = cases[0]
q = graph_query(cid, 'suspects')
a = graph_analyze(cid, 'centrality')
print(f'Case {cid}:')
print(f'  Suspects: {[s[\"name\"] for s in q.get(\"suspects\", [])]}')
print(f'  Top entity: {a[\"key_entities\"][0][\"name\"] if a.get(\"key_entities\") else \"none\"}')
print('✅ Graph tools verified')
"
