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

# ── 2. Install Python dependencies ────────────────────────────────────────────
python3 -m pip install --quiet --user neo4j openai networkx

# ── 3. Run entity extraction for all cases ────────────────────────────────────
echo ""
echo "Running entity extraction for all cases..."
cd "$REPO_ROOT"
python3 graph/ingest_entities.py

# ── 4. Smoke test ─────────────────────────────────────────────────────────────
echo ""
echo "Smoke test — querying first case..."
python3 -c "
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
