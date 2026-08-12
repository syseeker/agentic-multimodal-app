#!/usr/bin/env bash
# Sherlock — start all services in dependency order
# Run from repo root: bash deploy/start_all.sh
#
# First-time PHASE deployment order (run once per new instance):
#   1 → 2 → 5 → 3 → 4 → 6 → 7 → 8
#   Phase 5 (VSS) MUST come before Phase 3/4 — VSS takes ownership of
#   Elasticsearch and Redis. Running 3/4 first forces re-ingestion after 5.
#
# Daily service start order (this script):
#   0. VSS                (video analysis stack — owns Elasticsearch + Redis; must be first)
#   1. Neo4j              (graph store — no deps)
#   2. RAG Blueprint      (connects to VSS-owned Elasticsearch)
#   3. Sherlock MCP       (graph + audio tools — needs Neo4j; must be up before AI-Q)
#   3b. VSS Sherlock MCP  (video tools — wraps vss-agent; must be up before AI-Q)
#   4. AI-Q               (agent — needs RAG network + both MCPs)
#   5. Case Workbench UI  (FastAPI + Svelte — needs AI-Q + Neo4j)
#
# VSS (step 0) requires Phase 5 to have been run first (external/vss-3.2.0/deploy/docker/
# resolved.yml must exist). If not deployed, step 0 is skipped gracefully.
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

# ── 0. VSS (owns shared Elasticsearch + Redis; must start before RAG) ─────────

echo "[0/6] VSS (video analysis stack — owns Elasticsearch + Redis)"
VSS_DIR="$REPO_ROOT/external/vss-3.2.0/deploy/docker"
VSS_RESOLVED="$VSS_DIR/resolved.yml"
VSS_ENV="$VSS_DIR/developer-profiles/dev-profile-lvs/generated.env"

if curl -sf --max-time 3 http://localhost:8000/health 2>/dev/null | grep -q isAlive; then
    # ALREADY UP -- do not touch it. `up -d` against a live stack recreates containers,
    # and recreating vss-rtvi-vlm DISCARDS the writable-layer patches from
    # patch_vss_rtvi_vlm.sh (model-name normalization + VIOS UUID URL fallback) that the
    # video pipeline depends on. Re-running Phase 5 is the deliberate way to redeploy VSS.
    echo "  VSS already running — skipping bring-up (protects rtvi-vlm container patches)"
    echo "  VSS agent: http://localhost:8000"
    echo "  VSS UI:    http://localhost:7777"
elif [ -f "$VSS_RESOLVED" ] && [ -f "$VSS_ENV" ]; then
    # NON-FATAL: VSS is the one stage that may legitimately fail (a dead dependency such
    # as `kafka exited (143)` aborts the whole compose run). Under `set -e` an unguarded
    # failure here kills start_all before Neo4j/RAG/MCP/AI-Q/workbench ever start, taking
    # down the entire stack for a video-only problem. Warn and continue instead.
    if docker compose --env-file "$VSS_ENV" -f "$VSS_RESOLVED" -p mdx up -d; then
        echo "  NOTE: VSS containers were (re)created — re-apply the rtvi-vlm patches:"
        echo "        bash deploy/patch_vss_rtvi_vlm.sh"
        echo -n "  Waiting for vss-agent..."
        for i in $(seq 1 90); do
            if curl -sf --max-time 3 http://localhost:8000/health 2>/dev/null | grep -q isAlive; then
                echo " ready (${i}×5s)"; break
            fi
            sleep 5; echo -n "."
        done
        echo "  VSS agent: http://localhost:8000"
        echo "  VSS UI:    http://localhost:7777"
    else
        echo "  WARNING: VSS bring-up FAILED — continuing without it."
        echo "           Text/audio RAG, graph and workbench still work; video analysis does not."
        echo "           Check:  docker ps -a --filter name=kafka   (a dead dep fails the whole run)"
        echo "           Then:   bash deploy/phase5_vss.sh   (and patch_vss_rtvi_vlm.sh after)"
    fi
else
    echo "  SKIP: VSS not deployed (run Phase 5 first)"
    echo "        Expected: $VSS_RESOLVED"
fi
echo ""

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

echo "[1/6] Neo4j"
docker compose -p amms -f deploy/compose.neo4j.yaml up -d
wait_http "Neo4j HTTP" "http://localhost:7474" 60
echo "  Neo4j browser: http://localhost:7474  (neo4j / sherlock_dev)"

# ── 2. RAG Blueprint ─────────────────────────────────────────────────────────

