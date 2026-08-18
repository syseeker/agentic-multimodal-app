#!/usr/bin/env bash
# Phase 9e / S3 — aiperf rate sweep against the local Cosmos VLM (rtvi-vlm, vLLM).
#
#   bash benchmark/preflight.sh && bash benchmark/run_vlm.sh
#
# Env: RTVI_VLM_URL (default http://localhost:8018), RATES (default "1 2 4 8"),
#      GPU_TAG (default rtx_pro6000), DURATION (default 120)
#
# Record results in deploy/PHASE9E_INFERENCE_BENCHMARK.md §10.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VLM_URL="${RTVI_VLM_URL:-http://localhost:8018}"
GPU_TAG="${GPU_TAG:-rtx_pro6000}"
RATES="${RATES:-1 2 4 8}"
DURATION="${DURATION:-120}"
OUT_ROOT="$REPO_ROOT/benchmark/results/$GPU_TAG"
WORKLOAD="$REPO_ROOT/benchmark/workloads/vlm_video.jsonl"

command -v aiperf >/dev/null || { echo "ERROR: aiperf not installed"; exit 1; }
[ -f "$WORKLOAD" ] || { echo "ERROR: $WORKLOAD missing — run build_workloads.py first"; exit 1; }

# ── The model id must come from the server, not from a config file ────────────
# phase5_vss.sh and vss_sherlock_mcp.py disagree about which Cosmos model is loaded.
# The server is the only authority. See PHASE9E §3.
MODEL_ID="$(curl -sf -m 10 "${VLM_URL}/v1/models" | jq -r '.data[0].id // empty')"
[ -n "$MODEL_ID" ] || { echo "ERROR: could not read ${VLM_URL}/v1/models"; exit 1; }

# ── Refuse to benchmark a proxy ───────────────────────────────────────────────
# In openai-compat mode rtvi-vlm holds no weights and forwards to a remote endpoint;
# the run would measure the internet, not this GPU.
if docker ps -q --filter 'name=^/vss-rtvi-vlm$' | grep -q .; then
  MODE="$(docker exec vss-rtvi-vlm printenv RTVI_VLM_MODEL_TO_USE 2>/dev/null || echo unknown)"
  if [ "$MODE" = "openai-compat" ]; then
    echo "ERROR: rtvi-vlm is in openai-compat (proxy) mode — this would measure the remote"
    echo "       endpoint, not the local GPU. Redeploy integrated, then re-run."
    exit 1
  fi
  echo "  serving mode: $MODE"
fi

mkdir -p "$OUT_ROOT"
echo "=== VLM sweep ==="
echo "  url    : $VLM_URL"
echo "  model  : $MODEL_ID"
echo "  rates  : $RATES req/s   duration: ${DURATION}s"

nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv,noheader \
  | sed 's/^/  gpu    : /' || true

for R in $RATES; do
  OUT="$OUT_ROOT/vlm-r${R}"
  echo
  echo "-- rate ${R} req/s -> $OUT"

  # Open-loop (--request-rate + poisson), never --concurrency: closed-loop throttles itself
  # when the server slows, which hides the degradation we are trying to measure.
  # --streaming is required or TTFT/ITL are simply absent from the output.
  #
  # NOTE: aiperf sends plain OpenAI bodies. Sherlock's real video calls also pass
  # num_frames_per_second_or_fixed_frames_chunk / use_fps_for_chunking; add them with
  # --extra-inputs to match production, or state in the report that this measures the
  # default frame-handling path instead.
  aiperf profile \
    --url "$VLM_URL" \
    --model "$MODEL_ID" \
    --endpoint-type chat \
    --input-file "$WORKLOAD" \
    --custom-dataset-type single_turn \
    --streaming \
    --request-rate "$R" \
    --arrival-pattern poisson \
    --benchmark-duration "$DURATION" \
    --warmup-request-count 10 \
    --output-artifact-dir "$OUT" \
    --ui none || echo "  WARN: rate ${R} failed — recorded as a gap, not skipped silently"
done

echo
echo "=== done. Artifacts under $OUT_ROOT ==="
echo "Before reporting, check: error rate 0; TTFT >= 1 ms (below that is a measurement bug);"
echo "and label any p99 computed from fewer than 50 requests as unreliable."
