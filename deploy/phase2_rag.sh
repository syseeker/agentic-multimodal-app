#!/usr/bin/env bash
# Phase 2 — RAG Blueprint deployment script
# Follows: rag-blueprint skill (NVIDIA/skills) + docs/deploy-docker-nvidia-hosted.md
# Prerequisite: Phase 1 (amms-aiq-agent) must be running.
#
# IMPORTANT: NGC_API_KEY must have BOTH scopes:
#   - NGC Catalog  → nvcr.io image pulls
#   - AI Foundations / API → hosted NIM inference (embeddings, LLM, reranker)
#
# If you have separate keys:
#   1. docker login nvcr.io with registry key first
#   2. Set NGC_API_KEY = inference key below (Docker uses config.json for pulls)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RAG_DIR="${REPO_ROOT}/external/rag"

[ -f "${REPO_ROOT}/.env" ] || { echo "Missing ${REPO_ROOT}/.env"; exit 1; }

# Clone the RAG Blueprint if missing (mirrors phase1_aiq.sh). external/ is gitignored,
# so the blueprint is cloned fresh at deploy time. Ref pinned to match the 2.6.0 images
# referenced by this script's compose files (PHASE2_RAG.md).
RAG_REF="${RAG_REF:-v2.6.0}"
if [ ! -d "${RAG_DIR}/.git" ]; then
  echo "Cloning RAG Blueprint (${RAG_REF}) into ${RAG_DIR}..."
  git clone https://github.com/NVIDIA-AI-Blueprints/rag.git "${RAG_DIR}"
  git -C "${RAG_DIR}" fetch --depth 1 origin tag "${RAG_REF}" >/dev/null 2>&1 || true
  git -C "${RAG_DIR}" checkout "${RAG_REF}" >/dev/null 2>&1 || true
fi

# ── Load keys from root .env ──────────────────────────────────────────────────
INFERENCE_KEY=$(grep '^NVIDIA_API_KEY=' "${REPO_ROOT}/.env" | cut -d= -f2- | sed 's/[[:space:]]*#.*//' | tr -d '[:space:]')
REGISTRY_KEY=$(grep '^NGC_API_KEY=' "${REPO_ROOT}/.env" | cut -d= -f2- | sed 's/[[:space:]]*#.*//' | tr -d '[:space:]')

[ -z "${INFERENCE_KEY}" ] && { echo "NVIDIA_API_KEY not set in .env"; exit 1; }
[ -z "${REGISTRY_KEY}" ]  && { echo "NGC_API_KEY not set in .env"; exit 1; }

# ── Step 1: Docker login to nvcr.io ──────────────────────────────────────────
echo "=== Step 1: docker login nvcr.io ==="
echo "${REGISTRY_KEY}" | docker login nvcr.io -u '$oauthtoken' --password-stdin

# ── Step 2: Source nvdev.env (sets cloud NIM endpoints) ──────────────────────
echo "=== Step 2: source nvdev.env ==="
cd "${RAG_DIR}"
# nvdev.env line 2 does `export NVIDIA_API_KEY=${NGC_API_KEY}`; NGC_API_KEY must be set
# BEFORE sourcing or `set -u` aborts. (start_all.sh already pre-exports it for this reason.)
export NGC_API_KEY="${REGISTRY_KEY}"
source deploy/compose/nvdev.env

# Override: use inference key for everything (see PHASE2_RAG.md gotcha #1)
export NVIDIA_API_KEY="${INFERENCE_KEY}"
export NGC_API_KEY="${INFERENCE_KEY}"  # Docker pulls use config.json, not this
export APP_EMBEDDINGS_APIKEY="${INFERENCE_KEY}"
export APP_LLM_APIKEY="${INFERENCE_KEY}"
export APP_RANKING_APIKEY="${INFERENCE_KEY}"
export SUMMARY_LLM_APIKEY="${INFERENCE_KEY}"
export AGENTIC_PLANNER_LLM_APIKEY="${INFERENCE_KEY}"
export AGENTIC_TASK_LLM_APIKEY="${INFERENCE_KEY}"
export AGENTIC_SEED_GEN_LLM_APIKEY="${INFERENCE_KEY}"
export AGENTIC_SYNTHESIS_LLM_APIKEY="${INFERENCE_KEY}"
export ENABLE_AGENTIC_RAG=true
export APP_RANKING_MODELNAME="nvidia/llama-nemotron-rerank-vl-1b-v2"

echo "OCR_INFER_PROTOCOL: ${OCR_INFER_PROTOCOL} (expected: http)"
echo "ENABLE_AGENTIC_RAG: ${ENABLE_AGENTIC_RAG}"

