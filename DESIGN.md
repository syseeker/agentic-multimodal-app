# Agentic Multimodal App · Architecture Design

Authoritative design. **Build rule:** never hand-roll what an NVIDIA blueprint/skill
provides — deploy/configure it via its skill. Custom code only where no skill is the
SME (and it's flagged as a *proposal*). Design is signed off before implementation;
each phase has a **confirmation gate**.

> **Reusable skeleton.** **Sherlock** (a forensic co-worker) is the *worked example*
> used throughout — retarget to another domain by swapping configured tools, prompts,
> and data; the layers and method stay the same.

---

## 1. Problem statement

An **agentic co-worker for forensic investigators ("Sherlock")**. It ingests
**seized multimodal evidence** — photos from confiscated phones/laptops, **audio
statements (口供)**, and **WhatsApp/chat text** — and autonomously **plans and
performs**: **entity recognition** across all assets, **relationship-graph**
construction, and **sentiment / paralinguistic** analysis. It returns
**court-defensible cited findings**, with a **human-in-the-loop** approving each
consequential step. It turns today's **click-through** forensic app into an
**agentic** one, on **NVIDIA blueprints/SDKs as much as possible**.

The customer explicitly wants the **"middle ground"**, *not* full autonomy:
a co-agent that **proposes**, the investigator **approves**. Accountability is
mandatory; the agent advises, the human decides.

### Personas
- **Developer** — assembles the app from NVIDIA components via the skills (see [QUICKSTART_DEVELOPER.md](QUICKSTART_DEVELOPER.md)).
- **Investigator (user)** — works a case in the UI; approves each step; reads cited findings.

### Hard constraints
- **Air-gapped**: no internet at runtime. ⇒ **NIMs self-hosted** in production
  (GB10 / RTX PRO 6000, FP8); **AI-Q deep research runs over internal storage only,
  web search OFF**. Hosted NIMs (`build.nvidia.com`) allowed for **dev only**.
- **Orchestration + config overlay**: this repo deploys/configures the blueprints
  (skills clone them); it does **not** vendor or fork blueprint source.

---

## 2. Layered architecture

```
 INVESTIGATOR (browser)
        │ HTTPS / SSE
 ┌──────▼─────────────── UI LAYER — custom case workbench ───────────────────┐
 │ multimodal intake · chat · PLAN+APPROVE (HITL) · relationship-graph view · │
 │ cited findings/report · sentiment panel · evidence viewer                  │
 └──────┬─────────────────────────────────────────────────────────────────────┘
        │ REST/SSE
 ┌──────▼──── AGENT LAYER — hierarchical multi-agent ──────────────────────────┐
 │ SUPERVISOR = an SME deep agent (deepagents), forensic-configured:            │
 │   decompose → DECIDE which sub-agent/tool → delegate → HITL gate → aggregate │
 │   cited findings.  (NeMo Agent Toolkit instruments / evaluates / guards it — │
 │   NAT is the framework, NOT the agent.)                                      │
 │   delegates to SPECIALIST SUB-AGENTS:                                        │
 │   ├─ AI-Q deep-research  (internal corpus, WEB OFF; own Clarifier)           │
 │   ├─ VSS                 (video analysis → Neo4j ER)                         │
 │   └─ RAG-BP              (retrieval / agentic-RAG over the corpus)           │
 │   and calls SERVICE TOOLS:                                                   │
 │   transcribe→Parakeet · paralinguistics→MERaLiON · graph_query/analyze→      │
 │   Neo4j+cuGraph · sentiment · extract_entities (non-video ER)               │
 │ HITL approval at every delegation boundary                                   │
 └──────┬───────────────────────────────────────────────────────────────────────┘
 ┌──────▼──────────────── NVIDIA COMPONENT LAYER ────────────────────────────┐
 │ AI-Q (deep-research backend, headless, RAG-only)                           │
 │ RAG Blueprint: rag-server · ingestor/NV-Ingest · embed+rerank NIM · VLM    │
 │ VSS: RT-VLM dense-caption · RT-Embed · CA-RAG → Neo4j (video ER)           │
 │ Speech: Parakeet ASR (Canary opt) ·  MERaLiON (self-hosted, paralinguistics)│
 │ LLM/VLM NIMs (shared) · NeMo Guardrails + Content-Safety NIM               │
 │ NeMo Agent Toolkit (obs/eval/profiling) · aiperf · Nsight                  │
 └──────┬───────────────────────────────────────────────────────────────────────┘
 ┌──────▼──────────────── STORAGE LAYER (shared) ────────────────────────────┐
 │ BLOB: VIOS (video) + object store (image/audio/docs)                       │
 │ VECTOR: one Milvus (cuVS) — captions/transcripts/chat embeddings           │
 │ GRAPH: one Neo4j — entities+relations (VSS video ER + non-video ER step)   │
 │ RELATIONAL: Postgres — case/asset registry, jobs, agent checkpoints        │
 └────────────────────────────────────────────────────────────────────────────┘
```

### Layer responsibilities
- **UI** — purpose-built case workbench (neither AI-Q's research UI nor VSS's video
  UI fit). Requirements in §4.
- **Agent** — **hierarchical multi-agent**. The **supervisor is an SME deep agent
  (deepagents** — the SME deep-agent framework, the same tech AI-Q is built on),
  forensic-configured. **It decides** which specialist **sub-agent** to delegate to —
  **AI-Q deep-research** (internal corpus, web off; keeps its own
  Clarifier/Planner/Critic), **VSS** (video → Neo4j ER), **RAG-BP**
  (retrieval/agentic-RAG) — and which **service tools** to call (Parakeet, MERaLiON,
  Neo4j+cuGraph, sentiment, non-video ER). **NeMo Agent Toolkit instruments,
  evaluates, and guards** this agent tree — NAT is the framework, **not** the agent.
  HITL approval at each delegation boundary keeps autonomy bounded (the customer's
  "middle ground"). *Calling AI-Q/VSS/RAG-BP does trigger their agents — intentional
  (Pattern A);* sub-agents return cited results, the supervisor aggregates them.
- **NVIDIA components** — capabilities the agent calls; each deployed via its skill.
- **Storage** — one of each store, shared across components (no per-blueprint copies).

---

## 3. Component decisions (overlap resolved)

| Concern | Decision | Skill / source |
|---|---|---|
| Supervisor agent | **SME deep agent (deepagents), forensic-configured** — decides which sub-agent/tool to call | deepagents framework; **NeMo Agent Toolkit** instruments/evaluates/guards (not the agent) |
| Deep-research SUB-AGENT | **AI-Q**, **web OFF** (air-gapped) | `aiq-deploy`, `aiq-research` |
| Video SUB-AGENT (+ ER graph) | **VSS** (CA-RAG `graph_db` → Neo4j) | `vss-deploy-profile`, `vss-summarize-video` |
| Retrieval SUB-AGENT / ingestion | **RAG Blueprint** (AI-Q's FRAG substrate) | `rag-blueprint` + `aiq frag` |
| ~~Lightweight RAG~~ | **dropped** (overlaps RAG-BP) | ~~`nemo-retriever`~~ |
| ASR | **Parakeet** (primary), Canary optional | `nemotron-speech` |
| Paralinguistics / Singlish-SEA | **MERaLiON-3** (self-hosted) | *custom — no skill* |
| Guardrails / HITL policy | NeMo Guardrails + Content-Safety | `nemotron-policy-generator` + RAG-BP |
| Obs / eval / profiling | NeMo Agent Toolkit + Phoenix; aiperf; Nsight | NAT docs |
| Synthetic demo data | NeMo Data Designer | `data-designer` |
| Vector store | **one Milvus (cuVS)** | shared (RAG-BP + VSS) |
| Graph store | **one Neo4j** (Community = one DB, many cases by label/`case_id`) | shared (VSS + ER step) |

### Storage strategy (per modality)
| Asset | Blob | Vector | Graph |
|---|---|---|---|
| Image | file in object store | OCR/scene caption embeddings | entities/relations |
| Audio | file in object store | transcript (Parakeet) embeddings | entities/relations; sentiment as property |
| Video | VIOS | dense-caption (RT-Embed) embeddings | VSS CA-RAG entities/relations |
| Chat/text | (raw kept) | chunk embeddings | entities/relations |

Raw media never goes in the vector DB — only embeddings of its derived text.

---

## 4. UI requirements (the custom workbench)
| Need | From the problem |
|---|---|
| Multimodal case intake (image/audio/chat) | the three evidence types |
| Chat with Sherlock | ask about the case |
| Plan + step trace with **Approve/Reject** | HITL / legal accountability |
| **Relationship-graph** view (entities, edges, key players) | the ER-graph deliverable |
| **Cited findings/report**, click-through to source asset | court-defensible |
| **Sentiment/paralinguistic** panel per statement | the sentiment deliverable |
| **Evidence viewer** (image / audio / transcript) | verify a citation |

---

## 5. Custom pieces (proposals — no blueprint is the SME)
1. **Supervisor deep agent** — an SME deep agent (deepagents) configured for
   forensics: decides which sub-agent (AI-Q/VSS/RAG-BP) and tool to call, delegates,
   HITL-gates, and aggregates cited findings. Instrumented/evaluated/guarded by
   **NeMo Agent Toolkit** (NAT ≠ the agent).
2. **Case-workbench UI.**
3. **Non-video text→ER step** writing into the shared Neo4j (match VSS schema).
4. **MERaLiON paralinguistic sentiment** (self-hosted).
5. **Orchestration/config overlay** wiring the blueprints together.

Everything else = deploy/configure a blueprint via its skill.

---

## 6. Phased plan — each ends with a CONFIRMATION GATE

> The developer drives each phase via the named skill (always the latest, installed
> fresh). At the gate: run the verify step, I report, **you confirm before the next
> phase**. Details + commands live in [QUICKSTART_DEVELOPER.md](QUICKSTART_DEVELOPER.md).

| Phase | Goal | Skill | Custom? |
|---|---|---|---|
| 0 | This design sign-off | — | — |
| 1 | Deploy AI-Q backend (headless, web OFF); healthy | `aiq-deploy` | config |
| 2 | Deploy RAG-BP, wire as AI-Q FRAG; ingest docs/img/text | `rag-blueprint` + `aiq frag` | config |
| 3 | Forensic config + demo cases; cited deep-research over case files | `aiq configs` + `data-designer` | config + data |
| 4 | Audio: Parakeet ASR into ingestion; MERaLiON paralinguistics | `nemotron-speech` + **proposal** | proposal |
| 5 | Deploy VSS (lvs) + Neo4j CA-RAG (video ER) | `vss-deploy-profile` | config |
| 6 | Non-video ER → shared Neo4j; graph+cuGraph as agent tool | **proposal** | proposal |
| 7 | **Build supervisor deep agent** (deepagents): decide + delegate to AI-Q/VSS/RAG-BP sub-agents + service tools; HITL at each delegation; guardrails; NAT-instrumented | deepagents + NeMo Agent Toolkit + `nemotron-policy-generator` | proposal + config |
| 8 | Custom case-workbench UI | **proposal** | proposal |
| 9 | Observability / eval / benchmark | NAT + `aiperf` + Nsight | config |

(Phases 1–6 stand up the sub-agents + capabilities; 7 **builds the supervisor deep agent** over them; 8 the UI; 9 hardens.)

---

## 7. Deployment shapes
- **Dev (no GPU / single GPU)** — hosted NIMs (`build.nvidia.com`) allowed; subset of
  components.
- **Production (air-gapped)** — all NIMs self-hosted (GB10 / RTX PRO 6000, FP8);
  no web; AI-Q RAG-only. See per-phase notes in QUICKSTART.

Open verification items (resolved in their phase, from the skills — not guessed):
AI-Q web-off config, exact FRAG wiring, VSS↔shared-Neo4j schema match, embedding-model
unification (RAG-BP vs VSS graph embedder).
