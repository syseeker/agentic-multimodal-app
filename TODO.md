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
- [x] Multimodal ingest pipeline:
  - text → RAG Blueprint (FRAG) ✅
  - audio → Parakeet RNNT Multilingual ASR (cloud) + MERaLiON-3-10B paralinguistics (GPU) ✅
  - image → **not implemented** (`data/image/caption_images.py` does not exist; upload reports `image_caption_unavailable`)
  - video → VSS LVS `summarize_video` via direct rtvi-vlm call → Sherlock cited answer in UI ✅ (persist to RAG/Neo4j is TODO)
- [x] Document the agentic loop (Plan / Act / Observe / Refine) in AGENTS.md + DESIGN-EXT.md
- [x] **Test case upload** — upload a new case via the workbench UI (`/upload-case`) and verify it appears in the case list with correct metadata
- [x] Document graph DB swap path: Neo4j (default) → FalkorDB (alternative)
- [x] Document vector DB swap path: Elasticsearch (default) → ChromaDB (alternative)



### Phase 2 — RAG Blueprint

- [x] RAG Blueprint deployed (rag-server :8081, ingestor :8082, Elasticsearch VSS-owned, SeaweedFS)
- [x] Agentic RAG enabled (`ENABLE_AGENTIC_RAG=true`) — query decomposition → retrieval → cited synthesis
- [x] FRAG wired: AI-Q → RAG Blueprint knowledge layer via `config_sherlock_frag.yml`
- [x] 21 forensic cases ingested (85+ files, `multimodal_data` collection) — text, transcripts, analysis files
- [x] Audio analysis (`audio_analysis.txt`) ingested with human-readable MERaLiON paralinguistics summary
- [x] `ingest_start.sh` / `ingest_stop.sh` — clean nv-ingest lifecycle (VSS Redis/ES compatibility)



### Phase 3 — Data simulation

- [x] **Text cases** — 20 Singapore forensic cases generated via NeMo Data Designer (Nemotron Nano 30B): case reports, witness statements, lab reports, WhatsApp chats (Singlish), metadata
- [x] **Audio simulation** — Magpie TTS (`ai-magpie-tts-multilingual`): per-speaker voice auto-assigned from name patterns (Vietnamese/Chinese/Indian/Malay/English → matching Magpie voice + language code); `generate_audio_samples.py` with `--case`, `--file`, `--voice`, `--test-tone` flags
- [x] **Video prompts** — `video_prompt.txt` per case for ChatGPT Enterprise video generation; sample MP4s in `data/video/sample/`
- [x] **Hokkien TTS** — `MERaLiON-OmniVoice-Hokkien-TTS` (OmniVoice library, GPU) for Hokkien/Southern Min witness statements
- [x] Sample media committed to `data/audio/sample/` and `data/video/sample/` for demo



### Phase 4 — Audio pipeline

- [x] **Test evidence upload (audio)**
  - Magpie TTS → WAVs with per-speaker voice/language matching
  - Parakeet RNNT Multilingual (cloud ASR) → transcript → RAG ingest → Sherlock cites audio evidence
  - **MERaLiON-3-10B paralinguistics working**: language/emotion/stress/confidence extracted from audio
  - Sample case committed with full pipeline output
- [x] **MERaLiON-3-10B paralinguistics** wired in `process_audio.py` — GPU + HF_TOKEN required; falls back gracefully *(verified: RTX Pro 6000 x86_64 / Boon Ping)*
- [ ] **MERaLiON on GB10/DGX Spark** *(Jovan)* — aarch64 path in `process_audio.py` should work but not yet tested; audio evidence on DGX Spark still uses stub paralinguistics



### Phase 5 — VSS video analysis

