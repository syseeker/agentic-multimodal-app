#!/usr/bin/env bash
# Phase 5 — VSS (Video Search & Summarization) 3.2.0 on DGX Spark (GB10 / ARM64)
#
# Deploys the VSS Blueprint "Standard VSS (Base)" profile: a LOCAL Cosmos-Reason2-8B VLM
# (runs on the GB10) + a REMOTE LLM (hosted NIM). Follows NVIDIA's official DGX Spark VSS
# playbook (github.com/NVIDIA/dgx-spark-playbooks -> nvidia/vss, VSS 3.2.0, Cosmos Reason 2).
#
# This REPLACES the old LVS / rtvi-vlm "remote-all" script (which targeted a CPU-only Brev
# host and predates the VSS 3.x Spark topology). VSS's local VLM needs a GB10 GPU, so unlike
# the RAG stack there is no x86 path here.
#
# UI after deploy: http://localhost:7777
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VSS_DIR="$REPO_ROOT/external/vss-3.2.0"
VSS_REF="${VSS_REF:-v3.2.0}"
LLM_MODEL="${VSS_LLM_MODEL:-nvidia/nvidia-nemotron-nano-9b-v2}"   # remote LLM model name
# hosted NIM base URL — NO trailing /v1: VSS's NIM client appends /v1/chat/completions itself,
# so a /v1 here yields /v1/v1/chat/completions -> 404 "page not found" (masked as a generic error).
export LLM_ENDPOINT_URL="${LLM_ENDPOINT_URL:-https://integrate.api.nvidia.com}"

echo "=== Phase 5: VSS 3.2.0 on DGX Spark (local Cosmos-Reason VLM + remote LLM) ==="

# ── 1. Hardware / toolchain preflight ─────────────────────────────────────────
[ "$(uname -m)" = aarch64 ] || { echo "ERROR: VSS 3.2.0 (local VLM) needs aarch64/GB10. Host is $(uname -m)."; exit 1; }
command -v nvidia-smi >/dev/null || { echo "ERROR: nvidia-smi/GPU not found."; exit 1; }
echo "  driver: $(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1)  (need >= 580.95.05)"
command -v docker >/dev/null || { echo "ERROR: docker not found."; exit 1; }
# VSS's GPU containers use the *named* 'nvidia' docker runtime (compose has `runtime: nvidia`),
# which must be registered in /etc/docker/daemon.json. `--gpus all` (what other apps use) is NOT
# enough. Registering it needs sudo, so fail fast here with the exact fix.
if ! docker info 2>/dev/null | grep -i 'Runtimes' | grep -qi nvidia; then
  echo "ERROR: Docker's 'nvidia' runtime is not registered — VSS needs it."
  echo "  Configure it (requires sudo), then re-run this script:"
  echo "    sudo nvidia-ctk runtime configure --runtime=docker"
  echo "    sudo systemctl restart docker   # note: briefly restarts ALL containers"
  exit 1
fi
# git-lfs: VSS ships model configs/weights via LFS. Auto-install if missing (no sudo needed).
export PATH="$HOME/.local/bin:$PATH"
if ! git lfs version >/dev/null 2>&1; then
  echo "  git-lfs missing — installing..."
  if sudo -n true 2>/dev/null; then sudo apt-get install -y git-lfs >/dev/null 2>&1 || true; fi
  if ! git lfs version >/dev/null 2>&1; then
    LFSV="${GIT_LFS_VERSION:-3.6.1}"; A=$([ "$(uname -m)" = aarch64 ] && echo arm64 || echo amd64)
    curl -fsSL "https://github.com/git-lfs/git-lfs/releases/download/v${LFSV}/git-lfs-linux-${A}-v${LFSV}.tar.gz" -o /tmp/git-lfs.tgz \
      && tar xzf /tmp/git-lfs.tgz -C /tmp \
      && mkdir -p "$HOME/.local/bin" \
      && find "/tmp/git-lfs-${LFSV}" -maxdepth 1 -name git-lfs -type f -exec cp {} "$HOME/.local/bin/" \; \
      && chmod +x "$HOME/.local/bin/git-lfs"
  fi
  git lfs version >/dev/null 2>&1 || { echo "ERROR: git-lfs install failed — install it manually."; exit 1; }
fi
git lfs install >/dev/null 2>&1 || true
echo "  git-lfs: $(git lfs version | awk '{print $1}')"