echo ""
echo "[2/6] RAG Blueprint"
RAG_COMPOSE_DIR="$REPO_ROOT/external/rag/deploy/compose"
if [ -d "$RAG_COMPOSE_DIR" ]; then
    # nvdev.env line 2: export NVIDIA_API_KEY=${NGC_API_KEY}
    # Must export NGC_API_KEY before sourcing nvdev.env (set -u would abort otherwise).
    export NGC_API_KEY="$(grep '^NGC_API_KEY=' "$REPO_ROOT/.env" | cut -d= -f2- | tr -d '[:space:]')"
    INFERENCE_KEY="$(grep '^NVIDIA_API_KEY=' "$REPO_ROOT/.env" | cut -d= -f2- | sed 's/[[:space:]]*#.*//' | tr -d '[:space:]')"
    cd "$REPO_ROOT/external/rag"
    source deploy/compose/nvdev.env
    export NVIDIA_API_KEY="$INFERENCE_KEY"
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
    # Bring up the RAG-owned infra (Elasticsearch + SeaweedFS) and the FULL ingestor
    # stack (including its bundled redis), like phase2_rag.sh does. The old code
    # assumed VSS owned Elasticsearch (:9200) and Redis (:6379) on the host IP and
    # skipped vectordb.yaml — but on a CPU-only / no-VSS box nothing provides them,
    # so RAG never goes healthy. Use the in-network service names (no HOST_IP override).
    # ── ARM64 (DGX Spark / GB10) arch guard ──────────────────────────────────
    # Official rag/ingestor/nv-ingest images are amd64-only and die with
    # "exec format error" on aarch64. On arm64, use the locally-built arm64 images
    # (deploy/build_arm64_images.sh) + overrides. NO-OP on x86 (arrays empty, TAG unset
    # -> official :2.6.0 images, command lines byte-for-byte unchanged).
    ING_OVR=(); SRV_OVR=()
    if [ "$(uname -m)" = aarch64 ]; then
        export TAG=2.6.0-arm64 NVIDIA_DISABLE_REQUIRE=1
        export APP_NVINGEST_EXTRACTTABLES=False APP_NVINGEST_EXTRACTCHARTS=False
        export ENABLE_REDIS_BACKEND=True MAX_INGEST_PROCESS_WORKERS=2 APP_VECTORSTORE_INDEXTYPE=""
        bash "$REPO_ROOT/deploy/build_arm64_images.sh"   # idempotent: builds arm64 images only if missing
        ING_OVR=(-f "$REPO_ROOT/deploy/compose.ingestor.arm64.override.yaml")
        SRV_OVR=(-f "$REPO_ROOT/deploy/compose.rag-server.arm64.override.yaml")
    fi
    # Who owns Elasticsearch/Redis depends on whether VSS came up in step 0.
    # VSS binds :9200 and :6379 with network_mode=host, so on a VSS box RAG's own
    # vectordb.yaml cannot bind those ports, and rag-server pointed at the in-network
    # service name "elasticsearch" would query the wrong (or a dead) store. On a
    # CPU-only / no-VSS box nothing else provides them, so RAG must start its own.
    # Same wiring phase5_vss.sh applies in its reconnect step.
    # ING_SVCS: which services of the ingestor compose to start. The file bundles its
    # own `redis`, which binds host :6379 — the SAME port VSS already owns. On a VSS box
    # that bind fails ("address already in use") and aborts the whole script under set -e,
    # so name the services explicitly and let nv-ingest/ingestor use VSS's Redis via
    # REDIS_HOST. Same reasoning as ingest_start.sh. On a no-VSS box start everything.
    ING_SVCS=()
    if docker ps -q --filter "name=^/vss-agent$" | grep -q .; then
        HOST_ES_IP="$(ip route get 1.1.1.1 2>/dev/null | awk '/src/{for(i=1;i<=NF;i++) if($i=="src") print $(i+1); exit}')"
        export APP_VECTORSTORE_URL="http://${HOST_ES_IP}:9200"
        export REDIS_HOST="${HOST_ES_IP}"
        ING_SVCS=(--no-deps ingestor-server nv-ingest-ms-runtime)
        echo "  VSS detected — using VSS-owned Elasticsearch/Redis at ${HOST_ES_IP}"
    else
        echo "  No VSS — starting RAG-owned Elasticsearch + SeaweedFS"
        docker compose -f deploy/compose/vectordb.yaml up -d
    fi
    docker compose -f deploy/compose/docker-compose-ingestor-server.yaml "${ING_OVR[@]}" up -d "${ING_SVCS[@]}"
    docker compose -f deploy/compose/docker-compose-rag-server.yaml "${SRV_OVR[@]}" up -d
    docker network connect nvidia-rag amms-aiq-agent 2>/dev/null || true
    cd "$REPO_ROOT"
    wait_http "RAG ingestor" "http://localhost:8082/v1/health" 120
    wait_http "RAG server"   "http://localhost:8081/v1/health" 120
    echo "  RAG ingestor: http://localhost:8082"
    echo "  RAG server:   http://localhost:8081"
