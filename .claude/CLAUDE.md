# Agentic Multimodal App — Claude Context

This file is auto-loaded by Claude Code at the start of every session. It gives any new
Claude instance (or new developer) the full context needed to pick up the project without
losing prior knowledge.

---

## What This Project Is

**Sherlock** — a forensic investigation co-worker that ingests multimodal evidence
(photos, audio statements, WhatsApp/chat text) and performs entity recognition,
relationship-graph construction, and paralinguistic sentiment analysis. It returns
court-defensible cited findings with a human-in-the-loop approving each consequential step.

Built entirely on the **NVIDIA software stack**. The goal is a reference implementation
that shows how to evolve a click-through LLM app into an agentic multimodal one.

Two personas:
- **Developer** — assembles Sherlock from NVIDIA components using skills (this file + QUICKSTART_DEVELOPER.md).
- **Investigator (user)** — works a case in the UI; approves each step; reads cited findings (Phase 8+).

Full design: [DESIGN.md](../DESIGN.md) — read it first if you haven't.

---

## CRITICAL OPERATING RULES (non-negotiable)

1. **Skills first, always.** Before implementing or configuring any NVIDIA component,
   read the relevant skill's MD files at `~/skills/skills/<skill-name>/`. Skills are
   written by NVIDIA subject-matter experts. Claude is NOT an NVIDIA package SME.
   Skill files are the authoritative source for commands, images, env vars, and config.

2. **Never hand-roll what a blueprint provides.** If a skill covers it, use the skill.
   Custom code only for items explicitly flagged *proposal* in DESIGN.md.

3. **One phase at a time.** Each phase ends with a confirmation gate. Verify, report,
   get confirmation before moving to the next phase.

4. **Blueprints are cloned at deploy time.** They go into `external/` (gitignored).
   Never vendor, fork, or edit blueprint source.

5. **Secrets stay out of chat and git.** API keys are in `.env` files (gitignored).
   Never print, log, or commit them.

6. **Read the relevant skill files before asking Claude to guess.** The pattern is:
   read skill MD → understand what the skill does → invoke it → verify.

---

## Repository Setup (New Developer or New Instance)

Every new developer or instance MUST do this first:

```bash
# 1. Clone this repo (if not already)
git clone https://github.com/syseeker/agentic-multimodal-app ~/agentic-multimodal-app

# 2. Clone the NVIDIA skills repo (SME knowledge, required alongside this repo)
git clone https://github.com/NVIDIA/skills ~/skills

# 3. Copy and fill the shared env file
cp ~/agentic-multimodal-app/.env.example ~/agentic-multimodal-app/.env
# Edit .env and fill: NVIDIA_API_KEY, NGC_API_KEY, HF_TOKEN
```

Skills are at `~/skills/skills/<skill-name>/`. Read them before each phase.
The exact path may vary — adjust if you cloned skills elsewhere.

---

## Skills Reference (per phase)

Skills live in the NVIDIA skills repo — always `git pull` it first to get the latest,
then read ALL files in the relevant skill directory. Never guess, never rely on memory,
never use summaries. The skills are written by NVIDIA SMEs who know the package internals.

```bash
cd ~/skills && git pull   # always pull latest before starting a phase
```

| Phase | Skill(s) to read (all files in the directory) | Path |
|---|---|---|
| 1 | `aiq-deploy` | `~/skills/skills/aiq-deploy/` |
| 2 | `rag-blueprint` | `~/skills/skills/rag-blueprint/` |
| 3 | `aiq-deploy` (configs ref) + `data-designer` | `~/skills/skills/aiq-deploy/references/configs.md` + `~/skills/skills/data-designer/` |
| 4 | `nemotron-speech` | `~/skills/skills/nemotron-speech/` |
| 5 | `vss-deploy-profile` (lvs profile) | `~/skills/skills/vss-deploy-profile/` |
| 6 | *proposal* (no skill exists) | Follow DESIGN.md §5 only |
| 7 | `aiq-deploy` (configs ref) + `nemotron-policy-generator` | `~/skills/skills/aiq-deploy/references/configs.md` + `~/skills/skills/nemotron-policy-generator/` |
| 8 | *proposal* (no skill exists) | Follow DESIGN.md §4 only |
| 9 | NeMo Agent Toolkit | External docs only |

Do NOT maintain summaries of skill content in this repo. NVIDIA will update skills —
always read the latest from the cloned skills repo.

---

## Current Implementation Status

See `.claude/context/phase-status.md` for the authoritative current status.

