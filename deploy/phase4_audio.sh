#!/usr/bin/env bash
# Phase 4 — Audio Pipeline
# Deploys: nvidia-riva-client install, audio processing pipeline, RAG BP ingest
# Proof: deploy/PHASE4_AUDIO.md
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== Phase 4: Audio Pipeline (Parakeet RNNT Multilingual) ==="

# ── 1. Load NVIDIA_API_KEY ────────────────────────────────────────────────────
ENV_FILE="$REPO_ROOT/.env"
if [ ! -f "$ENV_FILE" ]; then echo "ERROR: .env not found"; exit 1; fi
NVIDIA_API_KEY_VALUE=$(grep '^NVIDIA_API_KEY=' "$ENV_FILE" | cut -d= -f2- | sed 's/[[:space:]]*#.*//' | tr -d '[:space:]')
[ -z "$NVIDIA_API_KEY_VALUE" ] && { echo "ERROR: NVIDIA_API_KEY not set"; exit 1; }
export NVIDIA_API_KEY="$NVIDIA_API_KEY_VALUE"
echo "✓ NVIDIA_API_KEY loaded (len=${#NVIDIA_API_KEY_VALUE})"
unset NVIDIA_API_KEY_VALUE

# HF_TOKEN — required for MERaLiON-3-10B paralinguistics (gated HuggingFace model)
HF_TOKEN_VALUE=$(grep '^HF_TOKEN=' "$ENV_FILE" | cut -d= -f2- | sed 's/[[:space:]]*#.*//' | tr -d '[:space:]')
if [ -n "$HF_TOKEN_VALUE" ]; then
    export HF_TOKEN="$HF_TOKEN_VALUE"
    echo "✓ HF_TOKEN loaded (MERaLiON paralinguistics enabled)"
else
    echo "  WARN: HF_TOKEN not set — MERaLiON paralinguistics will run as stub"
fi
unset HF_TOKEN_VALUE

# ── 2. Dependencies ───────────────────────────────────────────────────────────
# The worker (data/audio/process_audio.py) declares its deps via a PEP 723 header;
# `uv run` installs them into an isolated env on demand. Avoid system `pip install`
# (PEP 668 on Ubuntu 24.04 / Py3.12 refuses it, and this box has no pip module).
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null; then
    echo "ERROR: uv not found — needed to run the audio worker (PEP 723 deps)."
    echo "  Install (no sudo needed):"
    echo "    curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo "    source \$HOME/.local/bin/env"
    echo "  Then re-run this script."
    exit 1
fi
echo "✓ uv present — audio worker deps resolved on demand"

