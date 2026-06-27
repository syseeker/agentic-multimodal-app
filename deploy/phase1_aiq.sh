#!/usr/bin/env bash
# Phase 1 — deploy the AI-Q deep-research SUB-AGENT (headless, web OFF).
#
# This is a THIN overlay that runs the `aiq-deploy` skill's own documented steps
# (the skill is the source of truth). Every step cites its skill reference.
# It prepares + validates, then STOPS before `up` for the confirmation gate.
#
# Skill: nvidia/skills → aiq-deploy (v-target 2.1.0).  Refs under the skill:
#   locate-or-clone.md · env-and-secrets.md · configs.md · skill-backend.md · validation.md
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AIQ_DIR="$ROOT/external/aiq"
AIQ_REF="${AIQ_REF:-v2.1.0}"                 # match skill version (compat rule in SKILL.md)
CONFIG="${CONFIG:-config_web_default_llamaindex.yml}"  # configs.md default (web off / local KB)

# --- [locate-or-clone.md] clone fresh; do NOT reuse /home/ubuntu/aiq (other project) ---
if [ ! -d "$AIQ_DIR/.git" ]; then
  git clone https://github.com/NVIDIA-AI-Blueprints/aiq.git "$AIQ_DIR"
fi
cd "$AIQ_DIR"
git fetch --depth 1 origin tag "$AIQ_REF" >/dev/null 2>&1 || true
git checkout "$AIQ_REF" >/dev/null 2>&1 || true
grep -m1 '^version' pyproject.toml
for f in pyproject.toml deploy/.env.example deploy/compose/docker-compose.yaml; do
  test -f "$f" && echo "OK  $f" || { echo "MISSING $f"; exit 1; }
done

# --- [env-and-secrets.md] create deploy/.env (no overwrite) ---
[ -f deploy/.env ] || { cp deploy/.env.example deploy/.env; echo "created deploy/.env"; }

# --- [env-and-secrets.md] Normalize Skill Backend Mode + [configs.md] BACKEND_CONFIG ---
python3 - "$CONFIG" <<'PY'
import sys; from pathlib import Path
cfg=sys.argv[1]; path=Path("deploy/.env")
updates={"APP_ENV":"production","AIQ_DEV_ENV":"skill","BACKEND_CONFIG":f"/app/configs/{cfg}"}
defaults={"REQUIRE_AUTH":"false"}
lines=path.read_text().splitlines(); seen=set(); out=[]
for ln in lines:
    s=ln.strip()
    if s and not s.startswith("#") and "=" in s:
        k=s.split("=",1)[0].strip()
        if k in updates: out.append(f"{k}={updates[k]}"); seen.add(k); continue
        if k in defaults: seen.add(k)
    out.append(ln)
for k,v in {**updates,**{k:v for k,v in defaults.items() if k not in seen}}.items():
    if k not in seen: out.append(f"{k}={v}")
path.write_text("\n".join(out)+"\n"); print("normalized skill-backend + BACKEND_CONFIG")
PY

# --- [env-and-secrets.md] presence-only secret check (never prints values) ---
python3 - <<'PY'
from pathlib import Path
p={};
for ln in Path("deploy/.env").read_text().splitlines():
    ln=ln.strip()
    if ln and not ln.startswith("#") and "=" in ln:
        k,v=ln.split("=",1); p[k.strip()]=bool(v.strip())
for k in ["NVIDIA_API_KEY","TAVILY_API_KEY","SERPER_API_KEY","EXA_API_KEY"]:
    print(f"{k}={'SET' if p.get(k) else 'MISSING'}  ", end="")
print()
PY

# --- [SKILL.md Example 1] validate compose (no build) ---
cd deploy/compose
BUILD_TARGET=release docker compose --env-file ../.env -f docker-compose.yaml config --quiet \
  && echo "COMPOSE_CONFIG=VALID"

cat <<'GATE'

──────────────────────────────────────────────────────────────────────────────
STOP — confirmation gate. Prereqs to START the sub-agent (per validation.md):
  • NVIDIA_API_KEY in deploy/.env  (hosted NIMs; required for inference)
  • A host WITHOUT a conflicting AI-Q stack, OR isolate (unique project + ports +
    container_name override) — default names/ports collide with an existing AI-Q.
To start once safe:
  BUILD_TARGET=release docker compose --env-file ../.env -f docker-compose.yaml up -d --build aiq-agent
  curl -sf http://localhost:8000/health && echo backend=healthy   # validation.md
──────────────────────────────────────────────────────────────────────────────
GATE
