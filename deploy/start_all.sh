#!/usr/bin/env bash
# Sherlock — start all services in dependency order
# Run from repo root: bash deploy/start_all.sh
#
# Service start order:
#   1. Neo4j              (graph store — no deps)
#   2. RAG Blueprint      (Elasticsearch + SeaweedFS + RAG servers)
#   3. AI-Q               (agent — needs RAG network to be up)
#   4. Sherlock MCP       (graph tools server — needs Neo4j)
#   5. Case Workbench UI  (FastAPI + Svelte — needs AI-Q + Neo4j)
#
# GPU-only services (start manually when GPU instance is ready):
#   VSS — see deploy/PHASE5_VSS.md
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# ── Helpers ──────────────────────────────────────────────────────────────────

wait_http() {
    local name="$1" url="$2" max="${3:-60}"
    echo -n "  Waiting for $name..."
    for i in $(seq 1 "$max"); do
        if curl -sf "$url" >/dev/null 2>&1; then echo " ready (${i}s)"; return 0; fi
        sleep 2
    done
    echo " TIMEOUT after ${max}s"
    return 1
}

wait_port() {
    local name="$1" host="$2" port="$3" max="${4:-60}"
    echo -n "  Waiting for $name..."
    for i in $(seq 1 "$max"); do
        if python3 -c "import socket; s=socket.socket(); s.settimeout(1); s.connect(('$host',$port)); s.close()" 2>/dev/null; then
            echo " ready (${i}s)"; return 0
        fi
        sleep 2
    done
    echo " TIMEOUT after ${max}s"
    return 1
}

# ── Preflight ─────────────────────────────────────────────────────────────────

echo "=== Sherlock — starting all services ==="
echo ""

if [ ! -f ".env" ]; then
    echo "ERROR: .env not found. Copy .env.example → .env and fill API keys."
    exit 1
fi

AIQ_COMPOSE=""
for candidate in \
    "$REPO_ROOT/external/aiq/deploy/compose/docker-compose.yaml" \
    "$HOME/external/aiq/deploy/compose/docker-compose.yaml"; do
    if [ -f "$candidate" ]; then AIQ_COMPOSE="$candidate"; break; fi
done
if [ -z "$AIQ_COMPOSE" ]; then
    echo "ERROR: AI-Q compose file not found. Run Phase 1 first to clone the blueprint."
    echo "  Expected: external/aiq/deploy/compose/docker-compose.yaml"
    exit 1
fi

RAG_ENV=""
for candidate in \
    "$REPO_ROOT/external/rag/deploy/compose/nvdev.env" \
    "$HOME/external/rag/deploy/compose/nvdev.env"; do
    if [ -f "$candidate" ]; then RAG_ENV="$candidate"; break; fi
done

# ── 1. Neo4j ──────────────────────────────────────────────────────────────────

echo "[1/5] Neo4j"
docker compose -p amms -f deploy/compose.neo4j.yaml up -d
wait_http "Neo4j HTTP" "http://localhost:7474" 60
echo "  Neo4j browser: http://localhost:7474  (neo4j / sherlock_dev)"

# ── 2. RAG Blueprint ─────────────────────────────────────────────────────────

echo ""
echo "[2/5] RAG Blueprint"
if [ -n "$RAG_ENV" ]; then
    source "$RAG_ENV"
fi
RAG_COMPOSE="$(dirname "$(dirname "$RAG_ENV")")/docker-compose.yaml" 2>/dev/null || \
RAG_COMPOSE="$(ls "$REPO_ROOT"/external/rag/deploy/compose/docker-compose.yaml 2>/dev/null | head -1)"

if [ -f "$RAG_COMPOSE" ]; then
    docker compose -p amms -f "$RAG_COMPOSE" up -d
    wait_http "RAG ingestor" "http://localhost:8082/health" 120
    wait_http "RAG server"   "http://localhost:8081/health" 120
    echo "  RAG ingestor: http://localhost:8082"
    echo "  RAG server:   http://localhost:8081"
else
    echo "  SKIP: RAG compose not found (run Phase 2 first)"
fi

# ── 3. AI-Q (Sherlock config + prompt volume mount) ───────────────────────────

echo ""
echo "[3/5] AI-Q (Sherlock config)"
docker compose -p amms \
    --env-file "$REPO_ROOT/external/aiq/deploy/compose/.env" \
    -f "$AIQ_COMPOSE" \
    -f "$REPO_ROOT/deploy/compose.amms.override.yaml" \
    up -d aiq-agent postgres 2>/dev/null || \
docker compose -p amms \
    -f "$AIQ_COMPOSE" \
    -f "$REPO_ROOT/deploy/compose.amms.override.yaml" \
    up -d aiq-agent postgres

wait_http "AI-Q" "http://localhost:8100/health" 90
echo "  AI-Q: http://localhost:8100"

# ── 4. Sherlock MCP ───────────────────────────────────────────────────────────

echo ""
echo "[4/5] Sherlock MCP (graph tools)"
docker compose -p amms -f deploy/compose.sherlock_mcp.yaml up -d
wait_port "Sherlock MCP" "localhost" 9901 90
echo "  Sherlock MCP: http://localhost:9901/mcp"

# ── 5. Case Workbench UI ──────────────────────────────────────────────────────

echo ""
echo "[5/5] Case Workbench UI"
# Build image if not already built
if ! docker image inspect amms-workbench:latest >/dev/null 2>&1; then
    echo "  Building workbench image (first run — ~3 min)..."
    docker compose -p amms -f deploy/compose.workbench.yaml build workbench
fi
docker compose -p amms -f deploy/compose.workbench.yaml up -d
wait_http "Workbench" "http://localhost:8200/api/health" 90
echo "  Workbench: http://localhost:8200"

# ── Summary ───────────────────────────────────────────────────────────────────

echo ""
echo "=== All services started ==="
echo ""
echo "  Investigator workbench:  http://localhost:8200"
echo "  AI-Q API:                http://localhost:8100"
echo "  Neo4j browser:           http://localhost:7474   (neo4j / sherlock_dev)"
echo "  RAG ingestor:            http://localhost:8082"
echo "  Sherlock MCP:            http://localhost:9901/mcp"
echo ""
echo "  GPU services (start when GPU instance ready):"
echo "    VSS: see deploy/PHASE5_VSS.md"
echo "    Nemotron Content Safety: see Phase 9"
echo ""
echo "  Log tails:"
echo "    docker logs -f amms-aiq-agent"
echo "    docker logs -f amms-sherlock-mcp"
echo "    docker logs -f amms-workbench"
