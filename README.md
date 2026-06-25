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
> it via its skill (the SME-optimized path). The agent is **AI-Q's deepagents agent
> borrowed + extended** (its native tools kept; web search off; forensic tools added).
> Capabilities come from the RAG Blueprint, VSS, and NIMs. Custom code only where no
> skill is the SME (and it's flagged as a *proposal*).

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
AGENT — AI-Q deepagents agent, borrowed + extended (NeMo Agent Toolkit), HITL
  │   tools: AI-Q deep-research (internal corpus, web off) · RAG-BP retrieve ·
  │          VSS CA-RAG · Parakeet ASR · MERaLiON paralinguistics · Neo4j+cuGraph
  ▼
NVIDIA COMPONENTS — AI-Q · RAG Blueprint · VSS · speech/LLM/VLM NIMs · Guardrails
  ▼
STORAGE — blob · one Milvus (vector) · one Neo4j (graph) · Postgres
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
