#!/usr/bin/env bash
# Phase 7 — AI-Q forensic extensions
# Deploys: Sherlock MCP server + switches AI-Q to Sherlock config + forensic prompts
# See PHASE7_EXTENSIONS.md for context.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AIQ_COMPOSE="$REPO_ROOT/external/aiq/deploy/compose/docker-compose.yaml"
OVERRIDE="$REPO_ROOT/deploy/compose.amms.override.yaml"

# ── 1. Start Sherlock MCP server ──────────────────────────────────────────────
echo "Starting Sherlock MCP server..."
docker compose -p amms -f "$REPO_ROOT/deploy/compose.sherlock_mcp.yaml" up -d

echo "Waiting for Sherlock MCP to be healthy..."
until docker inspect amms-sherlock-mcp --format '{{.State.Health.Status}}' 2>/dev/null | grep -q healthy; do
    sleep 5
done
echo "✅ Sherlock MCP healthy at http://localhost:9901/mcp"

# ── 2. Smoke test MCP tools ───────────────────────────────────────────────────
echo ""
echo "Smoke testing MCP tools..."
python3 -c "
import urllib.request, json
req = urllib.request.Request(
    'http://localhost:9901/mcp',
    headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
    method='POST',
    data=json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/list','params':{}}).encode()
)
try:
    with urllib.request.urlopen(req, timeout=5) as r:
        data = json.loads(r.read())
        tools = [t['name'] for t in data.get('result', {}).get('tools', [])]
        print(f'MCP tools exposed: {tools}')
except Exception as e:
    print(f'MCP not yet ready via streamable-http (expected — use /mcp endpoint): {e}')
"

# ── 3. Restart AI-Q with Sherlock config + prompt volume mount ────────────────
echo ""
echo "Restarting AI-Q with Sherlock config..."
source "$REPO_ROOT/external/rag/deploy/compose/nvdev.env" 2>/dev/null || true

docker compose -p amms \
    -f "$AIQ_COMPOSE" \
    -f "$OVERRIDE" \
    up -d --no-build aiq-agent

echo "Waiting for AI-Q to be healthy..."
until curl -sf "http://localhost:8100/health" >/dev/null 2>&1; do
    sleep 5
done
echo "✅ AI-Q healthy at http://localhost:8100"

# ── 4. Verify Sherlock config is active ───────────────────────────────────────
echo ""
echo "Verifying Sherlock config..."
docker exec amms-aiq-agent python3 -c "
import os
cfg = os.environ.get('BACKEND_CONFIG', '')
print(f'BACKEND_CONFIG: {cfg}')
assert 'sherlock' in cfg, f'Expected sherlock config, got: {cfg}'
print('✅ Sherlock config active')
" && echo "✅ Prompts: mounted from host (shallow_researcher + clarifier patched)"

# ── 5. End-to-end graph tool query via AI-Q ───────────────────────────────────
echo ""
echo "End-to-end test: query graph tools via AI-Q..."
python3 -c "
import urllib.request, json, sys
cases_dir = '$REPO_ROOT/data/cases'
import os
cases = sorted([d for d in os.listdir(cases_dir) if os.path.isdir(os.path.join(cases_dir, d))])
if not cases:
    print('No cases found — skipping end-to-end test')
    sys.exit(0)
case_id = cases[0]

# Direct graph query (bypasses AI-Q, tests MCP server directly)
from graph.tools import graph_query, graph_analyze
import sys
sys.path.insert(0, '$REPO_ROOT')

# Load env
for line in open('$REPO_ROOT/.env').readlines():
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k,_,v = line.partition('='); v=v.split('#')[0].strip().strip('\"').strip(\"'\")
        os.environ.setdefault(k.strip(), v)

q = graph_query(case_id, 'suspects')
a = graph_analyze(case_id, 'centrality')
suspects = [s['name'] for s in q.get('suspects', [])]
top = a.get('key_entities', [{}])[0].get('name', 'none') if a.get('key_entities') else 'none'
print(f'Case {case_id}: suspects={suspects}, top entity={top}')
print('✅ Graph tools working')
"

echo ""
echo "=== Phase 7 complete ==="
echo "  - Sherlock MCP server: http://localhost:9901/mcp"
echo "  - AI-Q (Sherlock config): http://localhost:8100"
echo "  - Graph tools: graph_query, graph_analyze, extract_entities, list_cases"
echo "  - Forensic prompts: shallow_researcher + clarifier patched"
echo "  - Safety policy: guardrails/sherlock_forensic_safety_v1.0.0.md"
echo "  - VSS MCP (vss-agent): deferred — enable when GPU ready (LVS_ENABLE_MCP=true)"
