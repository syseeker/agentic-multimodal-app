# STE MSS × NVIDIA — Joint TODO

**From:** Meeting of June 12, 2026 (STE MSS + NVIDIA Technical Team)  
**Next sync:** July 2 or 3, 2026 (bi-weekly cadence)  
**Attendees:** Nat (FE), XinHe (PM), Darryl (Agil Trust), Zhu Cheng, Verlicia (BE), Claire (UI/UX), Jovan & BP (NVIDIA)

---

## Context

STE MSS runs an investigative platform on **GB10 hardware** (single-terminal per user, dev on 4090 laptops).  
Current stack: Qwen 3 14B + Qwen VL 2.5 3B · vLLM · ChromaDB + FalkorDB · Svelte frontend.  
Current workflows are **linear** (Chat Log Analyzer → Statement Analyzer → Document Query), non-agentic.

Goal: Move toward a **proactive co-agent** that plans and executes multi-step investigation tasks, while keeping the investigator legally accountable for every decision ("middle ground" — agent proposes, human approves).

NVIDIA's role: provide reference architectures, NIMs, observability tools, and hands-on support.

---

## Track 1 — Agentic Reference Implementation ("Code Drop")

> **Goal:** Demonstrate the path from static LLM workflows to agentic ones using this Sherlock repo as the worked example. STE MSS adapts it to their actual case workflows.

- [x] Implement lead agent (AI-Q / AgentIQ) with forensic persona and tool calling
- [x] Wire RAG Blueprint (FRAG) as knowledge layer for ingested case documents
- [x] Expose graph tools (Neo4j entity query + graph analysis) via MCP
- [x] Build multimodal case workbench UI (Svelte: chat, entity graph, evidence, paralinguistics)
- [x] Human-in-the-loop (HITL) plan approval — agent proposes, investigator approves
- [x] Multimodal ingest pipeline (text → RAG, audio → Parakeet ASR, image → VLM stub)
- [x] Document the agentic loop (Plan / Act / Observe / Refine) in AGENTS.md + DESIGN-EXT.md
- [ ] **Adapt to MSS workflows:** map Sherlock's chat-log / statement / document-query flows onto the agentic framework
- [ ] **Replace stub pipelines:** wire MeraLion 3 (A-STAR) for real paralinguistic analysis (replaces stub in `data/audio/process_audio.py`)
- [ ] **Swap graph DB:** evaluate FalkorDB (MSS current) vs Neo4j (Sherlock) — migrate if FalkorDB preferred
- [ ] **Swap vector DB:** evaluate ChromaDB (MSS current) vs Elasticsearch (Sherlock) — migrate if ChromaDB preferred
- [ ] Show investigator-facing flow: upload confiscated device export → agent autonomously runs chat log + statement analysis → presents cited findings for approval

---

## Track 2 — Observability, Evaluation & Profiling (NAT)

> **Goal:** Instrument the agentic system so STE MSS can measure, verify, and improve it — with or without full agentic deployment. Useful even for the current linear stack.

### 2a. Phoenix (on-premise observability)
- [ ] Deploy Phoenix on-premise (air-gapped — no cloud telemetry)
- [ ] Instrument AI-Q agent calls: log every LLM input/output, token counts, latency per step
- [ ] Instrument tool calls: log each graph query, RAG search, ASR call with latency + result size
- [ ] Build a dashboard view: TTFT, output tokens/sec, tool call latency per investigator session
- [ ] Set alert thresholds for degraded performance (e.g. TTFT > 5s)

### 2b. NeMo Agent Toolkit (NAT) — evaluation & optimization
- [ ] Integrate NAT for **LLM-as-a-judge** evaluation: score agent responses for accuracy, citation correctness, and forensic conduct adherence
- [ ] Add **guardrail evaluation**: verify NeMo Guardrails are blocking disallowed actions (web search in air-gapped mode, unauthorized file access)
- [ ] Set up **regression eval suite**: fixed set of investigator questions → expected answers → automated scoring after each code change
- [ ] Profile agent pipeline with NAT profiler: identify which step consumes the most time/tokens
- [ ] Produce optimization recommendations: prompt compression, caching, batching strategies

