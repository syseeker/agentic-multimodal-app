#!/usr/bin/env bash
# Start nv-ingest for document ingestion (Phase 3/4 or workbench uploads).
# VSS owns Elasticsearch (:9200) and Redis (:6379) — this script starts ONLY
# nv-ingest (not the bundled redis that would conflict) and ensures ingestor-server
# points at VSS's ES, not the bundled one.
#
# Usage:
#   bash deploy/ingest_start.sh          # start
#   bash deploy/ingest_stop.sh           # stop when done (frees ~10 GB RAM)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RAG_INGESTOR_COMPOSE="$REPO_ROOT/external/rag/deploy/compose/docker-compose-ingestor-server.yaml"
NV_CTR="compose-nv-ingest-ms-runtime-1"

if [ ! -f "$RAG_INGESTOR_COMPOSE" ]; then
    echo "ERROR: RAG Blueprint not found. Run Phase 2 first."
    exit 1
fi

ETH0_IP="$(ip route get 1.1.1.1 2>/dev/null | awk '/src/{for(i=1;i<=NF;i++) if($i=="src") print $(i+1); exit}')"

# Load credentials from root .env (required by docker compose interpolation)
ENV_FILE="$REPO_ROOT/.env"
REGISTRY_KEY="$(grep -m1 '^NGC_API_KEY=' "$ENV_FILE" | cut -d= -f2- | sed 's/[[:space:]]*#.*//' | tr -d '[:space:]')"
INFERENCE_KEY="$(grep -m1 '^NVIDIA_API_KEY=' "$ENV_FILE" | cut -d= -f2- | sed 's/[[:space:]]*#.*//' | tr -d '[:space:]')"
[ -n "$INFERENCE_KEY" ] || { echo "ERROR: NVIDIA_API_KEY not set in $ENV_FILE"; exit 1; }
export NVIDIA_API_KEY="$INFERENCE_KEY"
# nv-ingest's compose entry sets NVIDIA_BUILD_API_KEY=${NGC_API_KEY} (docker-compose-ingestor-server.yaml),
# and that is the key it uses for hosted embeddings at integrate.api.nvidia.com. NGC_API_KEY may be a
# registry-only key (see phase2_rag.sh) which 403s there, so export the INFERENCE key BEFORE the
# nv-ingest `up -d` below — env is baked in at container-create time, not at start time.
# REGISTRY_KEY stays available for image pulls, which use ~/.docker/config.json, not this variable.
export NGC_API_KEY="$INFERENCE_KEY"

echo "=== Starting nv-ingest (VSS ES: ${ETH0_IP}:9200, Redis: ${ETH0_IP}:6379) ==="

# ── 1. Start nv-ingest only (--no-deps skips bundled redis which conflicts with VSS) ──
cd "$REPO_ROOT/external/rag"
docker compose -f deploy/compose/docker-compose-ingestor-server.yaml \
    up -d --no-deps nv-ingest-ms-runtime
cd "$REPO_ROOT"

# ── 2. Ensure ingestor-server points at VSS's Elasticsearch (not bundled) ──────────
# Force-recreate with host IP and full API key env (nvdev.env sets embedding API keys;
# without it the ingestor uses local NIM hostnames that don't exist in our stack).
echo "Reconnecting ingestor-server → VSS ES at ${ETH0_IP}:9200 ..."
cd "$REPO_ROOT/external/rag"
# Source nvdev.env to get embedding/LLM API key env vars (same as start_all.sh)
source deploy/compose/nvdev.env 2>/dev/null || true
export NVIDIA_API_KEY="$INFERENCE_KEY"   # restore inference key after nvdev.env clobbers it
export NGC_API_KEY="$INFERENCE_KEY"
export APP_EMBEDDINGS_APIKEY="$INFERENCE_KEY"
export APP_LLM_APIKEY="$INFERENCE_KEY"
export APP_RANKING_APIKEY="$INFERENCE_KEY"
export SUMMARY_LLM_APIKEY="$INFERENCE_KEY"
export AGENTIC_PLANNER_LLM_APIKEY="$INFERENCE_KEY"
export AGENTIC_TASK_LLM_APIKEY="$INFERENCE_KEY"
export AGENTIC_SEED_GEN_LLM_APIKEY="$INFERENCE_KEY"
export AGENTIC_SYNTHESIS_LLM_APIKEY="$INFERENCE_KEY"
export ENABLE_AGENTIC_RAG=true
ENABLE_REDIS_BACKEND=True \
APP_VECTORSTORE_URL="http://${ETH0_IP}:9200" \
REDIS_HOST="${ETH0_IP}" \
docker compose -f deploy/compose/docker-compose-ingestor-server.yaml \
    up -d --force-recreate --no-deps ingestor-server 2>&1 | tail -3
cd "$REPO_ROOT"

# ── 3. Wait for nv-ingest container to be running ────────────────────────────────────
echo -n "Waiting for nv-ingest..."
for i in $(seq 1 30); do
    if docker ps -q --filter "name=^/${NV_CTR}$" | grep -q .; then echo " up ✓"; break; fi
    sleep 2; echo -n "."
done
if ! docker ps -q --filter "name=^/${NV_CTR}$" | grep -q .; then
    echo " TIMEOUT — check: docker logs ${NV_CTR}"
    exit 1
fi

# ── 4. Patch nv-ingest /etc/hosts: 'redis' → VSS Redis ──────────────────────────────
# nv-ingest has MESSAGE_CLIENT_HOST=redis hardcoded (env override is silently ignored).
# Patch /etc/hosts inside the container to resolve 'redis' to VSS's Redis IP.
BRIDGE_GW="$(docker network inspect nvidia-rag --format '{{range .IPAM.Config}}{{.Gateway}}{{end}}' 2>/dev/null || true)"
_redis_ok() {
    docker exec "$NV_CTR" python3 -c \
        "import socket; s=socket.socket(); s.settimeout(3); s.connect(('redis',6379)); s.close()" \
        2>/dev/null
}
if ! _redis_ok; then
    REDIS_TARGET=""
    for _ip in "$BRIDGE_GW" "$ETH0_IP"; do
        [ -z "$_ip" ] && continue
        if docker exec "$NV_CTR" python3 -c \
            "import socket; s=socket.socket(); s.settimeout(3); s.connect(('${_ip}',6379)); s.close()" \
            2>/dev/null; then
            REDIS_TARGET="$_ip"; break
        fi
    done
    if [ -n "$REDIS_TARGET" ]; then
        docker exec "$NV_CTR" \
            sh -c "grep -v '[[:space:]]redis\$' /etc/hosts > /tmp/hosts.new && \
                   cat /tmp/hosts.new > /etc/hosts && \
                   echo '${REDIS_TARGET} redis' >> /etc/hosts"
        echo "  ✓ nv-ingest: 'redis' → ${REDIS_TARGET}:6379"
    else
        echo "  WARNING: could not reach VSS Redis — ingest jobs may not process"
    fi
else
    echo "  ✓ nv-ingest Redis already reachable"
fi

# ── 5. Verify ingestor health ────────────────────────────────────────────────────────
echo -n "Waiting for ingestor-server health..."
for i in $(seq 1 20); do
    if curl -sf http://localhost:8082/health >/dev/null 2>&1; then echo " ✓"; break; fi
    sleep 3; echo -n "."
done

echo ""
echo "=== nv-ingest ready ==="
echo "  Run ingestion: CASE_LIMIT=5 bash deploy/phase3_data_sim.sh"
echo "  Stop when done: bash deploy/ingest_stop.sh   (~10 GB RAM freed)"
