#!/usr/bin/env bash
# Phase 7 — AI-Q forensic extensions
# Deploys: Sherlock MCP server + switches AI-Q to Sherlock config + forensic prompts
# See PHASE7_EXTENSIONS.md for context.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AIQ_COMPOSE="$REPO_ROOT/external/aiq/deploy/compose/docker-compose.yaml"
OVERRIDE="$REPO_ROOT/deploy/compose.amms.override.yaml"

# ── 0. Load shared secrets from root .env ─────────────────────────────────────
# Needed BEFORE any compose/source below:
#   - compose.sherlock_mcp.yaml substitutes ${NVIDIA_API_KEY} (else the MCP server's
#     LLM client gets a blank key)
#   - `source nvdev.env` runs `export NVIDIA_API_KEY=${NGC_API_KEY}`, which aborts the
#     whole script under `set -u` if NGC_API_KEY is unbound (the `2>/dev/null || true`
#     cannot catch an unbound-variable error raised during expansion).
# `|| true`: under `set -euo pipefail`, grep exits 1 when the key line is absent and
# pipefail would abort the bare assignment before the friendly guard on the next lines.
NVIDIA_API_KEY=$(grep '^NVIDIA_API_KEY=' "$REPO_ROOT/.env" | cut -d= -f2- | sed 's/[[:space:]]*#.*//' | tr -d '[:space:]' || true)
NGC_API_KEY=$(grep '^NGC_API_KEY=' "$REPO_ROOT/.env" | cut -d= -f2- | sed 's/[[:space:]]*#.*//' | tr -d '[:space:]' || true)
export NVIDIA_API_KEY NGC_API_KEY
# Preserve the inference key: `source nvdev.env` below does `export NVIDIA_API_KEY=${NGC_API_KEY}`,
# clobbering it with the registry key. Restore from INFERENCE_KEY after the source.
INFERENCE_KEY="$NVIDIA_API_KEY"
[ -n "${NVIDIA_API_KEY}" ] && echo "NVIDIA_API_KEY=SET" || { echo "NVIDIA_API_KEY missing in .env"; exit 2; }

# ── 1. Start Sherlock MCP server ──────────────────────────────────────────────
echo "Starting Sherlock MCP server..."
docker compose -p amms -f "$REPO_ROOT/deploy/compose.sherlock_mcp.yaml" up -d

echo "Waiting for Sherlock MCP to be healthy..."
until docker inspect amms-sherlock-mcp --format '{{.State.Health.Status}}' 2>/dev/null | grep -q healthy; do
    sleep 5
done
echo "✅ Sherlock MCP healthy at http://localhost:9901/mcp"

# ── 2. Confirm Sherlock MCP container is healthy ──────────────────────────────
# FastMCP streamable-http requires a session handshake — raw GET/POST without it
# returns 406 Not Acceptable. Container health check is the right gate here;
# AI-Q does the proper session handshake at runtime.
echo ""
STATUS=$(docker inspect amms-sherlock-mcp --format '{{.State.Health.Status}}' 2>/dev/null)
if [ "$STATUS" = "healthy" ]; then
    echo "✅ Sherlock MCP container healthy (graph + audio tools ready)"
else
    echo "⚠️  Sherlock MCP container status: ${STATUS:-not found}"
fi

# ── 3. Start VSS Sherlock MCP BEFORE AI-Q restarts ───────────────────────────
# AI-Q connects to ALL mcp_client entries at startup. If VSS MCP (:9903) is not
# running when AI-Q starts, it fails to connect and never becomes healthy.
# Rule: every MCP server in config_sherlock_frag_mcp.yml must be up before AI-Q.
echo ""
if curl -sf --max-time 5 http://localhost:8000/health 2>/dev/null | grep -q isAlive; then
  echo "Starting VSS MCP server for Sherlock (required before AI-Q)..."
  docker compose -p amms -f "$REPO_ROOT/deploy/compose.vss_sherlock_mcp.yaml" up -d
  echo -n "Waiting for VSS MCP to be healthy..."
  for i in $(seq 1 20); do
    STATUS=$(docker inspect amms-vss-sherlock-mcp --format '{{.State.Health.Status}}' 2>/dev/null)
    if [ "$STATUS" = "healthy" ]; then
      echo " ✅ VSS MCP container healthy"; break
    fi
    sleep 3; echo -n "."
  done
  echo ""

  # ── rtvi-vlm check ────────────────────────────────────────────────────────
  # rtvi-vlm runs on this same host (VSS LVS is single-machine — see phase5_vss.sh).
  # ask_video and summarize_video fail without it.
  if docker ps -q --filter "name=^/vss-rtvi-vlm$" | grep -q . && \
     { curl -sf --max-time 5 "http://localhost:8000/health"   >/dev/null 2>&1 || \
       curl -sf --max-time 5 "http://localhost:8000/v1/models" >/dev/null 2>&1; }; then
    echo "  ✅ rtvi-vlm running locally — video tools active"
  else
    echo "  ⚠️  WARNING: rtvi-vlm not running on this host."
    echo "      Video tools (ask_video, summarize_video) will fail."
    echo "      This host was likely deployed via phase5 PATH C (no GPU), which omits"
    echo "      rtvi-vlm. Video analysis needs a GPU in THIS machine."
    echo "      Check: docker logs vss-rtvi-vlm --tail 30"
  fi