---

## Track 3 — Inference Optimization (GB10 + NIM)

> **Goal:** Maximize throughput and minimize TTFT on NVIDIA GB10 (enterprise Blackwell) for MSS's long-context/short-output paradigm. Dev parity on 4090 where feasible.

### 3a. Benchmarking
- [ ] Measure baseline TTFT and output tokens/sec for current Qwen 3 14B on GB10
- [ ] Measure baseline for Qwen VL 2.5 3B (VLM for document/image analysis)
- [ ] Characterize the MSS workload profile: typical context length, output length, concurrency (1 user per terminal)
- [ ] Reproduce the **multi-container crash issue** on 4090 (three heavy containers) → identify memory ceiling

### 3b. NIM deployment on GB10
- [ ] Deploy optimized NIM profiles for Qwen 3 14B on GB10 (FP8, paged attention, chunked prefill)
- [ ] Deploy NIM for VLM (Qwen VL 2.5 3B or equivalent) alongside LLM on same GB10 without OOM
- [ ] Deploy Parakeet ASR NIM (or MeraLion 3 via NIM if packaged) — validate no memory conflict
- [ ] Test multi-NIM co-existence: LLM + VLM + ASR simultaneously on single GB10 terminal
- [ ] Document the working NIM profile config for STE MSS IT replication across all terminals

### 3c. Optimization
- [ ] Apply NIM-recommended GB10 tensor-parallel / pipeline-parallel settings
- [ ] Tune KV-cache size for long-context case files (chat log exports can be large)
- [ ] Evaluate quantization trade-offs: FP8 vs INT4 for quality vs speed on investigative outputs
- [ ] Compare Qwen 3 14B vs Nemotron-3-nano-30B on MSS eval suite — recommend best fit

---

## Track 4 — Safety & Policy (Guardrails + OpenShell)

> **Goal:** Ensure autonomous agent actions are bounded — no unauthorized file access, no external network calls, no actions outside defined forensic scope.

- [ ] Deploy NeMo Guardrails on-premise (input/output rails for investigative context)
- [ ] Define MSS-specific guardrail policies: what questions/actions are in-scope vs out-of-scope
- [ ] Evaluate OpenShell for filesystem and network policy enforcement on GB10 terminals
- [ ] Test guardrail coverage: agent should refuse web search, refuse cross-case data access, flag speculative claims
- [ ] Integrate guardrail evaluation into NAT eval suite (Track 2b)

---

## Track 5 — Process & Comms

- [ ] Set up shared **Telegram group** (NVIDIA + STE MSS) for immediate troubleshooting, codebase queries, prompt versioning
- [ ] Schedule **next sync: July 2 or July 3, 2026**
- [ ] Agree on demo scope for next meeting: which track(s) to show progress on
- [ ] Establish **prompt versioning** convention (currently ad-hoc — suggest git-tracked prompt files like `deploy/aiq-prompts/`)

---

## Open Questions

| Question | Owner | Status |
|----------|-------|--------|
| Will MSS migrate to Neo4j + Elasticsearch, or stay on FalkorDB + ChromaDB? | XinHe / Verlicia | Open |
| Is MeraLion 3 packaged as a NIM, or called via A-STAR API? | NVIDIA / A-STAR | Open |
| What is the GB10 RAM spec for MSS terminals — 96GB or 192GB? | Darryl / Zhu Cheng | Open |
| Are 4090 dev laptops expected to run all NIMs simultaneously, or just one at a time? | Verlicia | Open |
| Should HITL approval be per-step or per-plan (current: per-plan)? | Claire / XinHe | Open |
| Telegram group — who creates and manages? | BP / XinHe | Open |