- [x] **VSS LVS profile deployed** — profile: **LVS only** (Long Video Summarization). Other profiles: `base`/`alerts` not needed for Sherlock; `search` deferred (2-GPU required).
  - `dev-profile.sh -p lvs -H RTXPRO6000BW`; RTX Pro 6000 Blackwell 96 GB; Cosmos Reason2-8B VLM; Nemotron Nano 9B LLM (remote) *(verified: x86_64 / Boon Ping)*
  - `patch_vss_rtvi_vlm.sh` — re-applies rtvi-vlm container patches after every Phase 5 re-deploy
- [ ] **VSS on GB10/DGX Spark** *(Jovan)* — `phase5_vss.sh` has aarch64 PATH A (`dev-profile.sh -p base -H DGX-SPARK`) ready; not yet deployed on GB10. Video pipeline (Phase 5 + rtvi-vlm patches) pending Jovan.
- [x] **Video analysis working in UI** — `ask_video` + `summarize_video` via direct rtvi-vlm `/v1/chat/completions` (1fps, 4-8s); forensic narrative with `[1] mcp_vss_agent__summarize_video` citation; verified on homicide (assault weapon) and drug trafficking cases
- [x] **Test evidence upload (video)** — upload MP4 via workbench Evidence tab → VIOS registration → `*_analysis.txt` placeholder → Sherlock analyses on-demand via VSS MCP

- [ ] **Persist video analysis to RAG + Neo4j** — write VLM result to `<stem>_analysis.txt`, ingest to RAG, run entity extraction; currently shown in chat only
- [ ] **[2-GPU required] Semantic video search** — VSS `search` profile (RT-Embed + separate ES indices); NVIDIA Alpha; conflicts with LVS on host-network ports. Includes cross-video search (find same suspect across multiple videos). Skill: `~/skills/skills/vss-deploy-profile/references/search.md`



### Phase 6 — Entity graph (Neo4j)

- [x] Neo4j entity graph deployed (`amms-neo4j`, :7474/:7687)
- [x] LLM-based entity extraction over all case text files; graph tools: `graph_query`, `graph_analyze`, `extract_entities`, `list_cases` — all verified
- [x] `GRAPH_CASE_LIMIT` env var for partial ingest (`GRAPH_CASE_LIMIT=5 bash deploy/phase6_graph.sh`)



### Phase 7 — Sherlock MCP + AI-Q extensions

- [x] Sherlock MCP (`amms-sherlock-mcp`, :9901) — graph tools + audio tools (`list_audio_files`, `get_audio_analysis`, `analyze_audio`)
- [x] VSS Sherlock MCP (`amms-vss-sherlock-mcp`, :9903) — `ask_video`, `summarize_video`, `list_case_videos`
- [x] AI-Q switched to `config_sherlock_frag_mcp.yml` (web OFF, graph + RAG + VSS MCP); forensic prompts applied
- [x] Audio evidence flow verified: Parakeet ASR + MERaLiON paralinguistics → `audio_analysis.txt` → RAG → Sherlock cited answer
- [x] Video evidence flow verified: MP4 upload → VIOS → rtvi-vlm direct call (4-8s, 1fps) → Sherlock cited answer in UI
- [ ] nv-ingest auto-start/stop in workbench upload (`ui/server.py`) — saves ~10 GB RAM idle



### After Phase 8

- [x] End-to-end investigator flow: upload audio/video evidence → Sherlock analyses via Parakeet/MERaLiON/VSS → cited forensic findings in UI ✅ (2026-07-28)
- [ ] Upload new case (text + audio + image + video) and verify all evidence searchable via Sherlock with citations
- [ ] Persist video analysis to RAG + Neo4j (see Phase 5 TODO)

---



## Track 2 — Observability, Evaluation & Profiling (NeMo Agent Toolkit)

> Instrument the agentic system so teams can measure, verify, and improve it —
> useful even for non-agentic (linear) stacks.



### 2a. Phoenix (on-premise observability)

> **MVP shipped 2026-08-29 (GB10).** `deploy/phase9a_observability.sh` ·
> record `deploy/PHASE9A_OBSERVABILITY.md` · guide `QUICKSTART_TRACK2.md`

