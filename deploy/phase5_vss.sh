#!/usr/bin/env bash
# Phase 5 — VSS (Video Search & Summarization) 3.2.0
#
# Two deployment paths — selected automatically at runtime:
#
#   PATH A — Local GPU (aarch64 GB10  OR  x86_64 with GPU in the machine)
#     The full stack, including rtvi-vlm (NVDEC + VLM), on this one machine.
#     aarch64: GB10/DGX-SPARK deploy — Jovan's validated path, unchanged.
#     x86_64:  e.g. RTX Pro 6000. dev-profile.sh deploys everything.
#
#   PATH C — No GPU (x86_64, no local GPU)
#     VSS infrastructure only (vss-agent, ES, Redis, Kafka, Kibana, Phoenix).
#     rtvi-vlm is omitted, so there is NO video analysis on this host — the rest of
#     Sherlock (text/audio RAG, graph, workbench) still works. Useful for CPU-only
#     dev boxes and for the fresh-instance E2E validation run.
#
# There is deliberately NO remote-GPU path. Splitting VSS across a CPU host and a
# remote GPU was investigated at length and does not work: the LVS pipeline assumes
# single-machine operation (VIOS hands rtvi-vlm a local file path it cannot read
# across machines, and LVS's GStreamer cannot probe duration over HTTP → end_offset:0).
# Full write-up: .claude/context/implementation-learnings.md → "CPU-to-Remote-GPU ...".
# Do not re-add it — put the GPU in the box that runs VSS.
#
# UI after deploy: http://localhost:7777
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VSS_DIR="$REPO_ROOT/external/vss-3.2.0"
VSS_REF="${VSS_REF:-v3.2.0}"
LLM_MODEL="${VSS_LLM_MODEL:-nvidia/nvidia-nemotron-nano-9b-v2}"
# NO trailing /v1 — VSS's NIM client appends /v1/chat/completions itself.
export LLM_ENDPOINT_URL="${LLM_ENDPOINT_URL:-https://integrate.api.nvidia.com}"

ARCH="$(uname -m)"
HAS_GPU=false
nvidia-smi >/dev/null 2>&1 && HAS_GPU=true

echo "=== Phase 5: VSS 3.2.0 — arch=${ARCH}  gpu=${HAS_GPU} ==="

# ── 1. Common toolchain preflight ─────────────────────────────────────────────
command -v docker >/dev/null || { echo "ERROR: docker not found."; exit 1; }

# GPU runtime check — required only when a local GPU is present.
# VSS GPU containers need the *named* 'nvidia' docker runtime (not just --gpus all).
if [ "$HAS_GPU" = true ]; then
  if ! docker info 2>/dev/null | grep -i 'Runtimes' | grep -qi nvidia; then
    echo "ERROR: Docker's 'nvidia' runtime is not registered — VSS GPU containers need it."
    echo "  Fix (requires sudo):"
    echo "    sudo nvidia-ctk runtime configure --runtime=docker"
    echo "    sudo systemctl restart docker"
    exit 1
  fi
  echo "  GPU driver: $(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1)"
fi

# git-lfs: VSS ships model configs/weights via LFS. Auto-install if missing (no sudo needed).
# Already arch-aware: picks arm64 or amd64 binary automatically.
export PATH="$HOME/.local/bin:$PATH"
if ! git lfs version >/dev/null 2>&1; then
  echo "  git-lfs missing — installing..."
  if sudo -n true 2>/dev/null; then sudo apt-get install -y git-lfs >/dev/null 2>&1 || true; fi
  if ! git lfs version >/dev/null 2>&1; then
    LFSV="${GIT_LFS_VERSION:-3.6.1}"
    A=$([ "$ARCH" = aarch64 ] && echo arm64 || echo amd64)
    curl -fsSL "https://github.com/git-lfs/git-lfs/releases/download/v${LFSV}/git-lfs-linux-${A}-v${LFSV}.tar.gz" -o /tmp/git-lfs.tgz \
      && tar xzf /tmp/git-lfs.tgz -C /tmp \
      && mkdir -p "$HOME/.local/bin" \
      && find "/tmp/git-lfs-${LFSV}" -maxdepth 1 -name git-lfs -type f -exec cp {} "$HOME/.local/bin/" \; \
      && chmod +x "$HOME/.local/bin/git-lfs"
  fi
  git lfs version >/dev/null 2>&1 || { echo "ERROR: git-lfs install failed — install manually."; exit 1; }
fi
git lfs install >/dev/null 2>&1 || true
echo "  git-lfs: $(git lfs version | awk '{print $1}')"

