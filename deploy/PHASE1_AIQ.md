# Phase 1 — AI-Q Backend · Deployment Proof

**NVIDIA skill followed:** `aiq-deploy` v2.1.0
(`~/skills/skills/aiq-deploy/` — SKILL.md + all references/ read in full before deploying)

**References used (in order):**
`locate-or-clone.md` · `env-and-secrets.md` · `configs.md` · `docker-compose.md` · `validation.md`

**Goal (DESIGN.md Phase 1):** AI-Q backend headless (no UI), web search OFF, isolated in
Docker project `amms`, healthy and producing model-backed responses.

---

## Steps Executed — Skill Reference → Command → Actual Result

| # | Skill ref | Action | Actual result |
|---|---|---|---|
| 1 | `locate-or-clone.md` | `git clone https://github.com/NVIDIA-AI-Blueprints/aiq.git external/aiq && git checkout v2.1.0` | `version = "2.1.0"` in pyproject.toml ✓ |
| 2 | `locate-or-clone.md` | Verify required files: pyproject.toml, deploy/.env.example, deploy/compose/docker-compose.yaml | all present ✓ |
| 3 | `env-and-secrets.md` | `cp deploy/.env.example deploy/.env` (only when missing); `git check-ignore deploy/.env` | gitignored ✓ |
| 4 | `env-and-secrets.md` | `propagate_env.sh` copies NVIDIA_API_KEY, NGC_API_KEY from root `.env` into `external/aiq/deploy/.env` | `NVIDIA_API_KEY=SET`, `NGC_API_KEY=SET` ✓ |
| 5 | `env-and-secrets.md` + `configs.md` | Normalize skill-backend: `APP_ENV=production`, `AIQ_DEV_ENV=skill`, `BACKEND_CONFIG=/app/configs/config_web_default_llamaindex.yml`, `PORT=8100`, `REQUIRE_AUTH=false` | applied ✓ |
| 6 | `docker-compose.md` | Port check: 8100, 5432 | both free ✓ |
| 7 | `docker-compose.md` (SKILL.md Ex1) | `docker compose -p amms ... config --quiet` with override | `COMPOSE_CONFIG=VALID` ✓ |
| 8 | `docker-compose.md` (SKILL.md Ex1) | `BUILD_TARGET=release ... up -d --build aiq-agent` (no UI) | `amms-aiq-agent` up on :8100, `amms-aiq-postgres` healthy ✓ |
| 9 | `validation.md` | `curl http://localhost:8100/health` | `{"status":"healthy"}` ✓ |
| 10 | `validation.md` | `pg_isready -U aiq -d aiq_jobs` + `aiq_checkpoints` | both accepting connections ✓ |
| 11 | `validation.md` | `aiq.py agents` (from `~/skills/skills/aiq-research/scripts/aiq.py`) | `deep_researcher`, `shallow_researcher` listed ✓ |
| 12 | `validation.md` | `aiq.py chat "Confirm web search disabled"` | "web search disabled, only using internal context" ✓ |

**Gate: PASSED** — `AIQ_SERVER_URL=http://localhost:8100` — ready for Phase 2.

---

## Container Inventory (project `amms`)

| Container | Image | Ports | Purpose |
|---|---|---|---|
| `amms-aiq-agent` | `aiq:release` (built from `external/aiq`) | `0.0.0.0:8100→8000/tcp` | AI-Q deep-research backend |
| `amms-aiq-postgres` | `postgres:16-alpine` | `5432/tcp` (internal only) | Job store + checkpoints |

---

## Compose Wiring

```
Project: amms
Files layered (upstream first, overlay last):
  external/aiq/deploy/compose/docker-compose.yaml      ← AI-Q upstream (read-only, never edited)
  deploy/compose.amms.override.yaml                    ← our isolation overlay
  external/aiq/deploy/.env                             ← populated by propagate_env.sh
```

The overlay (`compose.amms.override.yaml`) does three things:
- Renames `aiq-agent` container → `amms-aiq-agent`
- Renames `postgres` container → `amms-aiq-postgres`
- Removes host port from postgres (`ports: !reset []`) — agent reaches it over compose network

**Single source of truth for secrets:** root `.env` → `propagate_env.sh` → each component's `.env`.
Developer fills root `.env` once. No component `.env` is ever filled manually.

---

## Config: `config_web_default_llamaindex.yml`

Web search OFF. Local LlamaIndex/Chroma KB. No external RAG wired yet.
Phase 2 switches to `config_web_frag.yml` (RAG Blueprint as FRAG).

---

## On-Prem Replay (no internet — images must be pre-pulled/saved)

```bash
cd /path/to/agentic-multimodal-app
./deploy/propagate_env.sh external/aiq/deploy/.env
cd external/aiq/deploy/compose
BUILD_TARGET=release docker compose -p amms --env-file ../.env \
  -f docker-compose.yaml \
  -f /path/to/agentic-multimodal-app/deploy/compose.amms.override.yaml \
  up -d aiq-agent          # drop --build to use pre-pulled image
curl -sf http://localhost:8100/health
```

## Note: aiq.py helper path

`validation.md` references `python3 skills/aiq-research/scripts/aiq.py` assuming the
skills repo is a sub-directory of the AI-Q checkout. In this project the skills repo is
separate. Use the full path:
```bash
AIQ_SERVER_URL=http://localhost:8100 python3 ~/skills/skills/aiq-research/scripts/aiq.py agents
```