- [x] Deploy Phoenix on-premise (air-gapped — no cloud telemetry) — `amms-phoenix` :6007,
      Sherlock-owned, separate from VSS's `phoenix` :6006
- [x] Instrument AI-Q agent calls: log every LLM input/output, token counts, latency per step
      — config-only (`general.telemetry.tracing.phoenix`), no agent code changed
- [x] Instrument tool calls: log each graph query, RAG search, ASR call with latency + result size
      — verified for graph + RAG tool spans. **Caveat:** the Sherlock MCP server's *own* LLM
      calls (`graph/tools.py`) run in a separate process and are NOT traced (no `traceparent`
      propagation through NAT's MCP client)
- [ ] Build a dashboard view: TTFT, output tokens/sec, tool call latency per session
      — Phoenix's project view already shows per-span latency + tokens; a custom dashboard is
      a Grafana job, pairs with the OTEL path below
- [ ] Set alert thresholds for degraded performance (e.g. TTFT > 5s)
      — Phoenix 14.x has no built-in alerting; needs OTEL Collector → Grafana (also the
      air-gapped production route, and where PII redaction must be enabled)



### 2b. NeMo Agent Toolkit (NAT) — evaluation & optimization

> **MVP shipped 2026-08-29 (GB10).** `deploy/phase9b_eval.sh` ·
> record `deploy/PHASE9B_EVAL.md` · guide `QUICKSTART_TRACK2.md`

- [x] LLM-as-a-judge evaluation: score agent responses for accuracy, citation correctness, and conduct adherence
      — `_type: tunable_rag_evaluator` (NOT `llm_judge`, which does not exist), judged by
      `gpt_oss_llm` — a different model family from the agent under test
- [ ] Guardrail evaluation: verify NeMo Guardrails block disallowed actions (web search in air-gapped mode, unauthorized access)
      — **blocked, not skipped:** NeMo Guardrails is not deployed. `guardrails/` holds a
      drafted policy doc, not enforcement (that is Phase 9d), so there is nothing to test.
      3 refusal questions in the eval dataset are the interim proxy
- [x] Regression eval suite: fixed question set → expected answers → automated scoring on every prompt change
      — 14 questions grounded in real `data/cases/` files, incl. 3 refusal traps.
      **Compare score bands, not equality** — the judge is nondeterministic at temperature 0
- [x] Profile agent pipeline with NAT profiler: identify which step consumes the most time/tokens
      — rides the same run as the eval. Measured: LLM 6.28s > `knowledge_search` 3.12s >
      graph tool 0.06s
- [ ] Produce optimization recommendations: prompt compression, caching, batching strategies
      — the profiler now supplies the evidence (LLM-bound); turning it into changes is a
      follow-on task needing its own before/after measurement



### 2c. Deferred

> The "needs GPU" blocker is **cleared** — Phases 1–8 run on an RTX Pro 6000 Blackwell.
> Nsight and aiperf are now scheduled as **Phase 9e**: `deploy/PHASE9E_INFERENCE_BENCHMARK.md`.

- [ ] **Nsight GPU profiling** — kernel-level profiling of local inference. Unblocked; Phase 9e step B7.
- [ ] **aiperf load test** — VLM + MERaLiON directly, RAG via the `rag-perf` skill. Unblocked; Phase 9e steps B4–B5.
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

> Planned in **`deploy/PHASE9E_INFERENCE_BENCHMARK.md`**. Scope this round: **VLM,
> MERaLiON, RAG**. Everything else is remote NIM and is recorded as an end-to-end baseline
> only — the bar local hosting must beat when these models move on-prem for sensitivity.

- [ ] Measure the VLM on RTX Pro 6000: TTFT, ITL, e2e percentiles, throughput, J/req (B4)
- [ ] Measure MERaLiON-3-10B behind the OpenAI shim (B3–B4)
- [ ] RAG stage breakdown — retrieval / rerank / LLM TTFT / generation — via `rag-perf` (B5)
- [ ] Characterize the real workload from the 21-case corpus: context length, output length, concurrency (B2)
- [ ] Establish the VRAM ceiling: does the VLM + MERaLiON co-reside in 96 GB, and at what cost (B6)
- [ ] Baseline the remote NIMs (agent LLM, embed, rerank, Parakeet, Magpie) — note these include internet RTT
- [ ] Repeat the suite on GB10 once Phase 5 lands there



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

---



## Track 5 — Production Architecture: NemoClaw + Hermes Migration

> Current Sherlock runs as a monolithic AI-Q container (single `amms-aiq-agent`).
> NemoClaw + Hermes is NVIDIA's production pattern for multi-agent systems on
> Kubernetes/OpenShift — each agent becomes a separate pod with its own
> `PERSONA.md`, `TOOLS.md`, and `SKILLS.md`, communicating via the Hermes message bus.
> See [AGENTS.md](AGENTS.md) §3 for the full comparison and component mapping.



### When to migrate

Migrate from AI-Q (monolithic) to NemoClaw + Hermes when you need:

- True multi-agent parallelism (agents running simultaneously on separate pods)
- Per-agent versioning (e.g. deploy `vss-agent` v2 without touching `sherlock-lead`)
- Production Kubernetes (health checks, auto-scaling, rolling updates per agent)
- Typed, logged Hermes message audit trail (stronger than SSE `intermediate_data:` events)



### Migration tasks

- [ ] Restructure Sherlock prompts: `deploy/aiq-prompts/shallow_researcher/researcher.j2` → `sherlock-lead/PERSONA.md`, `TOOLS.md`, `SKILLS.md`
- [ ] Restructure VSS sub-agent: MCP config → `vss-agent/PERSONA.md` + `vss-agent/TOOLS.md` (separate pod)
- [ ] Replace AI-Q workflow routing with a Hermes orchestrator service
- [ ] Replace `clarifier_agent.enable_plan_approval` (SSE-based HITL) with `Hermes HumanApprovalMessage`
- [ ] Deploy on OpenShift: one pod per agent (`sherlock-lead`, `vss-agent`, `hermes-orchestrator`)
- [ ] Migrate storage connections (Elasticsearch, Neo4j, Postgres) — unchanged, just re-point env vars
- [ ] Validate HITL flow end-to-end on Hermes: investigator approval message → Sherlock continues plan



### OpenShell (filesystem + network enforcement)

- [ ] Evaluate OpenShell for policy enforcement on air-gapped nodes: block unauthorized filesystem paths, restrict outbound network to defined endpoints only
- [ ] Define per-agent OpenShell policy: what paths and network endpoints each pod is permitted to access
- [ ] Test that OpenShell blocks agent attempts to access cross-case data or call external APIs

---



## Track 6 — Evidence CRUD (future)

> Currently all ingestion is Create-only. Investigation workflow requires full CRUD.

- [ ] **nv-ingest on-demand in workbench upload** — `POST /api/cases/upload` should auto-start
  `compose-nv-ingest-ms-runtime-1` before calling the ingestor and stop it after completion.
  nv-ingest uses ~10 GB RAM at idle; keeping it stopped between uploads is necessary on
  machines where RAM is shared with VSS + MERaLiON. Wire `docker start/stop` into
  `ui/server.py`'s upload handler so developers don't have to manage it manually.

- [ ] **Delete case evidence from RAG** — remove specific documents from `multimodal_data` collection when evidence is retracted or case is closed. RAG Blueprint ingestor has `DELETE /v1/documents/{id}` — wire it to workbench.
- [ ] **Delete case entities from Neo4j** — `MATCH (n {case_id: $id}) DETACH DELETE n` when case is archived.
- [ ] **Update evidence** — re-upload replaces same filename in RAG (already works via filename key). Neo4j MERGE handles entity updates. Document for operators.
- [ ] **Case archival flow** — mark case closed → remove from active RAG collection → archive to cold storage. Needed for production air-gapped deployment.