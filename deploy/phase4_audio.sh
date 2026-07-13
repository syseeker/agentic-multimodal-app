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

# ── 2. Dependencies ───────────────────────────────────────────────────────────
# The worker (data/audio/process_audio.py) declares its deps via a PEP 723 header;
# `uv run` installs them into an isolated env on demand. Avoid system `pip install`
# (PEP 668 on Ubuntu 24.04 / Py3.12 refuses it, and this box has no pip module).
export PATH="$HOME/.local/bin:$PATH"
command -v uv >/dev/null || { echo "ERROR: uv not found — needed to run the audio worker (PEP 723 deps)."; exit 1; }
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
    echo "NOTE: No audio files found. Pipeline is installed and verified."
    echo "To process audio:"
    echo "  1. Drop audio files into data/cases/<case_id>/audio/"
    echo "  2. Run: uv run data/audio/process_audio.py"
    echo ""
    echo "Supported formats: .wav, .mp3, .m4a, .aac, .flac, .ogg, .opus"
    echo "For non-WAV formats, ffmpeg is required:"
    echo "  apt-get install -y ffmpeg   # Ubuntu/Debian"
    echo ""
    echo "Phase 4 proof: deploy/PHASE4_AUDIO.md"
    echo "=== Phase 4 installed — ready for audio ==="
    exit 0
fi

# ── 5. Process all case audio ─────────────────────────────────────────────────
INGESTOR_URL="${INGESTOR_URL:-http://localhost:8082}"
echo "Processing $AUDIO_COUNT audio file(s)..."
uv run "$REPO_ROOT/data/audio/process_audio.py"
echo "✓ Audio pipeline complete"

# ── 6. Gate verification ──────────────────────────────────────────────────────
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
