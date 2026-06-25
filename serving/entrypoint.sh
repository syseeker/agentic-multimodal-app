#!/usr/bin/env bash
# Launch one vLLM OpenAI-compatible server. Flags adapt to GPU_PROFILE.
#
# Required env: MODEL, PORT, SERVED_NAME
# Optional env: QUANT (fp8|bf16|awq), MAX_MODEL_LEN, GPU_PROFILE (rtx6000|gb10),
#               SERVING_API_KEY, HF_TOKEN
set -euo pipefail

: "${MODEL:?MODEL is required}"
: "${PORT:?PORT is required}"
: "${SERVED_NAME:=$MODEL}"
QUANT="${QUANT:-fp8}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-16384}"
GPU_PROFILE="${GPU_PROFILE:-rtx6000}"

ARGS=(
  --model "$MODEL"
  --served-model-name "$SERVED_NAME"
  --host 0.0.0.0
  --port "$PORT"
  --max-model-len "$MAX_MODEL_LEN"
  --trust-remote-code            # MERaLiON / Qwen-VL ship custom code
)

# Our default checkpoints are ALREADY quantized (Qwen3-14B-FP8, Qwen3-VL-8B-FP8):
# vLLM auto-detects their quant config, so don't force --quantization for fp8.
# Use fp8-online only to quantize a raw (unquantized) checkpoint on the fly.
case "$QUANT" in
  fp8)        ARGS+=(--kv-cache-dtype fp8) ;;                    # pre-quantized fp8
  fp8-online) ARGS+=(--quantization fp8 --kv-cache-dtype fp8) ;; # quantize raw weights
  nvfp4|fp4)  ARGS+=(--quantization modelopt_fp4 --kv-cache-dtype fp8) ;;
  awq)        ARGS+=(--quantization awq) ;;
  bf16|"")    ARGS+=(--dtype bfloat16) ;;
  *)          ARGS+=(--quantization "$QUANT") ;;
esac

# Per-GPU tuning. GB10 has 128GB unified but low bandwidth -> conservative.
case "$GPU_PROFILE" in
  gb10)
    ARGS+=(--gpu-memory-utilization 0.30 --max-num-seqs 8 --enforce-eager) ;;
  rtx6000|*)
    ARGS+=(--gpu-memory-utilization 0.30 --max-num-seqs 16) ;;
esac

# Three servers share one GPU; ~0.30 each leaves headroom for the OS/runtime.

[ -n "${SERVING_API_KEY:-}" ] && ARGS+=(--api-key "$SERVING_API_KEY")

echo "[serving:$SERVED_NAME] vllm $MODEL quant=$QUANT profile=$GPU_PROFILE port=$PORT"
exec python3 -m vllm.entrypoints.openai.api_server "${ARGS[@]}"