# ── 3. Verify NVCF reachable + Parakeet RNNT Multilingual available ───────────
echo "Verifying NVCF connectivity and Parakeet RNNT Multilingual function..."
FID=$(curl -fsS -H "Authorization: Bearer $NVIDIA_API_KEY" \
  "https://api.nvcf.nvidia.com/v2/nvcf/functions?visibility=public,authorized" \
  | python3 -c "
import sys, json
for f in json.load(sys.stdin).get('functions', []):
    if f.get('status') == 'ACTIVE' and f.get('name') == 'ai-parakeet-1_1b-rnnt-multilingual-asr':
        print(f['id']); break
" 2>/dev/null)
[ -z "$FID" ] && { echo "ERROR: Parakeet RNNT Multilingual not found in NVCF"; exit 1; }
echo "✓ Parakeet RNNT Multilingual function resolved (FID not printed)"

# ── 4. Check for audio files ──────────────────────────────────────────────────
CASES_DIR="$REPO_ROOT/data/cases"
# Use find's own filtering (grouped -name, exclude .gitkeep) rather than piping to
# `grep -v` — under `set -euo pipefail`, grep returns 1 when it filters out every
# line (i.e. only .gitkeep present), which aborts the script on a no-audio instance.
AUDIO_COUNT=$(find "$CASES_DIR" -path "*/audio/*" -type f \
  \( -name "*.wav" -o -name "*.mp3" -o -name "*.m4a" -o -name "*.aac" \
     -o -name "*.flac" -o -name "*.ogg" -o -name "*.opus" \) \
  ! -name ".gitkeep" 2>/dev/null | wc -l || true)  # || true: find exits non-zero if CASES_DIR is absent
echo "Audio files found in case dirs: $AUDIO_COUNT"

if [ "$AUDIO_COUNT" -eq 0 ]; then
    echo ""
    echo "NOTE: No audio files found in any case audio/ dir."
    echo ""
    echo "Generate synthetic audio first, then re-run this script:"
    echo "  # One case (Magpie TTS, cloud, no GPU):"
    echo "  uv run data/sim/generate_audio_samples.py --case SC-2024-03C5F0E4 --tts magpie"
    echo ""
    echo "  # All 20 cases:"
    echo "  uv run data/sim/generate_audio_samples.py --all --tts magpie"
    echo ""
    echo "  # Pipeline smoke test (no API key needed):"
    echo "  uv run data/sim/generate_audio_samples.py --case SC-2024-03C5F0E4 --test-tone"
    echo ""
    echo "Or drop real audio files into data/cases/<case_id>/audio/ and re-run."
    echo "Supported formats: .wav .mp3 .m4a .aac .flac .ogg .opus"
    echo "(Non-WAV formats require ffmpeg: sudo apt-get install -y ffmpeg)"
    echo ""
    echo "=== Phase 4 ready — generate audio then re-run ==="
    exit 0
fi

# ── 5. nv-ingest Redis connectivity check (same fix as phase3) ───────────────
# After phase5, VSS replaces compose-redis-1 with its own Redis (host-network).
# nv-ingest's MESSAGE_CLIENT_HOST=redis is hardcoded — env overrides are ignored.
# Same scenario applies: phase1→2→3→4→5→4 or phase1→2→4→5→4.
NV_INGEST_CTR="${NV_INGEST_CTR:-compose-nv-ingest-ms-runtime-1}"
if docker ps -q --filter "name=^/${NV_INGEST_CTR}$" | grep -q .; then
    _nv_redis_ok() {
      docker exec "$NV_INGEST_CTR" python3 -c \
        "import socket; s=socket.socket(); s.settimeout(3); s.connect(('redis',6379)); s.close()" \
        2>/dev/null
    }
    if ! _nv_redis_ok; then
        echo "  nv-ingest: 'redis' hostname unreachable — patching /etc/hosts..."
        BRIDGE_GW="$(docker network inspect nvidia-rag --format '{{range .IPAM.Config}}{{.Gateway}}{{end}}' 2>/dev/null)"
        ETH0_IP="$(ip route get 1.1.1.1 2>/dev/null | awk '/src/{for(i=1;i<=NF;i++) if($i=="src") print $(i+1); exit}')"
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
          echo "  ✓ nv-ingest now reaches Redis at ${_REDIS_TARGET}:6379"
        else
          echo "  WARNING: nv-ingest cannot reach Redis — audio ingestion may fail"
        fi
    else
        echo "  ✓ nv-ingest Redis connectivity OK"
    fi
fi

# ── 5b. MERaLiON paralinguistics service ──────────────────────────────────────
# Serve the model over HTTP instead of loading it in every caller. In-process means each
# caller holds ~20 GB of VRAM and the model cannot be shared or pooled; it also cannot be
# load-tested (Phase 9e drives it with aiperf). process_audio.py prefers this service and
# falls back to in-process when it is absent, so this step is optional but recommended.
#
# Skipped without a GPU or HF_TOKEN — MERaLiON needs both, and starting it would only
# produce a service that returns stubs.
MERALION_PORT="${MERALION_PORT:-8500}"
MERALION_URL="http://localhost:${MERALION_PORT}"
if [ "${SKIP_MERALION_SERVICE:-0}" = "1" ]; then
    echo "  MERaLiON service: skipped (SKIP_MERALION_SERVICE=1)"
elif ! command -v nvidia-smi >/dev/null 2>&1 || ! nvidia-smi >/dev/null 2>&1; then
    echo "  MERaLiON service: skipped (no GPU) — paralinguistics will run as stub"
elif [ -z "${HF_TOKEN:-}" ]; then
    echo "  MERaLiON service: skipped (no HF_TOKEN) — paralinguistics will run as stub"
elif curl -sf -m 3 -o /dev/null "${MERALION_URL}/v1/health/ready" 2>/dev/null; then
    echo "  MERaLiON service: already running on :${MERALION_PORT} ✓"
else
    echo "  Starting MERaLiON service on :${MERALION_PORT} (first boot loads ~20 GB)..."
    mkdir -p "$REPO_ROOT/logs"
    nohup uv run "$REPO_ROOT/data/audio/meralion_server.py" --port "$MERALION_PORT" \
        > "$REPO_ROOT/logs/meralion_server.log" 2>&1 &
    echo "    pid=$! log=logs/meralion_server.log"
    echo -n "    waiting for ready (up to 10 min)"
    for _i in $(seq 1 120); do
        if curl -sf -m 3 -o /dev/null "${MERALION_URL}/v1/health/ready" 2>/dev/null; then
            echo " ✓"; break
        fi
        sleep 5; echo -n "."
    done
    if ! curl -sf -m 3 -o /dev/null "${MERALION_URL}/v1/health/ready" 2>/dev/null; then
        echo ""
        echo "    WARN: service did not become ready — see logs/meralion_server.log."
        echo "          Audio still processes; paralinguistics falls back to in-process."
    fi
fi
export MERALION_URL

# ── 6. Process all case audio ─────────────────────────────────────────────────
INGESTOR_URL="${INGESTOR_URL:-http://localhost:8082}"
echo "Processing $AUDIO_COUNT audio file(s)..."
uv run "$REPO_ROOT/data/audio/process_audio.py"
echo "✓ Audio pipeline complete"

# ── 7. Gate verification ──────────────────────────────────────────────────────
echo ""
echo "=== Phase 4 gate verification ==="
echo "Run this query to verify audio transcripts are searchable:"
echo ""
echo '  curl -sf -X POST http://localhost:8100/generate \'
echo '    -H "Content-Type: application/json" \'
echo '    -d '"'"'{"query":"What was said in the audio evidence?"}'"'"' | python3 -m json.tool'
echo ""
echo "Phase 4 proof: deploy/PHASE4_AUDIO.md"
echo "=== Phase 4 audio pipeline complete ==="
