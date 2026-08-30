#!/usr/bin/env bash
# Phase 9a / Track 2a — Phoenix on-premise observability for Sherlock.
# Proof + gotchas: deploy/PHASE9A_OBSERVABILITY.md
#
# What this does:
#   1. Starts a Sherlock-owned Phoenix (amms-phoenix, host :6007) on amms_aiq-network
#   2. Re-materializes the AI-Q config (which now carries the tracing block)
#   3. Restarts amms-aiq-agent  -- restart, NOT recreate (see WHY below)
#   4. Re-applies the runner.py ContextVar patch
#   5. Proves traces actually land in Phoenix (not just "the exporter started")
#
# WHY `docker restart` AND NOT `docker compose up -d --force-recreate`:
#   The config is a read-only BIND MOUNT read once at process start, so a plain
#   `compose up -d` is a NO-OP after a YAML-only edit (config hash unchanged) --
#   it prints "Container amms-aiq-agent Running" and changes nothing.
#   `--force-recreate` DOES apply it but is destructive here: it drops the
#   `nvidia-rag` network (knowledge_search then silently returns nothing) and
#   wipes the writable-layer runner.py patch. `docker restart` re-reads the YAML
#   while keeping both networks and the patch.
#
# Idempotent: safe to re-run.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

PHOENIX_HOST_PORT="${PHOENIX_HOST_PORT:-6007}"
PHOENIX_PROJECT="${PHOENIX_PROJECT:-sherlock}"
PROJECT="${COMPOSE_PROJECT_NAME:-amms}"

echo "=== Phase 9a: Phoenix observability ==="

# ── Step 1: Phoenix ───────────────────────────────────────────────────────────
# -p amms puts it in the same compose project as the rest of the AI-Q stack, so
# `docker compose -p amms ps` shows it alongside the agent.
echo "--- Step 1: start amms-phoenix"
docker compose -p "$PROJECT" -f deploy/compose.phoenix.yaml up -d

echo -n "    waiting for Phoenix to become healthy"
for _ in $(seq 1 40); do
    if curl -sf "http://localhost:${PHOENIX_HOST_PORT}/healthz" >/dev/null 2>&1; then
        echo " UP (http://localhost:${PHOENIX_HOST_PORT})"; break
    fi
    printf "."; sleep 3
done
curl -sf "http://localhost:${PHOENIX_HOST_PORT}/healthz" >/dev/null 2>&1 || {
    echo " FAILED"; echo "    docker logs amms-phoenix"; exit 1; }

# ── Step 2: is the AI-Q agent even running? ───────────────────────────────────
if ! docker ps -q --filter "name=^/amms-aiq-agent$" | grep -q .; then
    echo ""
    echo "amms-aiq-agent is NOT running — Phoenix is up but nothing will trace to it."
    echo "Run the AI-Q phases first (deploy/phase1_aiq.sh, or deploy/start_all.sh),"
    echo "then re-run this script."
    exit 0
fi

# ── Step 3: re-materialize the config carrying the tracing block ──────────────
# Mirrors start_all.sh:263 / phase7_extensions.sh:91. The MCP variant is the one
# that gets deployed once Phase 7 has run; the base is the Phases 1-6 path.
# Both now carry an identical tracing block, so either is fine — pick whichever
# matches what is actually deployed.
echo "--- Step 2: materialize AI-Q config (with tracing block)"
if docker ps -q --filter "name=^/amms-sherlock-mcp$" | grep -q .; then
    SRC="deploy/aiq-configs/config_sherlock_frag_mcp.yml"; echo "    Sherlock MCP is up -> using MCP config"
else
    SRC="deploy/aiq-configs/config_sherlock_frag.yml";     echo "    no Sherlock MCP -> using base config"
fi
cp "$REPO_ROOT/$SRC" "$REPO_ROOT/external/aiq/configs/config_sherlock_frag.yml"

# The eval dataset rides the same read-only /app/configs mount (used by Phase 9b).
cp "$REPO_ROOT/deploy/aiq-configs/sherlock_eval_dataset.json" \
   "$REPO_ROOT/external/aiq/configs/sherlock_eval_dataset.json"

# ── Step 4: restart (see header for why not recreate) ─────────────────────────
echo "--- Step 3: restart amms-aiq-agent"
docker restart amms-aiq-agent >/dev/null
echo -n "    waiting for AI-Q health"
for _ in $(seq 1 60); do
    if curl -sf "http://localhost:${AIQ_PORT:-8100}/health" >/dev/null 2>&1; then echo " UP"; break; fi
    printf "."; sleep 3
done

# ── Step 5: re-apply the ContextVar patch ─────────────────────────────────────
# Not lost by `docker restart` (writable layer survives), but this is the cheap
# insurance the repo already mandates after any AI-Q lifecycle event, and without
# it MCP tool spans show empty outputs and you blame the tracing.
echo "--- Step 4: re-apply runner.py ContextVar patch"
bash "$REPO_ROOT/deploy/patch_aiq_runner.sh" || echo "    (patch script reported an issue — check manually)"

# ── Step 6: prove traces actually arrive ──────────────────────────────────────
# NOTE ON THE PASS CRITERION: do NOT trust `force_flush() == True` or the
# "Started exporter 'phoenix'" log line. Both are True even when every export
# fails with HTTP 405. The only honest check is asking Phoenix what it stored.
echo "--- Step 5: end-to-end trace check"
BEFORE=$(curl -s "http://localhost:${PHOENIX_HOST_PORT}/v1/projects/${PHOENIX_PROJECT}/spans?limit=1000" 2>/dev/null \
         | python3 -c "import json,sys
try: print(len(json.load(sys.stdin).get('data',[])))
except Exception: print(0)")
echo "    spans in project '${PHOENIX_PROJECT}' before: ${BEFORE}"

cat > /tmp/_sherlock_trace_probe.yml <<'YAML'
general:
  telemetry:
    tracing:
      phoenix:
        _type: phoenix
        endpoint: http://amms-phoenix:6006/v1/traces
        project: sherlock
workflow:
  _type: current_datetime
YAML
docker cp /tmp/_sherlock_trace_probe.yml amms-aiq-agent:/tmp/_probe.yml >/dev/null
docker exec amms-aiq-agent /app/.venv/bin/nat run \
    --config_file /tmp/_probe.yml --input "phase9a trace probe" 2>&1 \
  | grep -Ei "Failed to export|error" || true
sleep 8   # exporter flush_interval defaults to 5.0s

AFTER=$(curl -s "http://localhost:${PHOENIX_HOST_PORT}/v1/projects/${PHOENIX_PROJECT}/spans?limit=1000" 2>/dev/null \
        | python3 -c "import json,sys
try: print(len(json.load(sys.stdin).get('data',[])))
except Exception: print(0)")
echo "    spans in project '${PHOENIX_PROJECT}' after:  ${AFTER}"
rm -f /tmp/_sherlock_trace_probe.yml

if [ "$AFTER" -gt "$BEFORE" ]; then
    echo "    ✓ traces are reaching Phoenix"
else
    echo "    ✗ NO NEW SPANS — tracing is not working."
    echo "      Check: docker logs amms-aiq-agent 2>&1 | grep -i 'failed to export'"
    echo "      A 405 means the endpoint is missing the /v1/traces suffix."
    exit 1
fi

echo ""
echo "=== Phase 9a complete ==="
echo "Phoenix UI:  http://localhost:${PHOENIX_HOST_PORT}   (project: ${PHOENIX_PROJECT})"
echo "Ask Sherlock a question in the workbench, then watch the trace tree appear."