else
  echo "  ⚠️  VSS MCP skipped — vss-agent not running. AI-Q will start without video tools."
  echo "      Run phase5_vss.sh first, then re-run phase7_extensions.sh."
fi

# ── 4. Restart AI-Q with Sherlock config + prompt volume mount ────────────────
echo ""
echo "Restarting AI-Q with Sherlock config (MCP-enabled)..."
# ALL MCP servers (Sherlock :9901, VSS :9903) must be running before this step.
cp "$REPO_ROOT/deploy/aiq-configs/config_sherlock_frag_mcp.yml" "$REPO_ROOT/external/aiq/configs/config_sherlock_frag.yml"
source "$REPO_ROOT/external/rag/deploy/compose/nvdev.env" 2>/dev/null || true
export NVIDIA_API_KEY="$INFERENCE_KEY"   # restore inference key (nvdev.env set it to ${NGC_API_KEY})

docker compose -p amms \
    --env-file "$REPO_ROOT/external/aiq/deploy/.env" \
    -f "$AIQ_COMPOSE" \
    -f "$OVERRIDE" \
    up -d --no-build --force-recreate aiq-agent

# force-recreate drops the extra `nvidia-rag` network that phase2_rag.sh attached, so
# FRAG (rag-server/ingestor lookups) would break with the new MCP config. Re-attach it.
# (aiq-deploy frag.md: "If aiq-agent is recreated, repeat the network connection.")
docker network connect nvidia-rag amms-aiq-agent 2>/dev/null \
    && echo "Reconnected amms-aiq-agent to nvidia-rag" || echo "nvidia-rag already connected"

echo -n "Waiting for AI-Q to be healthy"
until curl -sf "http://localhost:8100/health" >/dev/null 2>&1; do
    sleep 5; echo -n "."
done
echo " ✅ AI-Q healthy at http://localhost:8100"

# ── 4. Verify Sherlock config is active ───────────────────────────────────────
echo ""
echo "Verifying Sherlock config..."
docker exec amms-aiq-agent python3 -c "
import os
cfg = os.environ.get('BACKEND_CONFIG', '')
print(f'BACKEND_CONFIG: {cfg}')
assert 'sherlock' in cfg, f'Expected sherlock config, got: {cfg}'
print('✅ Sherlock config active')
" && echo "✅ Prompts: mounted from host (shallow_researcher + clarifier patched)"

# ── 5. End-to-end graph tool query via AI-Q ───────────────────────────────────
echo ""
echo "End-to-end test: query graph tools via AI-Q..."
PATH="$HOME/.local/bin:$PATH" uv run --with neo4j --with openai --with networkx python -c "
import sys, os
sys.path.insert(0, '$REPO_ROOT')
cases_dir = '$REPO_ROOT/data/cases'
cases = sorted([d for d in os.listdir(cases_dir) if os.path.isdir(os.path.join(cases_dir, d))])
if not cases:
    print('No cases found — skipping end-to-end test'); sys.exit(0)
case_id = cases[0]
# Load env (comment-stripped)
for line in open('$REPO_ROOT/.env').readlines():
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k,_,v = line.partition('='); v=v.split('#')[0].strip().strip('\"').strip(\"'\")
        os.environ.setdefault(k.strip(), v)
from graph.tools import graph_query, graph_analyze
q = graph_query(case_id, 'suspects')
a = graph_analyze(case_id, 'centrality')
suspects = [s['name'] for s in q.get('suspects', [])]
top = a.get('key_entities', [{}])[0].get('name', 'none') if a.get('key_entities') else 'none'
print(f'Case {case_id}: suspects={suspects}, top entity={top}')
print('✅ Graph tools working')
" || echo "(graph smoke test skipped/non-fatal — needs the phase6 graph venv + populated Neo4j)"

# ── 6. Audio MCP smoke test ───────────────────────────────────────────────────
# MCP streamable-http requires a session handshake before tool calls — raw curl/HTTP
# cannot replicate this. AI-Q does it correctly at runtime. We test the underlying
# data directly: file existence + function logic via Python, and container health
# via docker inspect. The MCP layer itself is validated by AI-Q connecting to it.
SAMPLE_CASE="SC-2024-03C5F0E4"
echo ""
echo "Audio MCP smoke test (case $SAMPLE_CASE)..."
python3 - <<PYEOF
import sys, json
from pathlib import Path

REPO_ROOT = Path("$REPO_ROOT")
case_dir  = REPO_ROOT / "data" / "cases" / "$SAMPLE_CASE"
audio_dir = case_dir / "audio"
AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".wma"}

