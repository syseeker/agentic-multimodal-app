#!/usr/bin/env bash
# Phase 1 — deploy the AI-Q deep-research SUB-AGENT (headless, web OFF), isolated
# into the harmonized "amms" stack so it never collides with another AI-Q on the host.
#
# Runs the `aiq-deploy` skill's own documented steps (skill = source of truth);
# each step cites its skill reference. Idempotent.
#
# Skill: nvidia/skills → aiq-deploy (target 2.1.0). Refs:
#   locate-or-clone.md · env-and-secrets.md · configs.md · skill-backend.md · validation.md
# Prereqs: docker + compose; project .env filled (NVIDIA_API_KEY) — see .env.example.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AIQ_DIR="$ROOT/external/aiq"
OVERRIDE="$ROOT/deploy/compose.amms.override.yaml"
AIQ_REF="${AIQ_REF:-v2.1.0}"
CONFIG="${CONFIG:-config_web_default_llamaindex.yml}"   # web off / local KB (configs.md)
PROJECT="${COMPOSE_PROJECT_NAME:-amms}"
export PORT="${AIQ_PORT:-8100}"

# 1. [locate-or-clone.md] clone fresh — do NOT reuse /home/ubuntu/aiq (other project)
[ -d "$AIQ_DIR/.git" ] || git clone https://github.com/NVIDIA-AI-Blueprints/aiq.git "$AIQ_DIR"
cd "$AIQ_DIR"
git fetch --depth 1 origin tag "$AIQ_REF" >/dev/null 2>&1 || true
git checkout "$AIQ_REF" >/dev/null 2>&1 || true
grep -m1 '^version' pyproject.toml   # expect 2.1.0 (SKILL.md compat rule)

# 2. [env-and-secrets.md] create deploy/.env, then propagate shared keys from the
#    single project .env (one key, many components)
[ -f deploy/.env ] || cp deploy/.env.example deploy/.env
"$ROOT/deploy/propagate_env.sh" "$AIQ_DIR/deploy/.env"

# 3. [env-and-secrets.md] normalize skill-backend + [configs.md] BACKEND_CONFIG + PORT
python3 - "$CONFIG" "$PORT" <<'PY'
import sys; from pathlib import Path
cfg,port=sys.argv[1],sys.argv[2]; path=Path("deploy/.env")
updates={"APP_ENV":"production","AIQ_DEV_ENV":"skill",
         "BACKEND_CONFIG":f"/app/configs/{cfg}","PORT":port}
defaults={"REQUIRE_AUTH":"false"}
lines=path.read_text().splitlines(); seen=set(); out=[]
for ln in lines:
    s=ln.strip()
    if s and not s.startswith("#") and "=" in s:
        k=s.split("=",1)[0].strip()
        if k in updates: out.append(f"{k}={updates[k]}"); seen.add(k); continue
        if k in defaults: seen.add(k)
    out.append(ln)
for k,v in {**updates, **{k:v for k,v in defaults.items() if k not in seen}}.items():
    if k not in seen: out.append(f"{k}={v}")
path.write_text("\n".join(out)+"\n"); print("normalized skill-backend + BACKEND_CONFIG + PORT")
PY

# 4. presence check (no values printed); require NVIDIA_API_KEY to start
grep -q '^NVIDIA_API_KEY=.\+' deploy/.env && echo "NVIDIA_API_KEY=SET" || {
  echo "NVIDIA_API_KEY MISSING — fill project .env then re-run (env-and-secrets.md)"; exit 2; }

# 5. [SKILL.md Ex1] validate, then up ONLY aiq-agent (frontend stays down), isolated
cd deploy/compose
COMPOSE="docker compose -p $PROJECT --env-file ../.env -f docker-compose.yaml -f $OVERRIDE"
BUILD_TARGET=release $COMPOSE config --quiet && echo "COMPOSE_CONFIG=VALID"
BUILD_TARGET=release $COMPOSE up -d --build aiq-agent

# 6. [validation.md] health + postgres readiness
curl --retry 30 --retry-delay 3 --retry-all-errors -sf "http://localhost:${PORT}/health" >/dev/null \
  && echo "backend=healthy http://localhost:${PORT}" || { echo "backend NOT healthy"; exit 3; }
docker exec "${PROJECT}-aiq-postgres" pg_isready -U aiq -d aiq_jobs
echo "AIQ_SERVER_URL=http://localhost:${PORT}   # hand off to aiq-research / supervisor"
