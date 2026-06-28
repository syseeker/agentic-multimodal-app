# Agentic Multimodal App

A **reference implementation** showing how to turn a *click-through* LLM application
into an **agentic, multimodal** one — built end-to-end on the **NVIDIA software
stack**, by deploying and configuring NVIDIA's blueprints via the skills rather than
hand-rolling them.

It ships with **Sherlock**, an example agent persona: a forensic co-worker that
ingests **photos**, **audio statements (口供)**, and **chat text**, then performs
**entity recognition → relationship graph → sentiment / paralinguistic analysis**,
always with a human-in-the-loop for accountability. Sherlock is just a configuration —
swap the tools, prompts, and data to retarget the same skeleton to any domain.

> **Build rule:** never hand-roll what an NVIDIA blueprint provides — deploy/configure
> it via its skill (the SME-optimized path). The agent layer is **AI-Q as the lead
> co-worker**, extended via its own points: **RAG-BP** as the Knowledge Layer (FRAG),
> a **video-specialist sub-agent (`vss-agent`) over MCP**, and speech/graph/sentiment
> as tools. Accountability = AI-Q's **built-in HITL plan-approval**. NeMo Agent Toolkit
> instruments/evaluates the agents (not itself an agent). Custom code only where no
> skill is the SME (flagged as a *proposal*).

---

## Two personas

| Persona | What they do | Where to look |
|---|---|---|
| **Developer** | Build the app fast with NVIDIA skills — deploy/configure blueprints, phase by phase. | [DESIGN.md](DESIGN.md) · [QUICKSTART_DEVELOPER.md](QUICKSTART_DEVELOPER.md) |
| **User** | Work a case with the agent: upload evidence, approve each step, read cited findings + relationship graph. | _(case-workbench UI built in Phase 8)_ |

---

## Architecture (short)

Four shared layers; the agent *decides* which tools to call (it is not a fixed
pipeline). Full detail + block diagram in **[DESIGN.md](DESIGN.md)**.

```
UI (custom case workbench)
  │
LEAD AGENT — AI-Q (single co-worker "Sherlock"): plan → HITL approval → execute → cite
  │   Knowledge Layer (text/docs/images): RAG-BP via FRAG
  │   video-specialist SUB-AGENT: vss-agent (via MCP) → shared ES+Neo4j
  │   tools: Parakeet/Canary ASR · MERaLiON paralinguistics · Neo4j+cuGraph · sentiment
  │   (NeMo Agent Toolkit instruments/evaluates — not the agent; web search OFF)
  ▼
NVIDIA COMPONENTS — AI-Q · RAG Blueprint · VSS · speech/LLM/VLM NIMs · Guardrails
  ▼
STORAGE — blob · one Elasticsearch (vector; Milvus/cuVS optional for GPU) · one Neo4j (graph) · Postgres
```

---

## The method (why this is faster)

A developer installs the NVIDIA skills into their coding agent and lets each skill
**deploy/configure its blueprint** — the SME-optimized way — instead of writing
glue. The build proceeds in phases, each driven by a skill, each with a confirmation
gate. See **[QUICKSTART_DEVELOPER.md](QUICKSTART_DEVELOPER.md)**.

## Status

Design signed off; implementation is **phased** with a confirmation checkpoint at the
end of every phase. Nothing is deployed until each phase is approved.

## License

Apache-2.0. Model weights (Qwen, MERaLiON, etc.) carry their own licenses — review
before commercial use.