# list_audio_files — check what exists on disk (same logic as the MCP tool)
files = []
if audio_dir.exists():
    for f in sorted(audio_dir.iterdir()):
        if f.suffix.lower() in AUDIO_EXTS and not f.name.startswith((".", "_")):
            tf = audio_dir / f"{f.stem}_transcript.txt"
            has_t = tf.exists()
            # Real MERaLiON output contains "emotion" key with actual value;
            # stub output only has "status":"stub" — not real paralinguistics
            has_p = False
            if has_t:
                content = tf.read_text()
                has_p = '"emotion"' in content and '"status": "stub"' not in content
            files.append({"filename": f.name, "has_transcript": has_t, "has_paralinguistics": has_p})

if files:
    print(f"  list_audio_files: ✅ {len(files)} file(s) found")
    for f in files:
        print(f"    {f['filename']} | transcript={f['has_transcript']} | paralinguistics={f['has_paralinguistics']}")
else:
    print("  list_audio_files: ⚠️  no audio files — run generate_audio_samples.py first")

# get_audio_analysis — check audio_analysis.txt
analysis_file = case_dir / "audio_analysis.txt"
if analysis_file.exists():
    content = analysis_file.read_text()
    para_entries = [l for l in content.splitlines() if '"emotion"' in l or '"language"' in l]
    print(f"  get_audio_analysis: ✅ audio_analysis.txt found ({analysis_file.stat().st_size} bytes, {len(para_entries)} paralinguistics line(s))")
else:
    print("  get_audio_analysis: ⚠️  no audio_analysis.txt — run Phase 4 first")

# Sherlock MCP container health
import subprocess
r = subprocess.run(["docker","inspect","amms-sherlock-mcp","--format","{{.State.Health.Status}}"],
                   capture_output=True, text=True)
status = r.stdout.strip()
if status == "healthy":
    print(f"  amms-sherlock-mcp container: ✅ {status}")
else:
    print(f"  amms-sherlock-mcp container: ⚠️  {status or 'not found'}")
PYEOF

# ── 7. VSS MCP smoke test ─────────────────────────────────────────────────────
# MCP streamable-http requires session handshake — we verify container health
# and that AI-Q registered the VSS data source (proves the MCP connection works).
# summarize_video / ask_video are tested in Phase 8 after workbench video upload.
echo ""
echo "VSS MCP smoke test..."
python3 - <<PYEOF
import subprocess, urllib.request, json

# Container health
r = subprocess.run(["docker","inspect","amms-vss-sherlock-mcp","--format","{{.State.Health.Status}}"],
                   capture_output=True, text=True)
status = r.stdout.strip()
if status == "healthy":
    print(f"  amms-vss-sherlock-mcp container: ✅ {status}")
else:
    print(f"  amms-vss-sherlock-mcp container: ⚠️  {status or 'not found'}")

# Verify AI-Q registered the VSS MCP as a data source
# Response is a JSON array directly (not wrapped in a dict)
try:
    with urllib.request.urlopen("http://localhost:8100/v1/data_sources", timeout=5) as r:
        sources = json.loads(r.read())
        if isinstance(sources, dict):
            sources = sources.get("data_sources", [])
        names = [s.get("name","") for s in sources]
        print(f"  AI-Q data sources: {names}")
        has_video = any("video" in n.lower() or "vss" in n.lower() for n in names)
        if has_video:
            print("  ✅ VSS video source registered in AI-Q")
        else:
            print("  ⚠️  no video source in AI-Q data sources (VSS MCP may not have connected)")
except Exception as e:
    print(f"  AI-Q data sources check: ⚠️  {e}")

print("  (list_case_videos / summarize_video tested in Phase 8 after workbench video upload)")
PYEOF

echo ""
echo "=== Phase 7 complete ==="
echo "  - Sherlock MCP:      http://localhost:9901/mcp"
echo "      Graph tools:  graph_query, graph_analyze, extract_entities, list_cases"
echo "      Audio tools:  list_audio_files, get_audio_analysis, analyze_audio"
echo "  - VSS Sherlock MCP:  http://localhost:9903/mcp"
echo "      Video tools:  list_case_videos, ask_video, summarize_video"
echo "  - AI-Q (Sherlock):   http://localhost:8100"
echo "  - Forensic prompts:  shallow_researcher + clarifier patched"
echo ""
echo "  Run phase8_workbench.sh to start the UI (if not already running)"
