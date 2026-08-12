#!/usr/bin/env bash
# Apply the AI-Q asyncio ContextVar patch to the amms-aiq-agent container.
#
# Bug: nat/runtime/runner.py resets ContextVars in __aexit__ and in finally blocks.
# When an MCP tool result streams back on a DIFFERENT asyncio task than the one that
# set the token, ContextVar.reset() raises `ValueError: <Token> was created in a
# different Context`. That exception propagates out of the finally block and the MCP
# tool result is silently dropped -- the UI shows an empty answer ("No response
# received"). Wrapping each reset in try/except ValueError makes the reset best-effort.
#
# This edit lives in the CONTAINER'S WRITABLE LAYER and is LOST on every recreate
# (docker compose up --force-recreate, image change, phase1/start_all re-run).
# Re-run this script after ANY amms-aiq-agent recreate:
#   bash deploy/patch_aiq_runner.sh
#
# Idempotent: re-running on an already-patched container is a no-op.
#
# See .claude/context/phase-status.md -> "AI-Q asyncio patch"
#     .claude/context/implementation-learnings.md -> "AI-Q asyncio context error with VSS MCP"
set -euo pipefail

echo "=== Patching amms-aiq-agent (nat/runtime/runner.py ContextVar resets) ==="

CTR="amms-aiq-agent"
if ! docker ps -q --filter "name=^/${CTR}$" | grep -q .; then
    echo "ERROR: ${CTR} is not running. Start it first (deploy/start_all.sh)."
    exit 1
fi

# NOTE: -i is REQUIRED. Without it docker does not forward stdin, so `python3 -`
# reads EOF, runs an empty program and exits 0 -- the patch silently no-ops while
# this script still reports success. (Same trap as patch_vss_rtvi_vlm.sh.)
docker exec -i "$CTR" python3 - <<'PYEOF'
import re
import sys

PATH = '/app/.venv/lib/python3.13/site-packages/nat/runtime/runner.py'

with open(PATH) as f:
    lines = f.readlines()

if any('except ValueError' in ln for ln in lines):
    print('  already patched -- no changes made')
    sys.exit(0)

# Match a bare `<something>.reset(<token>)` statement and wrap it:
#     try:
#         <stmt>
#     except ValueError:
#         pass   # token created in a different Context (cross-task MCP streaming)
RESET = re.compile(r'^(\s*)([A-Za-z_][\w.]*\.reset\([^)]*\))\s*$')

out, patched = [], 0
for ln in lines:
    m = RESET.match(ln.rstrip('\n'))
    if not m:
        out.append(ln)
        continue
    indent, stmt = m.group(1), m.group(2)
    out.append(f'{indent}try:\n')
    out.append(f'{indent}    {stmt}\n')
    out.append(f'{indent}except ValueError:\n')
    out.append(f'{indent}    pass  # token created in a different Context (cross-task MCP streaming)\n')
    patched += 1

if not patched:
    print('  ERROR: no .reset() call sites matched -- runner.py layout changed?')
    sys.exit(1)

src = ''.join(out)
compile(src, PATH, 'exec')          # refuse to write syntactically broken source
with open(PATH, 'w') as f:
    f.write(src)
print(f'  wrapped {patched} ContextVar reset call site(s)')
PYEOF

echo "Restarting ${CTR} to load the patched module..."
docker restart "$CTR" >/dev/null

echo -n "Waiting for AI-Q health"
for _ in $(seq 1 40); do
    if curl -sf http://localhost:8100/health >/dev/null 2>&1; then echo " ok"; break; fi
    sleep 3; echo -n "."
done

# A restart (unlike a recreate) keeps networks, but re-attach defensively --
# FRAG breaks silently if amms-aiq-agent is off the nvidia-rag network.
docker network connect nvidia-rag "$CTR" 2>/dev/null && echo "  re-attached nvidia-rag" || true

echo "=== Done ==="