else
    echo "  SKIP: external/rag not found (run Phase 2 first)"
fi

# ── 3. Sherlock MCP ───────────────────────────────────────────────────────────
# Must start BEFORE AI-Q: the unified config has mcp_sherlock_tools in
# function_groups, and the MCP client connects at AI-Q startup — if the server
# isn't reachable yet, AI-Q fails with "Temporary failure in name resolution".

echo ""
echo "[3/6] Sherlock MCP (graph + audio tools)"
docker network create \
    --label com.docker.compose.project=amms \
    --label com.docker.compose.network=aiq-network \
    amms_aiq-network 2>/dev/null || true
docker compose -p amms -f deploy/compose.sherlock_mcp.yaml up -d
wait_port "Sherlock MCP" "localhost" 9901 90
echo "  Sherlock MCP: http://localhost:9901/mcp"

# ── 3b. VSS Sherlock MCP (video tools — must be up before AI-Q) ───────────────

if curl -sf --max-time 3 http://localhost:8000/health 2>/dev/null | grep -q isAlive; then
    docker compose -p amms -f "$REPO_ROOT/deploy/compose.vss_sherlock_mcp.yaml" up -d
    echo -n "  Waiting for VSS Sherlock MCP..."
    for i in $(seq 1 20); do
        STATUS=$(docker inspect amms-vss-sherlock-mcp --format '{{.State.Health.Status}}' 2>/dev/null)
        [ "$STATUS" = "healthy" ] && echo " ready" && break
        sleep 3; echo -n "."
    done
    echo "  VSS Sherlock MCP: http://localhost:9903/mcp"
else
    echo "  VSS Sherlock MCP skipped — vss-agent not running"
fi

# ── 4. AI-Q (Sherlock config + prompt volume mount) ───────────────────────────

echo ""
echo "[4/6] AI-Q (Sherlock config)"
# Materialize the MCP-enabled config (graph tools + knowledge layer) into the
# bind-mounted configs dir. Safe here because step [3/5] already started the
# Sherlock MCP server — AI-Q's mcp_client can connect at startup. (The MCP-free
# config_sherlock_frag.yml base is only for the phase-by-phase path, Phases 1-6.)
cp "$REPO_ROOT/deploy/aiq-configs/config_sherlock_frag_mcp.yml" \
   "$REPO_ROOT/external/aiq/configs/config_sherlock_frag.yml"
docker compose -p amms \
    --env-file "$REPO_ROOT/external/aiq/deploy/.env" \
    -f "$AIQ_COMPOSE" \
    -f "$REPO_ROOT/deploy/compose.amms.override.yaml" \
    up -d aiq-agent postgres

wait_http "AI-Q" "http://localhost:8100/health" 90

# Re-apply the nat/runtime/runner.py ContextVar patch. It lives in the container's
# WRITABLE LAYER, so the `up -d` above silently discards it whenever compose recreates
# aiq-agent (config change, image change, --force-recreate). Without it, MCP tool
# results streaming back on a different asyncio task raise
# `ValueError: <Token> was created in a different Context` and are DROPPED — the user
# sees an empty answer. Idempotent: a no-op (and no restart) when already patched.
# Non-fatal: a patch failure must not take down a working stack.
if [ -x "$REPO_ROOT/deploy/patch_aiq_runner.sh" ] || [ -f "$REPO_ROOT/deploy/patch_aiq_runner.sh" ]; then
    bash "$REPO_ROOT/deploy/patch_aiq_runner.sh" 2>&1 | sed 's/^/  /' \
        || echo "  WARNING: patch_aiq_runner.sh failed — MCP tool results may be dropped."
fi

echo "  AI-Q: http://localhost:8100"

# ── 5. Case Workbench UI ──────────────────────────────────────────────────────

echo ""
echo "[5/6] Case Workbench UI"
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
echo "  Sherlock MCP:            http://localhost:9901/mcp  (graph + audio tools)"
echo "  VSS agent:               http://localhost:8000"
echo "  VSS Sherlock MCP:        http://localhost:9903/mcp  (video tools)"
echo ""
echo "  Log tails:"
echo "    docker logs -f amms-aiq-agent"
echo "    docker logs -f amms-sherlock-mcp"
echo "    docker logs -f amms-workbench"
