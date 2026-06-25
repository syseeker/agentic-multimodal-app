#!/usr/bin/env bash
# Benchmark TTFT + output tokens/s against a running vLLM server with aiperf
# (successor to GenAI-Perf). Models in this app are long-context / short-output,
# so we bias the profile that way.
#
#   pip install aiperf
#   ./benchmark/run_aiperf.sh text 8001
set -euo pipefail

NAME="${1:-text}"
PORT="${2:-8001}"
OUT="benchmark/results/${NAME}"
mkdir -p "$OUT"

# Long input, short output — matches forensic summarization workloads.
aiperf profile \
  --model "$NAME" \
  --url "http://localhost:${PORT}" \
  --endpoint-type chat \
  --synthetic-input-tokens-mean 4096 \
  --synthetic-input-tokens-stddev 512 \
  --output-tokens-mean 256 \
  --concurrency 5 \
  --request-count 100 \
  --artifact-dir "$OUT"

echo "Results in $OUT (see metrics for TTFT p50/p99 and output tok/s)."
echo "Compare QUANT=bf16 vs fp8 and GPU_PROFILE=rtx6000 vs gb10."
