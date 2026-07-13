#!/usr/bin/env bash
# Build ARM64 (aarch64 / DGX Spark GB10) images for the RAG Blueprint service containers
# whose official NGC images are linux/amd64-only (they die with `exec format error` on aarch64):
#   rag-server, ingestor-server, rag-frontend  -> rebuilt from the repo's own build: blocks via TAG
#   nv-ingest                                   -> cloned + a one-line CUDA-repo sbsa fix, built natively
#
# Idempotent: skips any image already present. NO-OP on x86_64 (official images are used there unchanged).
# Inference stays HOSTED, so these run GPU-disabled (CUDA_VISIBLE_DEVICES=-1) — no local NIMs, no VRAM.
set -euo pipefail

if [ "$(uname -m)" != aarch64 ]; then
  echo "[build_arm64_images] host is $(uname -m) — official amd64 images are used, nothing to build."
  exit 0
fi

REPO="$(cd "$(dirname "$0")/.." && pwd)"
RAGC="$REPO/external/rag/deploy/compose"
export TAG="${TAG:-2.6.0-arm64}"
NVING_REF="${NVING_REF:-26.3.0}"
need(){ ! docker image inspect "$1" >/dev/null 2>&1; }

# ── 1. ingestor-server (pure-Python FastAPI; Stage-2 pre-downloads a tokenizer -> needs network) ──
if need "nvcr.io/nvidia/blueprint/ingestor-server:$TAG"; then
  echo ">>> building ingestor-server:$TAG (native aarch64)"
  docker compose -f "$RAGC/docker-compose-ingestor-server.yaml" build ingestor-server
fi

# ── 2. rag-server + rag-frontend (pure-Python / Node; zero source changes) ──
if need "nvcr.io/nvidia/blueprint/rag-server:$TAG" || need "nvcr.io/nvidia/blueprint/rag-frontend:$TAG"; then
  echo ">>> building rag-server + rag-frontend:$TAG (native aarch64)"
  docker compose -f "$RAGC/docker-compose-rag-server.yaml" build rag-server rag-frontend
fi

# ── 3. nv-ingest (the only real port: CUDA apt-repo hardcodes x86_64 -> use sbsa on aarch64) ──
if need "sherlock/nv-ingest:${NVING_REF}-arm64"; then
  SRC="$REPO/external/nv-ingest"
  [ -d "$SRC/.git" ] || git clone https://github.com/NVIDIA/nv-ingest "$SRC"
  git -C "$SRC" fetch --depth 1 origin "refs/tags/${NVING_REF}:refs/tags/${NVING_REF}" 2>/dev/null || true
  git -C "$SRC" checkout "tags/${NVING_REF}" 2>/dev/null || git -C "$SRC" checkout "${NVING_REF}"
  # Fix 1: CUDA apt-repo path may hardcode .../repos/ubuntu2204/x86_64/ (404s on aarch64).
  # We build FOR arm64, so the SBSA (Server Base System Architecture) repo is correct.
  # (No-op at tag 26.3.0 — the line is absent there; kept for other tags.)
  sed -i 's#repos/ubuntu2204/x86_64/cuda-keyring#repos/ubuntu2204/sbsa/cuda-keyring#g' "$SRC/Dockerfile"
  # Fix 2: pin Ray to nv-ingest 26.3.0's locked version (src/uv.lock -> 2.53.0). `uv pip install`
  # (not `uv sync`) resolves Ray 2.56 on arm64, which REMOVED the ray.put(_owner=) arg that
  # nv-ingest's message-broker task-source loop uses -> every ingest crashes at runtime.
  grep -q 'ray==2.53.0' "$SRC/Dockerfile" || \
    sed -i 's#uv pip install ./client/dist/\*.whl#& \&\& uv pip install "ray==2.53.0"#' "$SRC/Dockerfile"
  echo ">>> building sherlock/nv-ingest:${NVING_REF}-arm64 (native aarch64 — long; wheel resolution, not kernel compile)"
  # --target runtime: the Dockerfile's final stage is 'docs'; 'runtime' is the deployable image (entrypoint + no test/dev extras).
  docker buildx build --load --target runtime -t "sherlock/nv-ingest:${NVING_REF}-arm64" -f "$SRC/Dockerfile" "$SRC"
fi

echo "=== ARM64 image build complete ==="
docker images --format '{{.Repository}}:{{.Tag}}' | grep -E 'arm64' || true
