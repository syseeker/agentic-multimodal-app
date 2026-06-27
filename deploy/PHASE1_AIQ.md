# Phase 1 — AI-Q deep-research sub-agent · proof of skill use

**NVIDIA skill used:** `nvidia/skills → aiq-deploy` (targets AI-Q Blueprint **2.1.0**).
Reference playbooks followed (read in full, not summarized):
`references/locate-or-clone.md`, `env-and-secrets.md`, `configs.md`,
`skill-backend.md`, `validation.md`, plus `SKILL.md` (Example 1: Docker-Compose
Skill backend).

Goal (DESIGN.md Phase 1): AI-Q backend **headless** (no UI), **web search OFF**
(air-gapped → RAG-only).

## Steps executed (each maps to a skill instruction)

| # | Skill ref | Action | Result (evidence) |
|---|---|---|---|
| 1 | `locate-or-clone.md` | Clone AI-Q fresh into `external/aiq` (deviation below) | cloned; required files present (`pyproject.toml`, `deploy/.env.example`, `deploy/compose/docker-compose.yaml`) |
| 2 | `SKILL.md` Version Compatibility | Default branch was **2.0.0** → skill rule says incompatible with 2.1.0; checked out tag **`v2.1.0`** | `pyproject.toml version = "2.1.0"` |
| 3 | `configs.md` | Selected default config `config_web_default_llamaindex.yml` (local KB, no separate RAG; web off) | config present in `configs/` |
| 4 | `env-and-secrets.md` | `cp deploy/.env.example deploy/.env` (no overwrite) | `created deploy/.env` |
| 5 | `env-and-secrets.md` | Presence-only secret check (no values printed) | `NVIDIA_API_KEY=MISSING`; `TAVILY/SERPER/EXA=MISSING` (⇒ web off) |
| 6 | `env-and-secrets.md` + `configs.md` | Normalize skill-backend mode + set `BACKEND_CONFIG` | `APP_ENV=production`, `AIQ_DEV_ENV=skill`, `REQUIRE_AUTH=false`, `BACKEND_CONFIG=/app/configs/config_web_default_llamaindex.yml` |
| 7 | `SKILL.md` Example 1 | `docker compose ... config --quiet` | `COMPOSE_CONFIG=VALID`; services: `postgres`, `aiq-agent`, `frontend` |
| 8 | `SKILL.md` Example 1 | `up -d --build aiq-agent` | **started, then STOPPED before container-create** — see blocker |

Reproducible overlay: [`deploy/phase1_aiq.sh`](phase1_aiq.sh) runs steps 1–7 and stops at the gate.

## Deviation from the skill (justified)
- `locate-or-clone.md` would *reuse* a detected checkout; it would find
  `/home/ubuntu/aiq`. That is the user's **separate project (do-not-touch)**, so we
  **cloned a fresh copy** into `external/aiq` instead. No files in `/home/ubuntu/aiq`
  were read or modified.

## Blocker (why `up` was not completed here)
This shared host **already runs the user's AI-Q stack** (`docker ps`: `aiq-agent`,
`aiq-postgres`, `aiq-blueprint-ui`, "Up 3–4 weeks", working_dir
`/home/ubuntu/aiq/deploy/compose`). The skill's compose uses the **same**
`container_name`s, the **same** default project name (`compose`), and the **same**
ports (8000/3000/5432). Running `up --build` would have **recreated/replaced the
user's running containers**. The build was stopped before any container was created;
the user's stack was verified **intact** afterward.

Second prereq gap: **`NVIDIA_API_KEY` is MISSING** (hosted-NIM inference key).
Per `validation.md`, basic validation can reach infra/API readiness without it, but
no model-backed response can be proven until it's supplied.

## Gate — decision needed before `up`
Pick how to run the Phase-1 sub-agent (then provide `NVIDIA_API_KEY` in `deploy/.env`,
never in chat):
- **A. Reuse the existing running AI-Q** at `localhost:8000` as the sub-agent (it's
  already healthy) — fastest, but couples to the user's other project.
- **B. Isolated instance** on this host — unique compose project + container_name
  override + ports (e.g. 8100/3100/5433). Clean separation; needs the key.
- **C. Defer to the real target host** (air-gapped GPU box) — Phase 1 here is
  "prepared + compose-validated, ready to deploy".

Status: **steps 1–7 done and verified; `up` + `/health` pending the gate decision.**
