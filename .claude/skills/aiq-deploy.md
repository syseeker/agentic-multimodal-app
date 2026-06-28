# SME Summary: aiq-deploy skill

Source: `~/skills/skills/aiq-deploy/`
Skill version: 2.1.0 — compatible with AI-Q Blueprint 2.1.0+
Always re-read the full skill files before implementing; this summary is a quick reference.

---

## What This Skill Does

Installs, deploys, validates, troubleshoots, and stops NVIDIA AI-Q Blueprint infrastructure.
It routes you to the right deployment mode and hands off to `aiq-research` when the backend is ready.

**For this project:** Use "skill backend" deployment mode — backend-only, no browser UI.

---

## Deployment Modes

| Mode | What it is | Use for this project? |
|---|---|---|
| skill backend | Backend-only service for `aiq-research`, no UI | **YES — this is our mode** |
| CLI | Interactive terminal AI-Q | No |
| UI | Browser AI-Q with frontend | No (we build our own UI in Phase 8) |
| Custom | Existing AI-Q config / advanced | For config customization in Phase 3/7 |

---

## Prerequisites (check before deploying)

- Git available
- Docker Compose v2 (we use Docker, not Python/Node/Helm)
- Network access to GitHub and NVIDIA-hosted endpoints (dev mode)
- Credentials in `deploy/.env` (never in chat, never in git)
  - `NVIDIA_API_KEY` — for hosted NIMs (dev)
  - `NGC_API_KEY` — for image pulls from nvcr.io
- Sufficient disk (AI-Q image ~5-8 GB)

---

## Key Config: deploy/.env

The skill expects secrets in `deploy/.env`. Our project uses a root `.env` that gets
propagated via `deploy/propagate_env.sh`. The relevant vars for AI-Q are:
- `NVIDIA_API_KEY`
- `NGC_API_KEY`
- `COMPOSE_PROJECT_NAME=amms` (project isolation)
- `AIQ_PORT=8100` (not default 8000)

---

## Version Compatibility Rule

- Skill 2.1.0 → Blueprint 2.1.0+
- Major versions must match
- Minor version of skill must be ≤ blueprint minor version
- Patch version irrelevant

---

## What the Skill Reference Files Cover

Read these from `~/skills/skills/aiq-deploy/references/` before each sub-task:

| File | When to read |
|---|---|
| `locate-or-clone.md` | First deploy — cloning AI-Q repo |
| `env-and-secrets.md` | Setting up credentials |
| `configs.md` | Choosing / customizing AI-Q config (Phase 3, 7) |
| `skill-backend.md` | Skill backend deployment (our mode) |
| `docker-compose.md` | Docker Compose deployment details |
| `validation.md` | Health checks and verification |
| `troubleshooting.md` | Diagnosing failures |
| `shutdown.md` | Clean shutdown and restart |
| `frag.md` | Wiring RAG Blueprint as FRAG (Phase 2) |

---

## Verification Endpoints

```bash
# Basic health
curl -sf http://localhost:8100/health
# Expected: {"status":"healthy"}

# List available agents
curl -sf http://localhost:8100/v1/agents
# Expected: should include deep_researcher, shallow_researcher

# Postgres readiness (inside container)
docker exec amms-aiq-postgres psql -U postgres -c "\dt" | grep -E "aiq_jobs|aiq_checkpoints"
```

---

## Common Failure Modes

| Symptom | Likely cause | Fix |
|---|---|---|
| Port already in use | Another AI-Q or service on 8100 | `lsof -i :8100`, stop the process |
| Missing credentials | `.env` not filled | Check without printing: `grep -c NVIDIA_API_KEY deploy/.env` |
| Backend not compatible with aiq-research | Wrong blueprint version | Check image tag matches v2.1.0 |
| Docker cleanup needed | Stale containers from prev attempt | Ask user before `docker compose down -v` (destructive) |

---

## Project-Specific Notes for This Repo

- Clone AI-Q to `external/aiq/` (gitignored via `.gitignore`).
- Use `deploy/compose.amms.override.yaml` to:
  - Prefix container names with `amms-`
  - Map AI-Q to host port `8100`
  - Avoid collisions with other stacks
- Bring up **only the `aiq-agent` service** (not full stack including UI).
- AI-Q config used: `config_web_default_llamaindex.yml` (Phase 1), then `config_web_frag.yml` (Phase 2).
- Both configs have web search OFF — mandatory for air-gapped target.

---

## FRAG Wiring (Phase 2 — done via this skill)

Read `~/skills/skills/aiq-deploy/references/frag.md` for exact steps.

In brief:
1. RAG Blueprint must be deployed first (Phase 2).
2. Set `BACKEND_CONFIG=config_web_frag.yml` in AI-Q env.
3. Set `RAG_SERVER_URL=http://rag-server:8081` (Docker service name).
4. Set `RAG_INGEST_URL=http://ingestor-server:8082`.
5. Connect AI-Q container to `nvidia-rag` Docker network.
6. Restart AI-Q.
7. Verify: AI-Q answers a question citing an ingested document.

---

## Phase 3/7 Config Customization

Read `~/skills/skills/aiq-deploy/references/configs.md`.
- Do NOT edit AI-Q's checked-in config files in `external/aiq/`.
- Create overlay config files in our repo's `deploy/` directory.
- Reference them via environment variable override when bringing up the container.
- Forensic prompts = a separate config that sets the system prompt / persona.
