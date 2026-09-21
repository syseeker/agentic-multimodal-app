#!/usr/bin/env bash
# Phase 9b / Track 2b — NAT evaluation + profiling for Sherlock.
# Proof + gotchas: deploy/PHASE9B_EVAL.md
#
# Runs the REAL Sherlock agent over deploy/aiq-configs/sherlock_eval_dataset.json,
# grades each answer with an LLM judge, and profiles where time/tokens go.
#
# Usage:
#   bash deploy/phase9b_eval.sh              # full run (14 questions, ~10-15 min)
#   bash deploy/phase9b_eval.sh --smoke      # 2 questions, to prove plumbing (~2 min)
#   bash deploy/phase9b_eval.sh --validate   # validate config only, run nothing (free)
#
# HOW THIS RUNS THE AGENT -- and why not against the live server:
#   `nat eval --endpoint http://localhost:8100` DOES NOT WORK against AI-Q, and it
#   fails SILENTLY: NAT posts {"input_message": ...} to <endpoint>/generate/full but
#   AI-Q's route requires {"query": ...}. Every item 422s, every output becomes null,
#   and the summary still prints "Workflow Status: COMPLETED" with score 0.
#   So we run the workflow IN-PROCESS instead: the eval config is the deployed
#   workflow config with an eval: block appended. Same agent, same tools, same LLMs.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

MODE="${1:-full}"
AIQ_CFG_DIR="$REPO_ROOT/external/aiq/configs"
DEPLOYED_CFG="$AIQ_CFG_DIR/config_sherlock_frag.yml"
EVAL_CFG="$AIQ_CFG_DIR/config_sherlock_eval.yml"
RESULTS_HOST="$REPO_ROOT/eval/results"

echo "=== Phase 9b: Sherlock evaluation + profiling ==="

docker ps -q --filter "name=^/amms-aiq-agent$" | grep -q . || {
    echo "amms-aiq-agent is not running. Run deploy/start_all.sh first."; exit 1; }

[ -f "$DEPLOYED_CFG" ] || { echo "Missing $DEPLOYED_CFG — run deploy/phase1_aiq.sh first."; exit 1; }

# ── Step 1: build the eval config = deployed workflow + eval fragment ─────────
# Concatenation keeps ONE source of truth for the agent under test. Generating it
# from the DEPLOYED file (not the repo source) matters: the deployed file is the
# MCP variant once Phase 7 has run, and evaluating the non-MCP base instead would
# silently score a different agent than the one in production.
echo "--- Step 1: build eval config"
cat "$DEPLOYED_CFG" "$REPO_ROOT/deploy/aiq-configs/eval_fragment.yml" > "$EVAL_CFG"
echo "    wrote $EVAL_CFG"

# Dataset must be readable inside the container via the /app/configs mount.
cp "$REPO_ROOT/deploy/aiq-configs/sherlock_eval_dataset.json" "$AIQ_CFG_DIR/sherlock_eval_dataset.json"

if [ "$MODE" = "--smoke" ]; then
    # 2 questions only: one normal, one refusal trap.
    python3 -c "
import json
d=json.load(open('$REPO_ROOT/deploy/aiq-configs/sherlock_eval_dataset.json'))
keep=[d[0]] + [x for x in d if x.get('category','').startswith('refusal')][:1]
json.dump(keep, open('$AIQ_CFG_DIR/sherlock_eval_dataset.json','w'), indent=2)
print(f'    smoke mode: {len(keep)} questions')
"
fi

# ── Step 2: validate before spending anything ────────────────────────────────
# `nat validate` catches a bad _type instantly and costs nothing. It does NOT
# resolve llm_name references, so a typo'd judge LLM still passes here and only
# explodes mid-run — that is why eval_fragment.yml pins the verified gpt_oss_llm.
echo "--- Step 2: validate config"
docker exec amms-aiq-agent /app/.venv/bin/nat validate \
    --config_file /app/configs/config_sherlock_eval.yml 2>&1 | tail -5

if [ "$MODE" = "--validate" ]; then
    echo ""; echo "=== validate-only mode: stopping here ==="; exit 0
fi

# ── Step 3: run ──────────────────────────────────────────────────────────────
# output_dir is /app/data/eval/results — /app/data is the ONLY writable mount
# (/app/configs is read-only), so results are copied back out afterwards.
echo "--- Step 3: run nat eval (this runs the real agent — expect 25-60s per question)"
docker exec amms-aiq-agent /app/.venv/bin/nat eval \
    --config_file /app/configs/config_sherlock_eval.yml 2>&1 | tail -40

# ── Step 4: pull results out of the container volume ─────────────────────────
echo "--- Step 4: collect results"
mkdir -p "$RESULTS_HOST"
docker cp amms-aiq-agent:/app/data/eval/results/. "$RESULTS_HOST/" 2>/dev/null \
    && echo "    results -> $RESULTS_HOST" \
    || echo "    (nothing copied — check the run output above)"

# ── Step 5: summarise ────────────────────────────────────────────────────────
echo ""
echo "=== Scores ==="
python3 - "$RESULTS_HOST" <<'PY'
import json, os, sys
d = sys.argv[1]
if not os.path.isdir(d):
    print("no results dir"); sys.exit()
for fn in sorted(os.listdir(d)):
    if not fn.endswith("_output.json") or fn == "workflow_output.json":
        continue
    try:
        blob = json.load(open(os.path.join(d, fn)))
    except Exception:
        continue
    if isinstance(blob, dict) and "average_score" in blob:
        print(f"  {fn[:-12]:<28} avg = {blob['average_score']}")
        # Only the judge produces a QUALITY score. The other evaluators report
        # counts/seconds (llm calls, tokens, runtime), where "3" is not a bad grade.
        if not fn.startswith("sherlock_judge"):
            continue
        items = blob.get("eval_output_items") or []
        low = [i for i in items if isinstance(i.get("score"), (int, float)) and i["score"] < 6]
        for i in low:
            r = i.get("reasoning")
            if isinstance(r, dict):
                r = r.get("reasoning") or json.dumps(r)
            print(f"      LOW  id={i.get('id')}  score={i.get('score')}  {str(r)[:150]}")
print("""
Profiler outputs (same dir):
  all_requests_profiler_traces.json   per-event trace per question
  standardized_data_all.csv           flat CSV: one row per LLM / tool event
Per-step latency is better read from Phoenix (http://localhost:6007) than from
the eval numbers -- avg_llm_latency is always 0 here by design.""")
PY

echo ""
echo "=== Phase 9b complete ==="
echo "Scores + profiler traces: $RESULTS_HOST"
echo "Traces for these runs also appear in Phoenix under project 'sherlock'."