Quick summary as of last update:
- Phase 0 (Design): ✅ Complete — DESIGN.md is the signed-off authoritative design.
- Phase 1 (AI-Q backend): Documented (deploy/PHASE1_AIQ.md) but NOT deployed on this instance. Must deploy from scratch.
- Phase 2 (RAG Blueprint): Documented (deploy/PHASE2_RAG.md) but NOT deployed on this instance. Must deploy from scratch.
- Phase 3 (Forensic config): Partially implemented on a previous instance that ran out of disk. Lost. Must redo.
- Phases 4–9: Not started.

**This instance is a clean slate. Start at Phase 1.**

---

## Architecture in One Page

```
UI LAYER (Phase 8 — custom case workbench)
  ↕ REST/SSE
AGENT LAYER
  Lead: AI-Q "Sherlock" (headless, web OFF, HITL plan-approval built-in)
    ├── Sub-agent: vss-agent via MCP (video specialist — Phase 5/7)
    ├── Knowledge: RAG Blueprint as FRAG (text/docs/images — Phase 2)
    └── Tools: Parakeet ASR · MERaLiON paralinguistics · Neo4j+cuGraph · sentiment
NVIDIA COMPONENT LAYER
  AI-Q · RAG Blueprint · VSS · Speech NIMs · LLM/VLM NIMs · NeMo Guardrails
STORAGE LAYER (shared, one of each)
  VECTOR: Elasticsearch (RAG-BP + VSS default; Milvus/cuVS optional for GPU prod)
  GRAPH:  Neo4j (case_id namespaced — VSS video ER + non-video ER)
  RELATIONAL: Postgres (case registry, agent jobs/checkpoints)
  BLOB:   VIOS (video) + object store (image/audio/docs)
```

Key constraints:
- Air-gapped in production: self-hosted NIMs (GB10 / RTX PRO 6000, FP8)
- Dev allowed: hosted NIMs from build.nvidia.com
- Web search: permanently OFF in AI-Q
- Docker project name: `amms` (isolated from any other AI-Q on host)
- AI-Q host port: 8100 (not the default 8000 — avoids collisions)

---

## Environment Variables (root .env)

| Variable | Purpose |
|---|---|
| `NVIDIA_API_KEY` | Hosted NIMs (dev only) |
| `NGC_API_KEY` | Image pulls from nvcr.io |
| `HF_TOKEN` | Gated HuggingFace models (MERaLiON, etc.) |
| `COMPOSE_PROJECT_NAME` | Stack isolation; set to `amms` |
| `AIQ_PORT` | Host port for AI-Q; set to `8100` |

`deploy/propagate_env.sh` distributes shared keys from root `.env` to each component's
`deploy/.env` at deploy time.

---

## Key Files

| File | Purpose |
|---|---|
| `DESIGN.md` | Authoritative architecture — read before anything else |
| `QUICKSTART_DEVELOPER.md` | Phase-by-phase build playbook |
| `.claude/CLAUDE.md` | This file — context for Claude instances |
| `.claude/context/phase-status.md` | Current deployment status per phase |
| `.claude/context/implementation-learnings.md` | Lessons and gotchas — READ before each phase |
| `deploy/PHASE{N}_*.md` | **Authoritative implementation record for each phase.** Contains: what the skill says, actual commands run, what worked, what failed, design decisions, caveats. Future developers must read the relevant PHASE*.md AND the live NVIDIA skill before implementing. |
| `deploy/phase{n}_*.sh` | **Deployable script for each phase.** Updated after each confirmed phase. On-prem (no-internet) deployment runs these scripts directly. |
| `deploy/compose.amms.override.yaml` | Docker Compose isolation overlay (port 8100, container prefixes) |
| `deploy/propagate_env.sh` | Distributes shared secrets to component .env files |

### How PHASE*.md and phase*.sh work together

The `.sh` is the deployable artifact — runs on-prem with no internet (assuming images pulled).
The `.md` is the "why" — skill references, design decisions, lessons learned, verification steps.

When a developer wants to change an implementation (e.g., swap Elasticsearch → Milvus):
1. Read the current `PHASE*.md` to understand the previous approach
2. `git pull` the NVIDIA skills repo — read the relevant skill's latest docs
3. Critique the current approach vs the skill
4. Update the `.sh` with the new approach
5. Update the `.md` to record what changed and why
6. Run and verify
7. Commit both files

---

## How to Continue After a Break

1. Read `.claude/context/phase-status.md` to find the last confirmed phase.
2. Read DESIGN.md §6 for the next phase's goal.
3. `cd ~/skills && git pull` to get the latest NVIDIA SME skills.
4. Read ALL files in the relevant skill directory (table above) before touching anything.
5. Check `.claude/context/implementation-learnings.md` for past gotchas on this project.
6. Deploy / configure following the skill strictly. If the skill and your intuition conflict, the skill wins.
7. Verify at the checkpoint.
8. Update `.claude/context/phase-status.md` and `implementation-learnings.md`.
9. Confirm with the developer before moving to the next phase.
