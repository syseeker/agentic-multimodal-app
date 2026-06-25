# Architecture

## From click-through to agentic

The original app was a fixed pipeline the user clicked through:

```
Upload → Extract → Chat-Log Analyze → Statement Analyze → Document Query
```

Each step was a separate form. The agentic version keeps every capability but lets an **orchestrator** decide *which* capabilities to run, *in what order*, and *how to cross-check* — while the investigator approves each consequential step.

```
                 ┌──────────────────────── AGENT APP ────────────────────────┐
  User  ───────▶ │  Svelte UI  →  Orchestrator (AI-Q deep-research pattern)   │
  (chat + HITL)  │                Planner → Investigator(s) → Critic          │
                 │                engine = deepagents (primary) | Hermes (alt) │
                 │                         │                                   │
                 │   ┌─────────────────────┴───────────────── TOOLS ───────┐  │
                 │   │ image-extract  Qwen3-VL    (OCR, scene, entities)    │  │
                 │   │ audio-extract  MERaLiON-3  (ASR + paralinguistics)   │  │
                 │   │ text-extract   Qwen3       (entities + relations)    │  │
                 │   │ graph-build    FalkorDB    (+ cuGraph analytics)     │  │
                 │   │ rag            Milvus/cuVS (+ NeMo Retriever)        │  │
                 │   │ sentiment      MERaLiON+Qwen3 (fused)                │  │
                 │   └──────────────────────────────────────────────────────┘ │
                 │   NeMo Guardrails wrap every step (citations, no autonomy,  │
                 │   human approval gates, topic + output rails)               │
                 └─────────────────────────┼──────────────────────────────────┘
   Serving (vLLM FP8, ModelOpt) ───────────┤
   Observability (NeMo Agent Toolkit → Phoenix/OTLP), Profiling (aiperf + Nsight)
```

## Components

### Orchestrator
The **AI-Q deep-research pattern** — a *Planner* decomposes the request, one or more *Investigator* sub-agents call tools, and a *Critic* cross-checks findings and demands citations. Implemented on `deepagents` + `langgraph` (`app/engines/deepagents_engine.py`). A second engine adapter targets the Hermes/NemoClaw harness (`app/engines/hermes_engine.py`) and is selected by `AGENT_ENGINE`.

### Tools (the former click-through "skills")
Each capability is now an agent tool returning **structured Pydantic JSON** (`app/models.py`). This keeps outputs verifiable and graph-loadable. Tools live in `app/tools/`.

### Data layer
- **Vectors:** Milvus accelerated by **cuVS** (NVIDIA-native, what NeMo Retriever / the RAG Blueprint default to). Chroma is a no-GPU dev fallback (`VECTOR_BACKEND`).
- **Graph:** FalkorDB stores the Cypher entity-relationship graph. **cuGraph** runs GPU analytics over it — centrality (key player), community detection (cells/clusters).

### Serving
Three vLLM servers (text / VLM / audio), FP8 via NVIDIA ModelOpt, one per model, sharing the GPU. `serving/` provides a GPU-profile switch so the same artifacts run on RTX PRO 6000 (dev) and GB10 (deploy).

### Accountability
Investigators require legal accountability, so the design forbids autonomous consequential actions: the Critic must cite sources, and the UI gates each step behind human approval (the "middle ground" between a static summarizer and a fully autonomous agent). NeMo Guardrails enforce this programmatically (P1).
