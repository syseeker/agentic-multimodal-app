# Phase 1 — AI-Q deep-research sub-agent · proof of skill use ✅

**NVIDIA skill used:** `nvidia/skills → aiq-deploy` (AI-Q Blueprint **2.1.0**).
Reference playbooks followed (read in full): `references/locate-or-clone.md`,
`env-and-secrets.md`, `configs.md`, `skill-backend.md`, `validation.md`, plus
`SKILL.md` (Example 1: Docker-Compose Skill backend).

**Goal (DESIGN.md Phase 1):** AI-Q backend **headless** (no UI), **web search OFF**
(air-gapped → RAG-only), deployed **isolated** into the harmonized `amms` stack.

## Steps executed (each maps to a skill instruction)

| # | Skill ref | Action | Result (evidence) |
|---|---|---|---|
| 1 | `locate-or-clone.md` | Clone AI-Q fresh into `external/aiq` (deviation below) | required files present |
| 2 | `SKILL.md` compat rule | default branch = 2.0.0 (incompatible) → checked out **`v2.1.0`** | `version = "2.1.0"` |
| 3 | `configs.md` | config `config_web_default_llamaindex.yml` (local KB; web off) | present in `configs/` |
| 4 | `env-and-secrets.md` | `cp deploy/.env.example deploy/.env`; **propagate** shared key from project `.env` | `NVIDIA_API_KEY=SET` |
| 5 | `env-and-secrets.md` | presence-only check (no values) | search keys `MISSING` ⇒ **web off** |
| 6 | `env-and-secrets.md`+`configs.md` | normalize: `APP_ENV=production`, `AIQ_DEV_ENV=skill`, `REQUIRE_AUTH=false`, `BACKEND_CONFIG=…llamaindex.yml`, `PORT=8100` | applied |
| 7 | `SKILL.md` Ex1 | `docker compose -p amms … config --quiet` | `COMPOSE_CONFIG=VALID` |
| 8 | `SKILL.md` Ex1 | `up -d --build aiq-agent` (isolated; frontend NOT started) | `amms-aiq-agent` :8100, `amms-aiq-postgres` healthy |
| 9 | `validation.md` | `/health` | **`{"status":"healthy"}`** |
| 10 | `validation.md` | postgres readiness | `aiq_jobs` + `aiq_checkpoints` accepting connections |
| 11 | `validation.md` | async-agent `health` + `agents` (aiq-research helper) | exposes **`deep_researcher`**, **`shallow_researcher`** |
| 12 | `validation.md` | shallow model-backed `chat` | **"Yes, I'm here and ready to help."** (`chat_deepresearcher_agent`) |

Reproducible: [`deploy/phase1_aiq.sh`](phase1_aiq.sh) (uses [`compose.amms.override.yaml`](compose.amms.override.yaml)).

## Isolation (harmonized `amms` stack)
The host already runs the user's AI-Q stack (`aiq-agent`/`aiq-postgres`/`aiq-blueprint-ui`,
ports 8000/3000/5432, project `compose`, dir `/home/ubuntu/aiq`). To avoid any
collision we deploy under a **deploy-time override** (not a blueprint edit):
- project **`amms`**; container `amms-aiq-agent` (host **:8100**); `amms-aiq-postgres`
  (**no host port** — `ports: !reset []`; agent reaches it over the compose network);
  `frontend` not started. The user's stack was verified **untouched**.

## Single project `.env` (per user feedback)
Shared secrets live once in the root [`.env`](../.env.example); `deploy/propagate_env.sh`
distributes them into each component's own `.env` (here `external/aiq/deploy/.env`).
Fill the key once; every component gets it.

## Deviation from the skill (justified)
`locate-or-clone.md` would reuse a detected checkout (it would find `/home/ubuntu/aiq`,
the user's do-not-touch project). We cloned a **fresh** copy into `external/aiq` and
read/modified nothing in `/home/ubuntu/aiq`.

## Dev vs production note
This dev-box run uses **NVIDIA-hosted NIMs** (needs key + internet). The air-gapped
**production** path self-hosts NIMs on the GPU host (no hosted key); that serving is
proven in the serving phase, not here.

**Gate: PASSED** — AI-Q deep-research sub-agent deployed, healthy, and producing
model-backed responses at `AIQ_SERVER_URL=http://localhost:8100`. Ready for Phase 2.