# ── 2. Secrets from root .env ─────────────────────────────────────────────────
ENV_FILE="$REPO_ROOT/.env"
getkey(){ grep "^$1=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- | sed 's/[[:space:]]*#.*//' | tr -d '[:space:]'; }
export NGC_CLI_API_KEY="$(getkey NGC_API_KEY)"
export NVIDIA_API_KEY="$(getkey NVIDIA_API_KEY)"
# VSS's remote-LLM client is OpenAI-compatible; integrate.api.nvidia.com accepts the nvapi- key
# as bearer token — mirror it so OPENAI_API_KEY is never empty (else chat fails with a 401).
export OPENAI_API_KEY="${OPENAI_API_KEY:-$(getkey NVIDIA_API_KEY)}"
export HF_TOKEN="$(getkey HF_TOKEN)"
[ -n "$NGC_CLI_API_KEY" ] || { echo "ERROR: NGC_API_KEY missing in .env."; exit 1; }
[ -n "$NVIDIA_API_KEY" ]  || echo "  WARN: NVIDIA_API_KEY empty — remote LLM auth will fail."
echo "$NGC_CLI_API_KEY" | docker login nvcr.io -u '$oauthtoken' --password-stdin >/dev/null 2>&1 \
  && echo "  nvcr.io login ok"

# ── 3. Clone VSS 3.2.0 (shared across all paths) ──────────────────────────────
if [ ! -d "$VSS_DIR/.git" ]; then
  echo "  cloning VSS $VSS_REF into external/vss-3.2.0 ..."
  git clone --branch "$VSS_REF" \
    https://github.com/NVIDIA-AI-Blueprints/video-search-and-summarization.git "$VSS_DIR"
fi
( cd "$VSS_DIR" && git lfs install && git lfs pull )

# ── 4. Arch-specific deploy ────────────────────────────────────────────────────

if [ "$ARCH" = aarch64 ] && [ "$HAS_GPU" = true ]; then
  # ── PATH A (aarch64 + local GPU): GB10/DGX Spark — Jovan's validated path ────
  echo "  PATH A: GB10/DGX-SPARK — local Cosmos VLM + remote LLM"

  # Unified-memory preflight: local VLM needs ~50 GB of the 128 GB UMA.
  # Will NOT coexist with a large vLLM (e.g. Qwen-35B). Stop it first.
  FREE_MIB=$(free -m | awk 'NR==2{print $7}')
  echo "  unified memory available: ~$((FREE_MIB/1024)) GB"
  if [ "$FREE_MIB" -lt 51200 ] && [ "${VSS_SKIP_MEM_CHECK:-0}" != 1 ]; then
    echo "  Not enough free unified memory for VSS local VLM (~50 GB needed)."
    echo "  Currently held on the GPU:"
    nvidia-smi --query-compute-apps=pid,used_memory,process_name --format=csv,noheader | sed 's/^/        /'
    echo "  Free it first (e.g. docker stop nemoclaw-vllm), then re-run."
    echo "  Bypass with VSS_SKIP_MEM_CHECK=1 (risks OOM)."
    exit 1
  fi

  # Skill (lvs-profile.md § Hard rules): RT-VLM AND LVS image tags must match CPU platform.
  # SBSA (DGX Spark / Grace / aarch64 server-ARM) uses the -sbsa suffix.
  # Enforce here so a stale or default generated.env never pulls the wrong image.
  export RTVI_VLM_IMAGE_TAG="${RTVI_VLM_IMAGE_TAG:-3.2.1-sbsa}"
  export LVS_TAG="${LVS_TAG:-3.2.1-sbsa}"
  echo "  Image tags (SBSA/aarch64): RTVI_VLM_IMAGE_TAG=$RTVI_VLM_IMAGE_TAG  LVS_TAG=$LVS_TAG"

  cd "$VSS_DIR"
  echo "  running: dev-profile.sh up -p base -H DGX-SPARK --use-remote-llm --llm $LLM_MODEL"
  echo "  (first run pulls large images + loads VLM — several minutes)"
  deploy/docker/scripts/dev-profile.sh up -p base -H DGX-SPARK --use-remote-llm --llm "$LLM_MODEL"

elif [ "$ARCH" = x86_64 ]; then
  # ── x86_64: always ask the user — never guess ─────────────────────────────────
  # Pre-set GPU_SETUP=1|2 env var to skip the prompt in non-interactive / CI runs.
  GPU_SETUP="${GPU_SETUP:-}"

  if [ -z "$GPU_SETUP" ] && [ -t 0 ]; then
    echo ""
    echo "  What is your GPU setup?"
    echo "  1) Local GPU in this machine   (PATH A — full VSS + rtvi-vlm NVDEC here)"
    echo "  2) No GPU in this machine      (PATH C — VSS infra only, no video analysis)"
    read -r -p "  Choice [1/2]: " GPU_SETUP
  fi
  # Default to the infra-only path: it is the one that cannot fail for lack of hardware.
  GPU_SETUP="${GPU_SETUP:-2}"

  case "$GPU_SETUP" in
    1)
      # PATH A: local GPU on this x86_64 machine
      echo "  PATH A: x86_64 + local GPU — full VSS with rtvi-vlm NVDEC"
      nvidia-smi >/dev/null 2>&1 || { echo "  ERROR: nvidia-smi not found. Is the GPU driver installed?"; exit 1; }
      echo "  GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | head -1)"
      # Skill: x86_64 uses non-sbsa image tags.
      export RTVI_VLM_IMAGE_TAG="${RTVI_VLM_IMAGE_TAG:-3.2.1}"
      export LVS_TAG="${LVS_TAG:-3.2.1}"
      echo "  Image tags: RTVI_VLM_IMAGE_TAG=$RTVI_VLM_IMAGE_TAG  LVS_TAG=$LVS_TAG"
      # Detect GPU → -H profile for NIM KV-cache sizing.
      GPU_NAME="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 | tr -d '[:space:]')"
      if   echo "$GPU_NAME" | grep -qi "RTX.*Pro.*6000\|Pro.*6000\|RTXPRO6000"; then HW_PROFILE="RTXPRO6000BW"
      elif echo "$GPU_NAME" | grep -qi "RTX.*Pro.*4500\|Pro.*4500\|RTXPRO4500"; then HW_PROFILE="RTXPRO4500BW"
      elif echo "$GPU_NAME" | grep -qi "H100";                                        then HW_PROFILE="H100"
      elif echo "$GPU_NAME" | grep -qi "L40S";                                        then HW_PROFILE="L40S"
      else HW_PROFILE="OTHER"
        echo "  WARN: '$GPU_NAME' not in known profile list — using OTHER"
        echo "        Override: export VSS_HW_PROFILE=<H100|L40S|RTXPRO6000BW|RTXPRO4500BW>"
      fi
      HW_PROFILE="${VSS_HW_PROFILE:-$HW_PROFILE}"
      echo "  Hardware profile: $HW_PROFILE"
      VLM_FLAG="${VSS_VLM_MODEL:+--vlm ${VSS_VLM_MODEL}}"
      # Cosmos Reason2-8B (Jovan's original choice — DO NOT DELETE):
      # Has a VLM_NAME naming bug in rtvi-vlm 3.2.1: the cosmos-reason2 code path
      # calls the internal vLLM as "nvidia/cosmos-reason2-8b" but vLLM registers
      # the model as "nim_nvidia_cosmos-reason2-8b_hf-1208" → 400 BadParameters.
      # Re-enable when NVIDIA fixes rtvi-vlm or a workaround is found.
      # VLM_FLAG="${VLM_FLAG:---vlm nvidia/cosmos-reason2-8b}"
      #
      # Cosmos Reason1-7B — officially supported by VSS skill (vss-deploy-profile
      # references/lvs-profile.md), smaller VRAM footprint, no naming bug.
      # Switch back to Reason2 by uncommenting the line above and commenting this one.
      VLM_FLAG="${VLM_FLAG:---vlm nvidia/cosmos-reason1-7b}"

      # dev-profile.sh copies the profile .env → generated.env and does NOT
      # read RTVI_VLM_IMAGE_TAG / LVS_TAG from the shell environment.
      # Patch the profile .env directly so the correct tags flow into generated.env.
      PROFILE_ENV="$VSS_DIR/deploy/docker/developer-profiles/dev-profile-lvs/.env"
      sed -i "s|^RTVI_VLM_IMAGE_TAG=.*|RTVI_VLM_IMAGE_TAG=\"${RTVI_VLM_IMAGE_TAG}\"|" "$PROFILE_ENV"
      sed -i "s|^LVS_TAG=.*|LVS_TAG=\"${LVS_TAG}\"|" "$PROFILE_ENV"
      echo "  Patched profile .env: RTVI_VLM_IMAGE_TAG=${RTVI_VLM_IMAGE_TAG}  LVS_TAG=${LVS_TAG}"

      # dev-profile.sh tears down the mdx project before re-creating it, but the
      # RAG Blueprint's elasticsearch and redis containers are on a different project
      # (nvidia-rag). VSS and RAG BP both try to use the same host-port names
      # ("elasticsearch", "redis") — Docker refuses to create duplicates.
      # Stop and remove the RAG BP versions first; the reconnect step below
      # re-points them at VSS's ES/Redis after VSS is up.
      for _c in elasticsearch compose-redis-1; do
        if docker ps -q --filter "name=^/${_c}$" | grep -q .; then
          docker stop "$_c" && docker rm "$_c" 2>/dev/null || true
          echo "  Removed conflicting container: ${_c} (VSS will own ES + Redis)"
        fi
      done

      cd "$VSS_DIR"
      echo "  running: dev-profile.sh up -p lvs -H $HW_PROFILE --use-remote-llm $VLM_FLAG"
      deploy/docker/scripts/dev-profile.sh up -p lvs -H "$HW_PROFILE" --use-remote-llm --llm "$LLM_MODEL" $VLM_FLAG
      ;;

    2|*)
      # PATH C: no GPU on this host — infra only, no video analysis
      echo "  PATH C: x86_64 + no GPU — VSS infra only (no rtvi-vlm, no video analysis)"
      echo "          Text/audio RAG, graph, and the workbench are unaffected."
      GPU_SETUP=2
      ;;
  esac

  # PATH A is deployed entirely by dev-profile.sh above (case 1) — including rtvi-vlm.
  # Everything below builds the CPU-only infra stack and must NOT run for PATH A:
  # it regenerates generated.env with HARDWARE_PROFILE=OTHER, deletes the rtvi-vlm
  # service from resolved.yml, and runs `compose down` — which would tear down the
  # working GPU deploy that dev-profile.sh just created.
  # (This was previously guarded by `[ x = 1 ] && {...} ||` which, because `||` binds
  # to the single next command, only skipped the first export. PATH A fell through
  # and destroyed itself.)
  if [ "$GPU_SETUP" = "1" ]; then
    echo "  PATH A complete — full VSS stack deployed by dev-profile.sh."

    # dev-profile.sh drives compose itself and never writes a top-level resolved.yml,
    # but start_all.sh gates its VSS step on that file existing -- so after a PATH A
    # deploy VSS is running yet start_all.sh reports "VSS not deployed" and skips it.
    # Emit the same snapshot PATH C builds. This is READ-ONLY: `config` + normalize only,
    # no down/build/up, so it cannot disturb the stack dev-profile.sh just brought up.
    # NOTE: resolved.yml has secrets interpolated inline -- external/ is gitignored, keep it so.
    VSS_DOCKER_A="$VSS_DIR/deploy/docker"
    ENV_GEN_A="$VSS_DOCKER_A/developer-profiles/dev-profile-lvs/generated.env"
    if [ -f "$ENV_GEN_A" ]; then
      echo "  generating resolved.yml snapshot (for start_all.sh VSS detection) ..."
      (
        cd "$VSS_DOCKER_A"
        # stdout ONLY -- 2>&1 would corrupt the YAML with stderr noise.
        docker compose --env-file "$ENV_GEN_A" config 2>/dev/null > resolved.yml
        export PATH="$HOME/.local/bin:$PATH"
        NORMALIZE_SCRIPT="$HOME/skills/skills/vss-deploy-profile/scripts/normalize_resolved_yml.py"
        if [ -f "$NORMALIZE_SCRIPT" ]; then
          uv run "$NORMALIZE_SCRIPT" resolved.yml >/dev/null
        else
          echo "  WARNING: normalize script missing ($NORMALIZE_SCRIPT) -- run: cd ~/skills && git pull"
        fi
        docker compose -f resolved.yml config --quiet 2>/dev/null \
          && echo "  resolved.yml OK" \
          || echo "  WARNING: resolved.yml did not validate -- start_all.sh will skip VSS"
      ) || echo "  WARNING: resolved.yml generation failed (non-fatal; VSS is already up)"
    else
      echo "  WARNING: $ENV_GEN_A missing -- cannot emit resolved.yml"
    fi
  else

  # Skill (lvs-profile.md § Hard rules): x86_64 / Jetson Thor must use non-sbsa tags.
  export RTVI_VLM_IMAGE_TAG="${RTVI_VLM_IMAGE_TAG:-3.2.1}"
  export LVS_TAG="${LVS_TAG:-3.2.1}"
  echo "  Image tags (x86_64): RTVI_VLM_IMAGE_TAG=$RTVI_VLM_IMAGE_TAG  LVS_TAG=$LVS_TAG"

  VSS_DOCKER="$VSS_DIR/deploy/docker"
  ENV_GEN="$VSS_DOCKER/developer-profiles/dev-profile-lvs/generated.env"

  # generated.env is NOT committed to the VSS repo — it is produced by dev-profile.sh at
  # deploy time (it copies .env → generated.env then populates LLM/VLM mode vars).
  # --dry-run generates the file without actually starting any docker containers.
  # -H OTHER: no local GPU on this host; skips GPU-specific hw-*.env sizing lookups.
  # --use-remote-vlm: sets RTVI_VLM_MODEL_PATH=none + RTVI_VLM_MODEL_TO_USE=openai-compat
  #   in generated.env so rtvi-vlm starts without trying to load model weights locally.
  # generated.env is NOT committed to the repo — it must be generated at deploy time.
  # dev-profile.sh --dry-run deletes it as cleanup, so we generate it manually instead:
  # copy the committed .env template then update only the vars that need to change for
  # remote LLM/VLM mode on a CPU host. This is exactly what dev-profile.sh does internally.
  echo "  generating generated.env from .env template ..."

  # Helper: set or update a var (handles existing, commented, or missing lines).
  _set_env() {
    local k="$1" v="$2"
    if grep -q "^${k}=" "$ENV_GEN" 2>/dev/null; then
      sed -i "s|^${k}=.*|${k}=${v}|" "$ENV_GEN"
    elif grep -Eq "^#[[:space:]]*${k}=" "$ENV_GEN" 2>/dev/null; then
      sed -i -E "s|^#[[:space:]]*${k}=.*|${k}=${v}|" "$ENV_GEN"
    else
      echo "${k}=${v}" >> "$ENV_GEN"
    fi
  }

  cp "$VSS_DOCKER/developer-profiles/dev-profile-lvs/.env" "$ENV_GEN"

  # Required paths (template has placeholders "/path/to/..." and '<HOST_IP>').
  VSS_DATA="${VSS_DATA_DIR:-$HOME/vss-data}"
  # eth0 IP — everything that talks to Kafka/Redis is on this same host.
  HOST_IP="$(ip route get 1.1.1.1 2>/dev/null | awk '/src/{for(i=1;i<=NF;i++) if($i=="src") print $(i+1); exit}')"
  _set_env VSS_APPS_DIR  "$VSS_DOCKER"
  _set_env VSS_DATA_DIR  "$VSS_DATA"
  _set_env HOST_IP       "$HOST_IP"
  _set_env HARDWARE_PROFILE OTHER   # no local GPU on this host

  # API keys (template has empty strings).
  _set_env NGC_CLI_API_KEY  "'${NGC_CLI_API_KEY}'"
  _set_env NVIDIA_API_KEY   "'${NVIDIA_API_KEY}'"
  _set_env OPENAI_API_KEY   "'${OPENAI_API_KEY}'"

  # Remote LLM (template defaults to local_shared).
  _set_env LLM_MODE     remote
  _set_env LLM_BASE_URL "$LLM_ENDPOINT_URL"

  # Remote VLM / rtvi-vlm (proxies to GPU instance when ready, else hosted NIM).
  # Skill lvs-profile.md: RTVI_VLM_ENDPOINT must include /v1 (RT-VLM reads verbatim).
  VLM_BASE="$LLM_ENDPOINT_URL"
  _set_env VLM_MODE              remote
  _set_env RTVI_VLM_MODEL_PATH   none
  _set_env RTVI_VLM_MODEL_TO_USE openai-compat
  _set_env RTVI_VLM_ENDPOINT     "${VLM_BASE}/v1"

  # Image tags — template ships 3.2.0; enforce correct non-sbsa tags for x86_64.
  _set_env RTVI_VLM_IMAGE_TAG "$RTVI_VLM_IMAGE_TAG"
  _set_env LVS_TAG            "$LVS_TAG"

  echo "  generated.env created ✓  (HOST_IP=${HOST_IP}  LLM=${LLM_ENDPOINT_URL}  VLM=${VLM_BASE})"

  # PATH C has no rtvi-vlm at all — RTVI_VLM_ENDPOINT stays pointed at the hosted NIM
  # (set above) and the service is stripped from resolved.yml below. No video analysis.
  echo "  PATH C: no rtvi-vlm on this host — video analysis unavailable."

  # Data directories (must exist before compose up).
  mkdir -p "$VSS_DATA/data_log/"{analytics_cache,calibration_toolkit,elastic/{data,logs},kafka,redis/{data,log}}
  mkdir -p "$VSS_DATA/agent_eval/"{dataset,results}
  # chmod may fail on root-owned files left by previous Docker runs — suppress and continue.
  # The directories themselves are accessible; Docker containers write as root regardless.
  chmod -R 777 "$VSS_DATA/data_log" "$VSS_DATA/agent_eval" 2>/dev/null || \
    sudo chmod -R 777 "$VSS_DATA/data_log" "$VSS_DATA/agent_eval" 2>/dev/null || true

  cd "$VSS_DOCKER"

  # Generate resolved.yml — stdout ONLY (2>&1 would corrupt the YAML with stderr noise).
  docker compose --env-file "$ENV_GEN" config 2>/dev/null > resolved.yml

  # Skill (SKILL.md § Step 3d): normalize_resolved_yml.py MUST run after config, before up -d.
  # Skipping this aborts the deploy with "depends on undefined service" errors.
  # The script is in the SKILLS repo — NOT in the VSS blueprint dir.
  export PATH="$HOME/.local/bin:$PATH"
  NORMALIZE_SCRIPT="$HOME/skills/skills/vss-deploy-profile/scripts/normalize_resolved_yml.py"
  if [ -f "$NORMALIZE_SCRIPT" ]; then
    uv run "$NORMALIZE_SCRIPT" resolved.yml
  else
    echo "ERROR: normalize script not found at $NORMALIZE_SCRIPT"
    echo "  Run: cd ~/skills && git pull"
    exit 1
  fi
  # Re-validate after normalize (SKILL.md Step 3d).
  docker compose -f resolved.yml config --quiet && echo "  resolved.yml OK"

  # Remove rtvi-vlm from local compose entirely — it needs NVDEC hardware and cannot
  # run on this CPU host even in remote-VLM mode. PATH C therefore has no video analysis.
  # Stripping GPU flags is not enough — rtvi-vlm still fails health checks without NVDEC.
  # Also strip GPU flags from sensor-ms and streamprocessing-ms (they can run CPU-mode).
  python3 - <<'PYEOF'
