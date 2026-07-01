# Roadmap — Agentic Multimodal App

Work items beyond the core Phase 0–8 build. Grouped by theme.
Items marked `[deferred]` need GPU hardware or additional infrastructure to unblock.

---

## Track 1 — Agentic Reference Implementation

> Demonstrate the path from static LLM workflows to agentic ones using this Sherlock
> repo as the worked example. Adapters swap in a different domain's tools, prompts,
> and data without changing the agent skeleton.

- [x] Lead agent (AI-Q / AgentIQ) with domain persona and tool calling
- [x] RAG Blueprint (FRAG) as knowledge layer for ingested case documents
- [x] Graph tools (Neo4j entity query + graph analysis) via MCP
- [x] Multimodal case workbench UI (Svelte: chat, entity graph, evidence, paralinguistics)
- [x] Human-in-the-loop (HITL) plan approval — agent proposes, user approves
- [x] Multimodal ingest pipeline (text → RAG, audio → Parakeet ASR, image → VLM stub)
- [x] Document the agentic loop (Plan / Act / Observe / Refine) in AGENTS.md + DESIGN-EXT.md
- [ ] End-to-end investigator flow: upload confiscated device export → agent runs analysis → presents cited findings for approval
- [ ] Replace paralinguistics stub: wire MERaLiON 3 (A-STAR) for real paralinguistic analysis (`data/audio/process_audio.py`)
- [ ] Document graph DB swap path: Neo4j (default) → FalkorDB (alternative)
- [ ] Document vector DB swap path: Elasticsearch (default) → ChromaDB (alternative)

---

## Track 2 — Observability, Evaluation & Profiling (NeMo Agent Toolkit)

> Instrument the agentic system so teams can measure, verify, and improve it —
> useful even for non-agentic (linear) stacks.

### 2a. Phoenix (on-premise observability)
- [ ] Deploy Phoenix on-premise (air-gapped — no cloud telemetry)
- [ ] Instrument AI-Q agent calls: log every LLM input/output, token counts, latency per step
- [ ] Instrument tool calls: log each graph query, RAG search, ASR call with latency + result size
- [ ] Build a dashboard view: TTFT, output tokens/sec, tool call latency per session
- [ ] Set alert thresholds for degraded performance (e.g. TTFT > 5s)

### 2b. NeMo Agent Toolkit (NAT) — evaluation & optimization
- [ ] LLM-as-a-judge evaluation: score agent responses for accuracy, citation correctness, and conduct adherence
- [ ] Guardrail evaluation: verify NeMo Guardrails block disallowed actions (web search in air-gapped mode, unauthorized access)
- [ ] Regression eval suite: fixed question set → expected answers → automated scoring on every prompt change
- [ ] Profile agent pipeline with NAT profiler: identify which step consumes the most time/tokens
- [ ] Produce optimization recommendations: prompt compression, caching, batching strategies

### 2c. Deferred (needs GPU or cloud)
- [ ] `[deferred]` **Nsight GPU profiling** — kernel-level profiling of NIM inference. Needs RTX PRO 6000 Blackwell or GB10.
- [ ] `[deferred]` **aiperf concurrent user load test** — multi-user throughput via `rag-perf` skill. Needs GPU for representative results.
- [ ] `[deferred]` **OTEL Collector → Grafana Tempo** — production air-gapped observability backend. Replaces Phoenix for prod. Config: `general.telemetry.tracing.otel` with `redaction_enabled: true`.
- [ ] `[deferred]` **LangSmith / W&B Weave** — cloud tracing for experiment comparison. Only enable if data-perimeter policy permits.
- [ ] `[deferred]` **Full regression eval suite** — expand from 20 to 100+ questions across all case types.
- [ ] `[deferred]` **RAG layer RAGAS eval** (`rag-eval` skill) — faithfulness, context precision, context recall. Complements end-to-end LLM-as-judge eval.
- [ ] `[deferred]` **Nemotron-3-Content-Safety multimodal** — text + image safety for submitted evidence photos. Needs GPU.

---

## Track 3 — Inference Optimization (GB10 + NIM)

> Maximize throughput and minimize TTFT on NVIDIA GB10 (enterprise Blackwell) for
> long-context / short-output workloads. Dev parity on RTX 4090 where feasible.

### 3a. Benchmarking
- [ ] Measure baseline TTFT and output tokens/sec for the primary LLM on GB10
- [ ] Measure baseline for the VLM (document/image analysis)
- [ ] Characterize workload profile: typical context length, output length, concurrency
- [ ] Reproduce multi-container OOM on 4090 (three heavy containers) → identify memory ceiling

### 3b. NIM deployment on GB10
- [ ] Deploy optimized NIM profiles for primary LLM on GB10 (FP8, paged attention, chunked prefill)
- [ ] Deploy VLM NIM alongside LLM on same GB10 without OOM
- [ ] Deploy ASR NIM — validate no memory conflict
- [ ] Test multi-NIM co-existence: LLM + VLM + ASR simultaneously on a single GB10 node
- [ ] Document the working NIM profile config for IT replication across all nodes

### 3c. Optimization
- [ ] Apply NIM-recommended GB10 tensor-parallel / pipeline-parallel settings
- [ ] Tune KV-cache size for long-context inputs (chat log exports can be large)
- [ ] Evaluate quantization trade-offs: FP8 vs INT4 for quality vs speed
- [ ] Compare LLM candidates on the eval suite — document best fit and rationale

---

## Track 4 — Safety & Policy (Guardrails)

> Ensure autonomous agent actions are bounded — no unauthorized file access, no
> external network calls, no actions outside the defined domain scope.

- [ ] Deploy NeMo Guardrails on-premise (input/output rails for the investigative context)
- [ ] Define domain-specific guardrail policies: in-scope vs out-of-scope questions and actions
- [ ] Evaluate OpenShell for filesystem and network policy enforcement on air-gapped nodes
- [ ] Test guardrail coverage: refuse web search, refuse cross-case data access, flag speculative claims
- [ ] Integrate guardrail evaluation into NAT eval suite (Track 2b)
