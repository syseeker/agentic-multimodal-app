#!/usr/bin/env bash
# Phase 9e preflight — run BEFORE any benchmark step.
#
# Every check here exists because skipping it produces numbers that look valid and are not.
# Exits non-zero on anything that would invalidate a run.
#
#   bash benchmark/preflight.sh
#
# Record: deploy/PHASE9E_INFERENCE_BENCHMARK.md
set -uo pipefail

VLM_URL="${RTVI_VLM_URL:-http://localhost:8018}"
RAG_URL="${RAG_SERVER_URL:-http://localhost:8081}"
ING_URL="${RAG_INGEST_URL:-http://localhost:8082}"
COLLECTION="${COLLECTION_NAME:-multimodal_data}"

FAIL=0
ok()   { echo "  ✓ $*"; }
warn() { echo "  ! $*"; }
bad()  { echo "  ✗ $*"; FAIL=1; }

echo "=== Phase 9e preflight ==="

# ── 1. GPU present ────────────────────────────────────────────────────────────
echo "-- GPU"
if nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv,noheader 2>/dev/null; then
  ok "nvidia-smi responded"
else
  bad "no GPU / driver. S2-S6 cannot run here."
fi

# ── 2. Tooling ────────────────────────────────────────────────────────────────
echo "-- tooling"
for t in aiperf nsys jq curl; do
  if command -v "$t" >/dev/null 2>&1; then ok "$t: $(command -v $t)"
  else bad "$t MISSING"; fi
done

# ── 3. RT-VLM mode — TRAP 1 ───────────────────────────────────────────────────
# openai-compat means rtvi-vlm holds no model and proxies to a remote endpoint. Benchmarking
# it would measure integrate.api.nvidia.com over the internet, not this GPU.
echo "-- rtvi-vlm serving mode"
if docker ps -q --filter 'name=^/vss-rtvi-vlm$' | grep -q .; then
  MODE="$(docker exec vss-rtvi-vlm printenv RTVI_VLM_MODEL_TO_USE 2>/dev/null || echo unknown)"
  MPATH="$(docker exec vss-rtvi-vlm printenv RTVI_VLM_MODEL_PATH 2>/dev/null || echo unknown)"
  echo "     RTVI_VLM_MODEL_TO_USE=$MODE"
  echo "     RTVI_VLM_MODEL_PATH=$MPATH"
  case "$MODE" in
    openai-compat) bad "PROXY MODE — a benchmark here measures the remote endpoint, not the GPU. Redeploy integrated." ;;
    unknown)       warn "could not read the mode; verify manually before trusting results" ;;
    *)             ok "integrated mode ($MODE) — the model is local" ;;
  esac
else
  bad "vss-rtvi-vlm not running"
fi

# ── 4. Model id — settles the Reason1-vs-Reason2 question ─────────────────────
# Do not guess from phase5_vss.sh or the MCP default; ask the server.
echo "-- VLM model id (authoritative)"
MODEL_ID="$(curl -sf -m 10 "${VLM_URL}/v1/models" 2>/dev/null | jq -r '.data[0].id // empty')"
if [ -n "$MODEL_ID" ]; then
  ok "model id: $MODEL_ID"
  echo "     use this verbatim as aiperf --model"
else
  bad "could not read ${VLM_URL}/v1/models"
fi

# ── 5. Chat endpoint reachable ────────────────────────────────────────────────
# /v1/completions returns 400 by design; only the chat endpoint is usable.
echo "-- VLM chat endpoint"
if curl -sf -m 10 -o /dev/null "${VLM_URL}/v1/health/ready" 2>/dev/null; then
  ok "${VLM_URL}/v1/health/ready"
else
  warn "health/ready not responding (older builds may not expose it)"
fi

# ── 6. RAG collection — a wrong name validates fine and returns zero citations ─
echo "-- RAG"
curl -sf -m 10 -o /dev/null "${RAG_URL}/v1/health" 2>/dev/null \
  && ok "rag-server ${RAG_URL}" || bad "rag-server unreachable at ${RAG_URL}"
COLLECTIONS="$(curl -sf -m 10 "${ING_URL}/v1/collections" 2>/dev/null || echo '')"
if echo "$COLLECTIONS" | grep -q "$COLLECTION"; then
  ok "collection '$COLLECTION' exists"
else
  bad "collection '$COLLECTION' NOT found — rag-perf would report zero citations. Got: ${COLLECTIONS:0:200}"
fi

# ── 7. Noisy neighbours — nv-ingest must not idle co-run with VSS ─────────────
echo "-- resident containers"
if docker ps -q --filter 'name=nv-ingest' | grep -q .; then
  bad "nv-ingest is running. Stop it (deploy/ingest_stop.sh) or capacity numbers are noise."
else
  ok "nv-ingest not resident"
fi

echo
if [ "$FAIL" -eq 0 ]; then
  echo "=== preflight PASSED ==="
else
  echo "=== preflight FAILED — fix the ✗ items above before benchmarking ==="
fi
exit "$FAIL"