import yaml
path = 'resolved.yml'
with open(path) as f:
    c = yaml.safe_load(f)
svcs = c.get('services', {})
# Remove rtvi-vlm entirely — health check fails without NVDEC GPU hardware.
# Also purge all depends_on references to it (normalize only strips optional ones;
# lvs-server has a hard depends_on: rtvi-vlm that must be cleaned up too).
if 'rtvi-vlm' in svcs:
    del svcs['rtvi-vlm']
    print("  resolved.yml: removed rtvi-vlm service (runs on GPU machine, not here)")
for svc_name, svc_def in svcs.items():
    dep = svc_def.get('depends_on', {})
    if 'rtvi-vlm' in dep:
        del dep['rtvi-vlm']
        if not dep:
            del svc_def['depends_on']
        print(f"  resolved.yml: removed rtvi-vlm depends_on from {svc_name}")
# Strip GPU requirements from remaining containers that can run in CPU mode.
for svc in ['sensor-ms', 'streamprocessing-ms']:
    if svc in svcs:
        svcs[svc].pop('runtime', None)
        svcs[svc].get('deploy', {}).get('resources', {}).get('reservations', {}).pop('devices', None)
        print(f"  resolved.yml: stripped GPU reqs from {svc}")
with open(path, 'w') as f:
    yaml.dump(c, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
PYEOF

  # Stop containers that conflict with VSS's Elasticsearch (:9200) and Redis (:6379).
  # VSS owns these; RAG Blueprint must reconnect to VSS's instances after this step.
  for c in elasticsearch compose-redis-1; do
    if docker ps -q --filter "name=^/${c}$" | grep -q .; then
      docker stop "$c" && docker rm "$c"
      echo "  Removed conflicting container: $c (VSS will own ES + Redis)"
    fi
  done

  # Tear down any previous partial/stale deployment first (SKILL.md Step 0).
  # --remove-orphans cleans up containers from prior interrupted runs.
  echo "  Tearing down any existing mdx deployment..."
  docker compose -f resolved.yml --env-file "$ENV_GEN" -p mdx down --remove-orphans 2>&1 | \
    grep -E "Removed|Stopped|Removing" || true

  # Pre-build custom images (elasticsearch, kibana-init, broker-health-check).
  # Docker Compose v5 tries to pull before build; pull fails for custom images with no
  # registry entry, blocking the deploy. Building first avoids the pull-then-fail path.
  echo "  Building custom images (cached on repeat runs — no output if up to date)..."
  docker compose -f resolved.yml --env-file "$ENV_GEN" build 2>&1 | grep -E "Built|Building|ERROR" || true

  # Deploy the infra-only stack (rtvi-vlm stripped above) — safe to start lvs-server.
  docker compose -f resolved.yml --env-file "$ENV_GEN" -p mdx up -d --remove-orphans

  fi   # end PATH C infra block (skipped for PATH A)

else
  echo "ERROR: Unsupported combination: arch=${ARCH} gpu=${HAS_GPU}"
  echo "  Supported: aarch64+GPU (GB10), x86_64+GPU (RTX Pro 6000), x86_64+no-GPU (CPU host)"
  exit 1
fi

# ── Reconnect RAG Blueprint → VSS Elasticsearch + Redis (ALL PATHS) ──────────
# Both paths (A local GPU, C no GPU) kill the RAG-owned elasticsearch and redis
# containers and replace them with VSS's host-network versions. Either path may
# have RAG Blueprint running (phases 1-2 precede phase 5 in the recommended order).
# Guards: docker ps checks skip gracefully if RAG services aren't present.
# Use eth0 IP — RAG containers are on the nvidia-rag bridge and reach the host
# via the Docker gateway.
ETH0_IP="$(ip route get 1.1.1.1 2>/dev/null | awk '/src/{for(i=1;i<=NF;i++) if($i=="src") print $(i+1); exit}')"
RAG_DIR="$REPO_ROOT/external/rag"
if [ -d "$RAG_DIR" ] && \
   { docker ps -q --filter "name=^/rag-server$" | grep -q . || \
     docker ps -q --filter "name=^/ingestor-server$" | grep -q .; }; then
  echo "  Reconnecting RAG Blueprint → VSS ES:${ETH0_IP}:9200 Redis:${ETH0_IP}:6379 ..."
  cd "$RAG_DIR"
  # `--force-recreate` below re-derives EVERY env var from compose defaults, so anything
  # phase2_rag.sh established and does not re-export here is LOST. That silently produced:
  #   - all per-role APP_*_APIKEY unset  -> 401 from the embedder/reranker
  #   - ENABLE_AGENTIC_RAG back to false -> agentic pipeline quietly off
  #   - NVIDIA_API_KEY = the REGISTRY key -> 403 on integrate.api.nvidia.com
  # i.e. rag-server came back up unable to search at all. Keep this block in sync with
  # phase2_rag.sh:53-61.
  INFERENCE_KEY="$(getkey NVIDIA_API_KEY)"      # capture BEFORE nvdev.env clobbers it
  export NGC_API_KEY="${NGC_CLI_API_KEY}"
  source deploy/compose/nvdev.env 2>/dev/null || true
  # nvdev.env line 2 does `export NVIDIA_API_KEY=${NGC_API_KEY}` — undo that. The old
  # `export NVIDIA_API_KEY="${NVIDIA_API_KEY}"` was a no-op: it re-exported the clobbered value.
  export NVIDIA_API_KEY="${INFERENCE_KEY}"
  export APP_EMBEDDINGS_APIKEY="${INFERENCE_KEY}"
  export APP_LLM_APIKEY="${INFERENCE_KEY}"
  export APP_RANKING_APIKEY="${INFERENCE_KEY}"
  export SUMMARY_LLM_APIKEY="${INFERENCE_KEY}"
  export AGENTIC_PLANNER_LLM_APIKEY="${INFERENCE_KEY}"
  export AGENTIC_TASK_LLM_APIKEY="${INFERENCE_KEY}"
  export AGENTIC_SEED_GEN_LLM_APIKEY="${INFERENCE_KEY}"
  export AGENTIC_SYNTHESIS_LLM_APIKEY="${INFERENCE_KEY}"
  export ENABLE_AGENTIC_RAG=true

  # rag-server: Elasticsearch + Redis
  if docker ps -q --filter "name=^/rag-server$" | grep -q .; then
    APP_VECTORSTORE_URL="http://${ETH0_IP}:9200" \
    REDIS_HOST="${ETH0_IP}" \
    docker compose -f deploy/compose/docker-compose-rag-server.yaml \
      up -d --force-recreate rag-server 2>&1 | tail -2
    echo "  rag-server ✓"
  fi

  # ingestor-server: Elasticsearch + Redis
  if docker ps -q --filter "name=^/ingestor-server$" | grep -q .; then
    APP_VECTORSTORE_URL="http://${ETH0_IP}:9200" \
    REDIS_HOST="${ETH0_IP}" \
    docker compose -f deploy/compose/docker-compose-ingestor-server.yaml \
      up -d --force-recreate ingestor-server 2>&1 | tail -2
    echo "  ingestor-server ✓"
  fi

  # nv-ingest: Redis message broker
  # MESSAGE_CLIENT_HOST=redis is hardcoded in the compose file (literal, not a variable),
  # so env var overrides via docker compose are silently ignored. Instead, patch
  # /etc/hosts inside the container — try bridge gateway first (same subnet, no iptables
  # rules needed), fall back to eth0. This proactively fixes nv-ingest so any subsequent
  # phase3 or phase4 ingest works without needing to self-heal.
  NV_INGEST_CTR="compose-nv-ingest-ms-runtime-1"
  if docker ps -q --filter "name=^/${NV_INGEST_CTR}$" | grep -q .; then
    BRIDGE_GW="$(docker network inspect nvidia-rag --format '{{range .IPAM.Config}}{{.Gateway}}{{end}}' 2>/dev/null)"
    _nv_redis_ok() {
      docker exec "$NV_INGEST_CTR" python3 -c \
        "import socket; s=socket.socket(); s.settimeout(3); s.connect(('redis',6379)); s.close()" \
        2>/dev/null
    }
    if ! _nv_redis_ok; then
      _REDIS_TARGET=""
      for _ip in "$BRIDGE_GW" "$ETH0_IP"; do
        [ -z "$_ip" ] && continue
        if docker exec "$NV_INGEST_CTR" python3 -c \
            "import socket; s=socket.socket(); s.settimeout(3); s.connect(('${_ip}',6379)); s.close()" \
            2>/dev/null; then
          _REDIS_TARGET="$_ip"; break
        fi
      done
      if [ -n "$_REDIS_TARGET" ]; then
        docker exec "$NV_INGEST_CTR" \
          sh -c "grep -v '[[:space:]]redis\$' /etc/hosts > /tmp/hosts.new && cat /tmp/hosts.new > /etc/hosts && echo '${_REDIS_TARGET} redis' >> /etc/hosts"
        echo "  nv-ingest: 'redis' → ${_REDIS_TARGET} ✓"
      else
        echo "  nv-ingest: WARN could not reach Redis — phase3/phase4 ingests may fail"
      fi
    else
      echo "  nv-ingest Redis already reachable ✓"
    fi
  fi

  # Reconnect AI-Q to nvidia-rag (force-recreate drops the network attachment)
  docker network connect nvidia-rag amms-aiq-agent 2>/dev/null || true
  echo "  amms-aiq-agent reconnected to nvidia-rag ✓"
  cd "$REPO_ROOT"
fi

# ── 5. Verify vss-agent ────────────────────────────────────────────────────────
# First boot: rtvi-vlm downloads Cosmos Reason2 weights from NGC (~15 GB) before
# vss-agent goes healthy. This normally takes 10–20 min. We wait up to 30 min total
# and print a "still loading" hint every 2 min so the developer knows it's progressing.
echo -n "  waiting for vss-agent (:7777 or :8000) [up to 30 min on first boot]"
VSS_UP=false
for i in $(seq 1 180); do
  if curl -sf -m3 -o /dev/null http://localhost:7777 2>/dev/null || \
     curl -sf -m3 http://localhost:8000/health 2>/dev/null | grep -q '"isAlive"'; then
    echo " up ✓"; VSS_UP=true; break
  fi
  # Every 2 min: hint on what rtvi-vlm is doing (weight download or TRT engine build)
  if [ $((i % 24)) -eq 0 ]; then
    RTVI_STATUS=$(docker inspect rtvi-vlm --format '{{.State.Status}}' 2>/dev/null || echo "not yet created")
    echo ""
    echo -n "  [${i}×10s] rtvi-vlm=${RTVI_STATUS} — still loading (first boot: NGC download + TRT build)"
  fi
  sleep 10; echo -n "."
done
echo ""

if [ "$ARCH" = x86_64 ] && [ "$HAS_GPU" = false ]; then
  echo ""
  echo "  NOTE: deployed without rtvi-vlm — video analysis is unavailable on this host."
  echo "  Video requires a GPU in THIS machine (VSS LVS is single-machine by design)."
  echo "  Move to a GPU box and re-run: bash deploy/phase5_vss.sh   # choose 1"
fi

if [ "$VSS_UP" = false ]; then
  echo ""
  echo "ERROR: vss-agent did not respond after 6 minutes. Phase 5 FAILED."
  echo ""
  echo "Diagnostics:"
  echo "  Container states (look for 'Created' = never started, 'Exited' = crashed):"
  docker ps -a --filter "label=com.docker.compose.project=mdx" \
    --format "    {{.Names}}: {{.Status}}" 2>/dev/null || true
  echo ""
  echo "  Common causes:"
  echo "  1. Name conflict: RAG Blueprint elasticsearch/redis still running when VSS tried to start."
  echo "     Fix: docker stop elasticsearch compose-redis-1 && docker rm elasticsearch compose-redis-1"
  echo "          docker rm -f kafka vss-kibana-init 2>/dev/null || true"
  echo "          ./deploy/phase5_vss.sh   # re-run"
  echo ""
  echo "  2. rtvi-vlm still loading Cosmos Reason2 weights from NGC (~15 GB, first boot only)."
  echo "     Fix: docker logs rtvi-vlm   # check if download is in progress"
  echo "          # If still downloading, just wait and poll:"
  echo "          until curl -sf http://localhost:8000/ | grep -q isAlive; do sleep 30; done"
  echo ""
  echo "  3. Image tag mismatch (pulled 3.2.1 but compose expects different tag)."
  echo "     Fix: docker images | grep vss-rt-vlm   # check what tags exist"
  echo "          docker tag nvcr.io/nvidia/vss-core/vss-rt-vlm:3.2.1 nvcr.io/nvidia/vss-core/vss-rt-vlm:3.2.0"
  exit 1
fi

echo "Phase 5 proof: deploy/PHASE5_VSS.md"
echo "=== VSS 3.2.0 deploy complete — arch=${ARCH} gpu=${HAS_GPU} ==="
