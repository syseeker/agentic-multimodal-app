# Agentic Multimodal App

A **reference implementation / developer enablement PoC** showing how to turn a *click-through* LLM application
into an **agentic, multimodal** one — built end-to-end on the **NVIDIA software
stack**, by deploying and configuring NVIDIA's blueprints via the skills rather than
hand-rolling them.

It ships with **Sherlock**, an example agent persona: a forensic investigation co-worker
that ingests **photos**, **audio statements**, and **chat text**, then performs
**entity recognition → relationship graph → sentiment / paralinguistic analysis**,
with human review as the accountability goal. The current UI approval is follow-up
chat, not a server-enforced tool gate; images are stored/viewed without analysis.
Sherlock is just a configuration —
swap the tools, prompts, and data to retarget the same skeleton to any domain.

> **Build rule:** never hand-roll what an NVIDIA blueprint provides — deploy/configure
> it via its skill (the SME-optimized path). The agent layer is **AI-Q as the lead
> co-worker**, extended via: **RAG-BP** as the Knowledge Layer (FRAG),
> **custom video tools over MCP → VSS HTTP APIs**, and speech/graph/sentiment
> as tools. Accountability remains the design goal: built-in approval is disabled
> and the safety policy is drafted. NeMo Agent Toolkit provides runtime/integration
> and instruments/evaluates the workflow (not itself an agent). Custom code only where no
> skill is the SME (flagged as a *proposal*).

---

## Two personas

| Persona | What they do | Where to look |
|---|---|---|
| **Developer** | Build the app fast with NVIDIA skills — deploy/configure blueprints, phase by phase, or adopt selected modules. Then measure it. | [DESIGN.md](DESIGN.md) · [QUICKSTART_DEVELOPER.md](QUICKSTART_DEVELOPER.md) · [QUICKSTART_BENCHMARK.md](QUICKSTART_BENCHMARK.md) |
| **Investigator** | Work a case with the agent: upload evidence, approve each step, read cited findings + relationship graph. | [QUICKSTART_INVESTIGATOR.md](QUICKSTART_INVESTIGATOR.md) |

---

## Architecture (short)

Four shared layers; the agent *decides* which tools to call — it is not a fixed
pipeline. Full detail + block diagram in **[DESIGN.md](DESIGN.md)**.

```
UI — Svelte case workbench (:8200): case list · chat · entity graph · evidence · paralinguistics
  │
LEAD AGENT — AI-Q "Sherlock" (:8100): shallow tool loop → synthesize → cite; UI approval feedback
  │   Knowledge Layer (text/docs/transcripts): RAG Blueprint via FRAG (:8081)
  │   Graph tools: Sherlock MCP server (:9901) → Neo4j (:7687)
  │   Video tools: custom MCP :9903 → RT-VLM HTTP (LVS/vss-agent fallbacks)
  │   Tools: Parakeet ASR · MERaLiON paralinguistics · Neo4j+NetworkX CPU · sentiment
  │   (NeMo Agent Toolkit instruments/evaluates — not itself an agent; web search OFF)
  ▼
NVIDIA COMPONENTS — AI-Q · RAG Blueprint · VSS · speech/LLM/VLM NIMs · NeMo Guardrails (planned)
  ▼
STORAGE — Elasticsearch (vector) · Neo4j (graph) · Postgres (agent state) · SeaweedFS (RAG objects) · local case files / VIOS
```

---

## Build phases

The phase table preserves build history; check the target host for current readiness.

| Phase | What ships | Status |
|---|---|---|
| 0 | Architecture design (DESIGN.md) | ✅ |
| 1 | AI-Q agent backend (FRAG mode, :8100) | ✅ |
| 2 | RAG Blueprint knowledge layer (:8081 / :8082) | ✅ |
| 3 | Synthetic forensic case data (21 case folders in reviewed tree; verify ingestion) | ✅ |
| 4 | Audio pipeline (Parakeet ASR → transcripts → RAG) | ✅ |
| 5 | VSS video specialist (GPU-gated; shared ES + Redis) | ✅ partial |
| 6 | Entity recognition → Neo4j graph | ✅ |
| 7 | AI-Q extensions: Sherlock MCP + forensic prompts | ✅ |
| 8 | Svelte case workbench UI with approval feedback | ✅ |
| 9 | Observability · Evaluation · Profiling · Guardrails | 🔄 in progress |

Each phase ends with a verification gate and a phase proof file, now preserved in [docs/archive/](docs/archive/README.md).
See [`.claude/context/phase-status.md`](.claude/context/phase-status.md) for the
dated machine status and implementation context; it is not a live service check.

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

# 4. Start the prepared stack (first-time phase installation must already be complete)
bash deploy/start_all.sh
```

Open `http://localhost:8200` — the investigator workbench.

See [QUICKSTART_DEVELOPER.md](QUICKSTART_DEVELOPER.md) for the full phase-by-phase
build guide. The full-video order is **1 → 2 → 5 → VSS patch → 3 → 4 → 6 → 7 → 8**.
New data-flow diagrams are in [DESIGN.md §8](DESIGN.md#8-installation-and-evidence-data-flows);
[NVIDIA workshop topics](DESIGN.md#9-nvidia-modules-and-workshop-slide-preparation) are in §9.

---

## The method (why this is faster)

Install the NVIDIA skills into your coding agent and let each skill
**deploy/configure its blueprint** — the SME-optimized path — instead of writing
glue. The build proceeds in phases, each driven by a skill, each with a confirmation
gate. See **[QUICKSTART_DEVELOPER.md](QUICKSTART_DEVELOPER.md)**.

---

Repository connection: `origin` fetch/push is
`git@github.com:syseeker/agentic-multimodal-app.git`.

## License

Apache-2.0. Model weights (Qwen, MERaLiON, Nemotron, etc.) carry their own licenses —
review before commercial use.
