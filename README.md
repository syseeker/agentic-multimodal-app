# Agentic Multimodal App

A **reference implementation** showing how to turn a *click-through* LLM application
into an **agentic, multimodal** one — built end-to-end on the **NVIDIA software
stack**, by deploying and configuring NVIDIA's blueprints via the skills rather than
hand-rolling them.

It ships with **Sherlock**, an example agent persona: a forensic investigation co-worker
that ingests **photos**, **audio statements**, and **chat text**, then performs
**entity recognition → relationship graph → sentiment / paralinguistic analysis**,
always with a human-in-the-loop for accountability. Sherlock is just a configuration —
swap the tools, prompts, and data to retarget the same skeleton to any domain.

> **Build rule:** never hand-roll what an NVIDIA blueprint provides — deploy/configure
> it via its skill (the SME-optimized path). The agent layer is **AI-Q as the lead
> co-worker**, extended via: **RAG-BP** as the Knowledge Layer (FRAG),
> a **video-specialist sub-agent (`vss-agent`) over MCP**, and speech/graph/sentiment
> as tools. Accountability = AI-Q's **built-in HITL plan-approval**. NeMo Agent Toolkit
> instruments/evaluates the agents (not itself an agent). Custom code only where no
> skill is the SME (flagged as a *proposal*).

---

## Two personas

| Persona | What they do | Where to look |
|---|---|---|
| **Developer** | Build the app fast with NVIDIA skills — deploy/configure blueprints, phase by phase. | [DESIGN.md](DESIGN.md) · [QUICKSTART_DEVELOPER.md](QUICKSTART_DEVELOPER.md) |
| **Investigator** | Work a case with the agent: upload evidence, approve each step, read cited findings + relationship graph. | Case workbench UI at `:8200` (Phase 8) |

---

## Architecture (short)

Four shared layers; the agent *decides* which tools to call — it is not a fixed
pipeline. Full detail + block diagram in **[DESIGN.md](DESIGN.md)**.

```
UI — Svelte case workbench (:8200): case list · chat · entity graph · evidence · paralinguistics
  │
LEAD AGENT — AI-Q "Sherlock" (:8100): plan → HITL approval → execute → cite
  │   Knowledge Layer (text/docs/images): RAG Blueprint via FRAG (:8081)
  │   Graph tools: Sherlock MCP server (:9901) → Neo4j (:7687)
  │   Video sub-agent: vss-agent via MCP (Phase 5/7, GPU-gated)
  │   Tools: Parakeet ASR · MERaLiON paralinguistics · Neo4j+cuGraph · sentiment
  │   (NeMo Agent Toolkit instruments/evaluates — not itself an agent; web search OFF)
  ▼
NVIDIA COMPONENTS — AI-Q · RAG Blueprint · VSS · speech/LLM/VLM NIMs · NeMo Guardrails
  ▼
STORAGE — Elasticsearch (vector) · Neo4j (graph) · Postgres (agent state) · SeaweedFS (blob)
```

---

## Build phases

| Phase | What ships | Status |
|---|---|---|
| 0 | Architecture design (DESIGN.md) | ✅ |
| 1 | AI-Q agent backend (FRAG mode, :8100) | ✅ |
| 2 | RAG Blueprint knowledge layer (:8081 / :8082) | ✅ |
| 3 | Synthetic forensic case data (20 cases, ingested) | ✅ |
| 4 | Audio pipeline (Parakeet ASR → transcripts → RAG) | ✅ |
| 5 | VSS video specialist (GPU-gated; shared ES + Redis) | ✅ partial |
| 6 | Entity recognition → Neo4j graph | ✅ |
| 7 | AI-Q extensions: Sherlock MCP + forensic prompts | ✅ |
| 8 | Svelte case workbench UI with HITL | ✅ |
| 9 | Observability · Evaluation · Profiling · Guardrails | 🔄 in progress |

Each phase ends with a verification gate and a `deploy/PHASE{N}_*.md` proof file.
See [`.claude/context/phase-status.md`](.claude/context/phase-status.md) for the
authoritative current state.

---

## Quick start (developer)

```bash
# 1. Clone this repo
git clone https://github.com/syseeker/agentic-multimodal-app
cd agentic-multimodal-app

# 2. Clone the NVIDIA skills repo (SME knowledge, required alongside this repo)
git clone https://github.com/NVIDIA/skills ~/skills

# 3. Fill in API keys
cp .env.example .env
# Edit .env — NVIDIA_API_KEY, NGC_API_KEY, HF_TOKEN

# 4. Start all services (requires Phases 1-8 deployed; clones blueprints into external/)
bash deploy/start_all.sh
```

Open `http://localhost:8200` — the investigator workbench.

See [QUICKSTART_DEVELOPER.md](QUICKSTART_DEVELOPER.md) for the full phase-by-phase
build guide.

---

## The method (why this is faster)

Install the NVIDIA skills into your coding agent and let each skill
**deploy/configure its blueprint** — the SME-optimized path — instead of writing
glue. The build proceeds in phases, each driven by a skill, each with a confirmation
gate. See **[QUICKSTART_DEVELOPER.md](QUICKSTART_DEVELOPER.md)**.

---

## License

Apache-2.0. Model weights (Qwen, MERaLiON, Nemotron, etc.) carry their own licenses —
review before commercial use.
