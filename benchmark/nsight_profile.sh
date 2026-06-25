#!/usr/bin/env bash
# Capture an Nsight Systems timeline of a serving container under load, then
# (optionally) drill into the hottest kernel with Nsight Compute.
#
#   ./benchmark/nsight_profile.sh serving-text
set -euo pipefail

CONTAINER="${1:-serving-text}"
OUT="benchmark/results/nsight"
mkdir -p "$OUT"

PID="$(docker inspect -f '{{.State.Pid}}' "$CONTAINER")"
echo "Profiling $CONTAINER (host pid $PID) for 30s — drive load now (run_aiperf.sh)."

# Timeline: find GPU hotspots / gaps / sync stalls.
nsys profile --duration=30 --output "$OUT/${CONTAINER}_timeline" \
  --trace=cuda,nvtx,osrt --attach "$PID"

echo "Open $OUT/${CONTAINER}_timeline.nsys-rep in Nsight Systems."
echo "For per-kernel detail: ncu --target-processes all --set full <cmd>"