# ── 2. Secrets from root .env ─────────────────────────────────────────────────
ENV_FILE="$REPO_ROOT/.env"
getkey(){ grep "^$1=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- | sed 's/[[:space:]]*#.*//' | tr -d '[:space:]'; }
export NGC_CLI_API_KEY="$(getkey NGC_API_KEY)"       # dev-profile.sh reads NGC_CLI_API_KEY
export NVIDIA_API_KEY="$(getkey NVIDIA_API_KEY)"     # remote LLM endpoint auth (nim client)
# VSS's remote-LLM client is OpenAI-compatible and auths with OPENAI_API_KEY. The hosted
# integrate.api.nvidia.com endpoint accepts the nvapi- key as the bearer token, so mirror it
# here — otherwise OPENAI_API_KEY is empty and chat fails instantly with a redacted 401.
export OPENAI_API_KEY="${OPENAI_API_KEY:-$(getkey NVIDIA_API_KEY)}"
export HF_TOKEN="$(getkey HF_TOKEN)"                 # VA-MCP / gated model weights
[ -n "$NGC_CLI_API_KEY" ] || { echo "ERROR: NGC_API_KEY missing in .env (needed to pull VSS images)."; exit 1; }
[ -n "$NVIDIA_API_KEY" ] || echo "  WARN: NVIDIA_API_KEY empty — remote LLM auth will fail."
echo "$NGC_CLI_API_KEY" | docker login nvcr.io -u '$oauthtoken' --password-stdin >/dev/null 2>&1 && echo "  nvcr.io login ok"

# ── 3. Unified-memory preflight (the hard constraint on GB10) ─────────────────
# VSS's local VLM reserves a large slice of unified memory; on DGX-SPARK the profile
# targets ~40% (~50GB of 128GB). It will NOT coexist with a big vLLM (e.g. Qwen-35B).
FREE_MIB=$(free -m | awk 'NR==2{print $7}')
echo "  unified memory available: ~$((FREE_MIB/1024)) GB"
if [ "$FREE_MIB" -lt 51200 ] && [ "${VSS_SKIP_MEM_CHECK:-0}" != 1 ]; then
  echo "  ⚠️  Not enough free unified memory for VSS's local Cosmos VLM (~50GB needed)."
  echo "      Currently held on the GPU:"
  nvidia-smi --query-compute-apps=pid,used_memory,process_name --format=csv,noheader | sed 's/^/        /'
  echo "      Free it first, e.g.:  docker stop nemoclaw-vllm   (or kill the VLLM::EngineCore PID),"
  echo "      then re-run.  Bypass this check with VSS_SKIP_MEM_CHECK=1 (risks OOM)."
  exit 1
fi

# ── 4. Clone VSS 3.2.0 (+ Git LFS weights/config) ─────────────────────────────
if [ ! -d "$VSS_DIR/.git" ]; then
  echo "  cloning VSS $VSS_REF into external/vss-3.2.0 ..."
  git clone --branch "$VSS_REF" \
    https://github.com/NVIDIA-AI-Blueprints/video-search-and-summarization.git "$VSS_DIR"
fi
( cd "$VSS_DIR" && git lfs install && git lfs pull )

# ── 5. Deploy Standard VSS (Base): local VLM + remote LLM ─────────────────────
# (Per the DGX Spark playbook. -H DGX-SPARK selects the GB10 profile; device-id flags N/A.)
cd "$VSS_DIR"
echo "  running: deploy/docker/scripts/dev-profile.sh up -p base -H DGX-SPARK --use-remote-llm --llm $LLM_MODEL"
echo "  (first run pulls large images + loads the VLM — several minutes; watch for OOM under UMA.)"
deploy/docker/scripts/dev-profile.sh up -p base -H DGX-SPARK --use-remote-llm --llm "$LLM_MODEL"

# ── 6. Verify UI ──────────────────────────────────────────────────────────────
echo -n "  waiting for VSS Agent UI (:7777)"
for i in $(seq 1 72); do
  if curl -sf -m3 -o /dev/null http://localhost:7777 2>/dev/null; then echo " up ✓"; break; fi
  sleep 5; echo -n "."
done
echo ""
echo "Phase 5 proof: deploy/PHASE5_VSS.md"
echo "=== VSS 3.2.0 (Spark) deploy issued — Agent UI: http://localhost:7777 ==="