# ── ARM64 (DGX Spark / GB10) arch guard ───────────────────────────────────────
# Official rag/ingestor/nv-ingest images are amd64-only ("exec format error" on aarch64).
# On arm64: use locally-built arm64 images (deploy/build_arm64_images.sh) + overrides.
# On x86: official amd64 images + compose.ingestor.override.yaml (shm/tmpfs/CV guards).
ING_OVR=(); SRV_OVR=()
if [ "$(uname -m)" = aarch64 ]; then
    export TAG=2.6.0-arm64 NVIDIA_DISABLE_REQUIRE=1
    export APP_NVINGEST_EXTRACTTABLES=False APP_NVINGEST_EXTRACTCHARTS=False
    export ENABLE_REDIS_BACKEND=True MAX_INGEST_PROCESS_WORKERS=2 APP_VECTORSTORE_INDEXTYPE=""
    bash "${REPO_ROOT}/deploy/build_arm64_images.sh"   # idempotent: builds arm64 images only if missing
    ING_OVR=(-f "${REPO_ROOT}/deploy/compose.ingestor.arm64.override.yaml")
    SRV_OVR=(-f "${REPO_ROOT}/deploy/compose.rag-server.arm64.override.yaml")
else
    # x86 CPU host (hosted inference only, small RAM): same memory/CV guards as arm64,
    # minus the arm64 image repoint (x86 uses the official amd64 images). Without this,
    # nv-ingest gets blueprint defaults (40gb shm, unbounded /tmp) -> a Ray spill-storm
    # fills the host disk. See deploy/compose.ingestor.override.yaml.
    export APP_NVINGEST_EXTRACTTABLES=False APP_NVINGEST_EXTRACTCHARTS=False
    export MAX_INGEST_PROCESS_WORKERS=2
    ING_OVR=(-f "${REPO_ROOT}/deploy/compose.ingestor.override.yaml")
fi

# ── Step 3: Start vector DB ───────────────────────────────────────────────────
echo "=== Step 3: vectordb (elasticsearch + seaweedfs) ==="
docker compose -f deploy/compose/vectordb.yaml up -d

# ── Step 4: Start ingestor ────────────────────────────────────────────────────
echo "=== Step 4: ingestor-server + nv-ingest + redis ==="
docker compose -f deploy/compose/docker-compose-ingestor-server.yaml "${ING_OVR[@]}" up -d

# ── Step 5: Start RAG server (with agentic RAG) ───────────────────────────────
echo "=== Step 5: rag-server + rag-frontend ==="
docker compose -f deploy/compose/docker-compose-rag-server.yaml "${SRV_OVR[@]}" up -d

# ── Step 6: Wire AI-Q to nvidia-rag network ───────────────────────────────────
echo "=== Step 6: connect AI-Q to nvidia-rag network ==="
docker network connect nvidia-rag amms-aiq-agent 2>/dev/null \
  && echo "Connected" || echo "Already connected"

# ── Step 7: Health checks ─────────────────────────────────────────────────────
echo "=== Step 7: health checks ==="
echo -n "Waiting for ingestor-server..."
until curl -sf http://localhost:8082/v1/health > /dev/null 2>&1; do
  printf "."; sleep 5
done
echo " UP"

echo -n "Waiting for rag-server..."
until curl -sf http://localhost:8081/v1/health > /dev/null 2>&1; do
  printf "."; sleep 5
done
echo " UP"

echo ""
echo "Ingestor health:"
curl -sf 'http://localhost:8082/v1/health?check_dependencies=true' \
  | python3 -c "
import sys,json; d=json.load(sys.stdin)
print('  message:', d.get('message'))
for s in ['nim','databases','object_storage','task_management']:
    for i in d.get(s,[]): print(f'  {s}/{i[\"service\"]}: {i[\"status\"]}')
"

echo ""
echo "RAG server health:"
curl -sf 'http://localhost:8081/v1/health?check_dependencies=true' \
  | python3 -c "
import sys,json; d=json.load(sys.stdin)
print('  message:', d.get('message'))
for s in ['nim','databases','object_storage']:
    for i in d.get(s,[]): print(f'  {s}/{i[\"service\"]}: {i[\"status\"]}')
"

echo ""
echo "=== Phase 2 deployment complete ==="
echo "Ingestor API: http://localhost:8082"
echo "RAG API:      http://localhost:8081"
echo "RAG UI:       http://localhost:3001"
echo ""
echo "AI-Q (Sherlock) is wired to RAG via FRAG:"
echo "  RAG_SERVER_URL=http://rag-server:8081/v1"
echo "  RAG_INGEST_URL=http://ingestor-server:8082/v1"
echo "  COLLECTION_NAME=multimodal_data"
echo "  ENABLE_AGENTIC_RAG=true"
