# Phase Status

Last updated: 2026-07-28

> **⛔ Remote-GPU (PATH B) is gone.** Tailscale CPU+GPU split proven not to work.
> VSS runs on the machine that has the GPU. See implementation-learnings.md.

## ✅ RTX Pro 6000 (x86_64) — Phases 1–8 + video pipeline complete (2026-07-28, Boon Ping)

Single machine: RTX Pro 6000 Blackwell Server Edition, 96 GB GDDR7, x86_64, Brev instance.

### Phase deployment order: 1 → 2 → 5 → 3 → 4 → 6 → 7 → 8

- ✅ **Phase 1** AI-Q :8100 (config_sherlock_frag.yml → config_sherlock_frag_mcp.yml after Phase 7)
- ✅ **Phase 2** RAG Blueprint (rag-server :8081, ingestor :8082, nv-ingest, VSS-owned ES+Redis)
  - `ingest_start.sh` / `ingest_stop.sh` — clean nv-ingest lifecycle (ENABLE_REDIS_BACKEND=True)
- ✅ **Phase 5 PATH A** VSS LVS profile, local GPU, RTXPRO6000BW hardware profile
  - Cosmos Reason2-8B VLM in rtvi-vlm (~46 GB VRAM); Nemotron Nano 9B LLM (remote NIM)
  - `patch_vss_rtvi_vlm.sh` MUST run after every Phase 5 re-deploy (model name + VIOS URL patches)
  - **rtvi-vlm patches applied** (in container writable layer — lost on recreate, re-apply with script):
    - `rtvi_vlm_server.py`: normalize model name (accept friendly name aliases for nim_ format)
    - `asset_manager.py`: VIOS UUID fallback (name-based GET 400 → UUID timelines lookup); use json.loads(text()) not .json() for text/plain VIOS responses; use 172.31.33.197 directly (not host.docker.internal)
  - **AI-Q asyncio patch**: `nat/runtime/runner.py` — wrap context resets in try/except ValueError to prevent MCP tool results being dropped on cross-task ContextVar reset
- ✅ **Phase 3** 21 forensic cases ingested (multimodal_data, VSS-owned ES); CASE_LIMIT=N supported
- ✅ **Phase 4** Audio pipeline: Magpie TTS + Parakeet ASR + MERaLiON-3-10B paralinguistics
  - MERaLiON transformers==4.50.1, pad_token_id patch, 16kHz resample, new-token-only output
  - `process_audio.py --file <name>` for single-file processing; `analyze_audio` MCP tool
- ✅ **Phase 6** Neo4j entity graph; GRAPH_CASE_LIMIT env var for partial ingest
- ✅ **Phase 7** Sherlock MCP :9901 (graph + audio tools) + VSS Sherlock MCP :9903 (video tools)
  - `ask_video` / `summarize_video`: direct rtvi-vlm `/v1/chat/completions` (4-8s, 1fps frames)
  - VIOS UUID resolution: timelines → UUID → temp_files URL (172.31.33.197 not host.docker.internal)
  - MCP tool_call_timeout: 300s (was 60s — video inference takes 4-8s but chain overhead)
  - `start_all.sh` includes VSS as step 0 (owns ES+Redis; must start before RAG)
- ✅ **Phase 8** Workbench :8200 — 21 cases, full multimodal pipeline working
  - Stop button (■) in chat UI to cancel in-flight queries
  - Paralinguistics tab before Evidence tab; FPS frame sampling for video VLM

### Video pipeline E2E verified (2026-07-28)
- Homicide case men_assault.mp4: green bottle assault, victim falls, attacker flees — 4.3s inference
- Drug trafficking drug-seize.mp4: tactical team, 250g white powder, arrest — 4.3s inference
- Both verified with `[1] mcp_vss_agent__summarize_video` citation in Sherlock UI

### Open items on this instance
- nv-ingest auto-start/stop in workbench upload not yet implemented
- Persist video VLM analysis to RAG + Neo4j (currently chat-only)
- VSS rtvi-vlm patches lost on container recreate — `patch_vss_rtvi_vlm.sh` must be re-run

### Recommended phase order: **1 → 2 → 5 → patch_vss → 3 → 4 → 6 → 7 → 8**

---

## 🟡 DGX Spark (ARM64/GB10) — Track-1 partial (2026-07-12, Jovan — pending Phase 5 + MERaLiON)
Working on TODO.md **Track 1** on the DGX Spark box (`spark-d10008`, `/home/nvidia/test/…`).
Details in `implementation-learnings.md` → "DGX Spark (ARM64) — Track-1 Tests…". This work is
folded into a single squashed commit on the `dev` branch.
- ✅ **22 Test case upload** — `POST /api/cases/upload` → case + metadata + listing verified.
- ✅ **23 Test audio evidence** — Magpie TTS → Parakeet transcript → RAG ingest → retrieval (E2E).
- ✅ **26 doc** Neo4j→FalkorDB swap · ✅ **27 doc** ES→ChromaDB swap (Chroma not native; LanceDB is the config swap).
- ⬜ **21** E2E investigator flow
- ⬜ **24** video via VSS→Neo4j→MCP — Phase 5 (VSS LVS) **not yet deployed on GB10**. `phase5_vss.sh` has aarch64 PATH A ready (`dev-profile.sh -p base -H DGX-SPARK`). After Phase 5, run `patch_vss_rtvi_vlm.sh` (see RTX Pro 6000 learnings above).
- ⬜ **25** real MERaLiON-3 paralinguistics — `process_audio.py` aarch64 path should work but not yet tested; audio evidence on DGX Spark still runs stub paralinguistics.
- ⚠️ **Open bug:** `amms-workbench` lacks `networkx`/`openai` + `NVIDIA_API_KEY` → on-upload
  entity extraction crashes silently → uploaded cases show an empty graph. Fix in `compose.workbench.yaml`.
- ⚠️ **Operational:** nv-ingest Ray spill is capped (tmpfs `/tmp:16g`); run nv-ingest **on-demand**,
  never idle-co-running with VSS (128 GB UMA contention). See the disk-fill root cause in learnings.

## ✅ FULL E2E VALIDATION (2026-07-04, fresh 15 GB instance)
Ran Phases 1→2→3→4→6→7→8 from scratch (Phase 5 skipped — needs GPU). **All 7 passed
end-to-end.** Found & fixed **7 fresh-instance deploy blockers** not yet handled by the
scripts (see `implementation-learnings.md` → "Fresh-Instance E2E Validation (2026-07-04)"):
1. `phase3_data_sim.sh` — create collection via singular `/v1/collection` (creates the
   `metadata_schema` index; array-form `/v1/collections` does not → all ingests 404)
2. `phase3_data_sim.sh` — success detection keyed off `documents_completed`/`message`,
   not the nonexistent `status` field (was mislabeling every success as FAILED)
3. `compose.amms.override.yaml` — set `RAG_SERVER_URL`/`RAG_INGEST_URL` (with `/v1`) +
   `COLLECTION_NAME` (FRAG defaulted to localhost → AI-Q retrieved nothing)
4. `phase4_audio.sh` — audio-file count via `find` filtering, not `grep -v` (aborted
   under `set -euo pipefail` when only `.gitkeep` present)
5. `phase7_extensions.sh` — reconnect `nvidia-rag` after AI-Q force-recreate (else FRAG breaks)
6. `phase7_extensions.sh` — load+export `NVIDIA_API_KEY`/`NGC_API_KEY` before the MCP compose
   and `source nvdev.env` (blank key + `set -u` abort)
7. `graph/tools.py` — OpenAI client `timeout=120` (a hung extraction stalled the whole batch)

Verified: 85 files → 186 chunks; AI-Q FRAG cited answer (SC-2024-873A3944, Nguyen Van Thanh);
Neo4j graph tools (suspect ranked #1 centrality); MCP both data sources; workbench SSE cited
answer via shallow_research_agent. Streaming watch-item resolved: committed config is fine.
RAM note: nv-ingest ≈ 8–9 GB; stop ingestion-only services after ingest to free headroom.

## Phase 0 — Design ✅
DESIGN.md is the signed-off authoritative design document.

## Phase 1 — AI-Q Backend ✅
Deployed on this instance. See `deploy/PHASE1_AIQ.md` for proof.
- `amms-aiq-agent` running on :8100 (FRAG mode, `config_web_frag.yml`)
- `amms-aiq-postgres` running (internal only)
- BACKEND_CONFIG switched to `config_web_frag.yml` after Phase 2

## Phase 2 — RAG Blueprint ✅
Deployed on this instance. See `deploy/PHASE2_RAG.md` for proof.
- `elasticsearch` + `seaweedfs` on `nvidia-rag` network
- `ingestor-server` on :8082, `rag-server` on :8081
- `ENABLE_AGENTIC_RAG=true` (LangGraph plan-execute pipeline)
- FRAG wired: AI-Q → `http://rag-server:8081/v1` (COLLECTION_NAME=multimodal_data)
- End-to-end verified: ingest → query → cited answer with source attribution

## Phase 3 — Data Simulation ✅
See `deploy/PHASE3_DATA_SIM.md` for full proof table. See `implementation-learnings.md` Phase 3 section for gotchas.

**Completed (sim-case-text):**
- 20 synthetic Singapore forensic cases generated via `data-designer` v0.7.0
- Model: `nvidia-text` (nemotron-3-nano-30b-a3b), 120/120 tasks ok
- Config: `data/sim/forensic_cases.py` — 16 columns, Singapore-specific context
- Case folders: `data/cases/<SC-2024-XXXXXXXX>/` — case_report.txt, witness_statement.txt, lab_report.txt, whatsapp_chat.txt, metadata.json, + audio/images/video placeholder dirs
- 80/80 files ingested to RAG BP (`multimodal_data` collection)
- End-to-end verified: AI-Q Sherlock cited correct case, suspect, evidence, WhatsApp chat

**Optional (post-Phase 9):**
- sim-case-audio: Magpie TTS (Riva) for witness interviews + MERaLiON for Singlish/Southeast Asian audio
- sim-case-images: static fixtures — no general-purpose forensic image generation NIM exists in skills catalog
- sim-case-video: static MP4 fixtures — no text-to-video NIM; Cosmos Transfer is augmentation-only

**Git strategy:**
- `data/sim/*.py`, `data/sim/*.sh` — committed
- `data/sim/artifacts/` — gitignored (large parquet, regenerate with forensic_cases.py)
- `data/cases/<id>/*.txt` + `metadata.json` + `.gitkeep` — committed
- `data/cases/<id>/audio|images|video` actual files — gitignored (future large media)

## Phase 4 — Audio Pipeline ✅
See `deploy/PHASE4_AUDIO.md`. See `implementation-learnings.md` Phase 4 section.

**Completed:**
- `data/audio/process_audio.py`: full pipeline — scan audio dirs → normalize (ffmpeg/soundfile) → Parakeet RNNT Multilingual (cloud gRPC) → transcript files → audio_analysis.txt → RAG BP ingest
- `data/sim/generate_audio_samples.py --test-tone`: synthetic WAV for pipeline testing (replaces deleted `data/audio/generate_test_audio.py`)
- Model: Parakeet RNNT Multilingual (`ai-parakeet-1_1b-rnnt-multilingual-asr`) — multilingual for Singapore forensic context
- FID discovered at runtime via NVCF API (never hardcoded)
- End-to-end verified: synthetic WAV → Parakeet gRPC → transcript → RAG BP ingested
- MERaLiON paralinguistics: STUB in `process_audio.py::meralion_paralinguistics()` — Phase 7
- RAG Blueprint API corrected: `POST /documents`, field `documents=@file` (not `/v1/documents`, `file=@`)
- `data/sim/ingest_cases.sh` updated with corrected API endpoint/field

## Phase 5 — VSS LVS Profile ✅ (partial — GPU pending)
See `deploy/PHASE5_VSS.md` for full proof and gotchas.

**Complete:**
- vss-agent healthy at :8000 (`{"isAlive":true}`)
- Elasticsearch, Redis, Kafka, Logstash, Kibana, Phoenix, VST stack — all running
- VSS owns shared Elasticsearch (9200) and Redis (6379)
- resolved.yml patched for remote-all (nvidia runtime + GPU devices removed from rtvi-vlm, sensor-ms, streamprocessing-ms)

**Deferred (GPU instance — RTX PRO 6000 Blackwell):**
- rtvi-vlm — needs NVDEC hardware GPU decoder even in remote-all mode
- vss-lvs — waits for rtvi-vlm
- MCP enable (LVS_ENABLE_MCP) — Phase 7 step

**Config:** `RTVI_VLM_URL=http://<GPU_IP>:8018` in generated.env when GPU ready.
**Hardware profile:** `RTXPRO6000BW` (RTX PRO 6000 Blackwell, 96 GB VRAM).
**Production end-state:** GB10 (DGX Spark, 128 GB).

## Phase 6 — Non-video ER → Neo4j ✅
See `deploy/PHASE6_GRAPH.md` for full proof.

- Neo4j Community running (`amms-neo4j`, :7474 browser, :7687 Bolt)
- `graph/tools.py`: extract_entities, graph_query, graph_analyze — all verified
- `graph/ingest_entities.py`: batch runner, wired into `data/sim/ingest_cases.sh`
- 20-case ER ingest completed; entities + relations in Neo4j per case
- graph_analyze centrality correctly ranks suspects as highest-centrality nodes
- Phase 7: register tools into AI-Q as custom skills

## Phase 7 — AI-Q Extensions ✅
See `deploy/PHASE7_EXTENSIONS.md` for full proof.

- Sherlock MCP server running (`amms-sherlock-mcp`, :9901) — graph_query, graph_analyze, extract_entities, list_cases
- AI-Q on `config_sherlock_frag.yml`: web search OFF, MCP graph tools + RAG-BP
- Data sources: `Case Documents` (RAG) + `Case Graph` (MCP) ✅
- Forensic prompts: shallow_researcher + clarifier patched (Sherlock SPF persona)
- Safety policy: `guardrails/sherlock_forensic_safety_v1.0.0.md` (enforce at Phase 9 with GPU)
- VSS MCP (`vss-agent`): deferred — uncomment in config when GPU ready + `LVS_ENABLE_MCP=true`

## Phase 8 — Case Workbench UI ✅
See `deploy/PHASE8_WORKBENCH.md` for full proof.

- FastAPI backend (`ui/server.py`) running on :8200 — verified: health OK, 20 cases loaded, graph OK, evidence OK
- Svelte SPA (`ui/src/`): App + CaseSelector + ChatPanel (SSE + HITL) + GraphPanel (Cytoscape) + EvidenceViewer + SentimentPanel
- HITL: plan detection heuristic (≥3 numbered steps OR "plan" heading) → Approve/Reject banner
- Graph: 25 nodes + 27 edges rendered for SC-2024-03C5F0E4 (verified Neo4j → Cytoscape format)
- Docker: `ui/Dockerfile` multi-stage (node:20 build + python:3.11 serve); `deploy/compose.workbench.yaml`
- Dev mode: `python3 ui/server.py` + `cd ui && npm run dev` (proxies /api to :8200)

## Phase 9 — Observability, Evaluation, Profiling & Guardrails ⬜
Full plan: `deploy/PHASE9_PLAN.md` — read this before starting anything.

Sub-phases (each ends with a verification gate + PHASE9X_*.md proof file):

### 9a — Observability (Phoenix) ⬜
- Start Phoenix server; add `general.telemetry.tracing.phoenix` to `config_sherlock_frag.yml`
- Gate: Phoenix trace tree visible for a live Sherlock query (agent steps, tool calls, token counts, latency)
- Source: `external/aiq/docs/source/deployment/observability.md`

### 9b — Evaluation: AI-Q layer (`nat eval` + LLM judge) ⬜
- Build `eval/sherlock_eval_dataset.json` (20 forensic Q&A pairs, nat eval format)
- Write `eval/config_sherlock_eval.yml` with LLM-as-judge evaluator
- Run `dotenv -f deploy/.env run nat eval --config_file eval/config_sherlock_eval.yml`
- Gate: scores for all 20 questions; citation_present = 1.0 baseline
- Source: `external/aiq/docs/source/evaluation/`

### 9b-rag — Evaluation: RAG-BP layer (`rag-eval` skill, RAGAS) ⬜
- Build `eval/rag-eval-dataset/` (corpus/ symlink + train.json in RAGAS format)
- Run `uv run --project scripts/eval python scripts/eval/evaluate_rag.py` from external/rag root
- Gate: faithfulness ≥ 0.8, context_precision ≥ 0.7 for all 20 questions
- Source: `~/skills/skills/rag-eval/` (read ALL files)
- **Why:** isolates RAG retrieval quality from AI-Q synthesis quality — needed to diagnose which layer causes score drops

### 9c — Profiling: AI-Q layer (`nat eval` + profiler + tokenomics) ⬜
- Add `profiler:` block to eval config; run `nat eval`; generate tokenomics HTML report
- Gate: `tokenomics_report.html` opens; bottleneck step identified and documented
- Source: `external/aiq/docs/source/profiling/index.md`

### 9c-rag — Profiling: RAG-BP layer (`rag-perf` skill, aiperf) ⬜
- Configure `eval/config_rag_perf_sherlock.yaml` (collection_names: ["multimodal_data"])
- Run `rag-perf -c eval/config_rag_perf_sherlock.yaml` from external/rag root
- Gate: stage breakdown (retrieval / reranker / synthesis) with bottleneck flag
- Source: `~/skills/skills/rag-perf/` (read ALL files)
- **Why:** reveals bottleneck INSIDE the FRAG call that nat eval profiler cannot see

### 9d — Guardrails & Content Safety ⬜
- Read `nemotron-policy-generator` skill (ALL files); generate forensic safety policy
- Deploy Nemotron-Content-Safety-Reasoning-4B; wire into AI-Q via NeMo Guardrails
- Gate: jailbreak prompt blocked; Phoenix trace shows rail activation
- Source: `~/skills/skills/nemotron-policy-generator/` + NeMo Guardrails docs

### Deferred (needs GPU or cloud)
- Nsight GPU profiling (needs RTX PRO 6000 / GB10)
- aiperf concurrent user load test (rag-perf skill)
- Nemotron-3-Content-Safety multimodal (needs GPU)
- OTEL Collector → Grafana Tempo for production air-gapped observability
- Full regression eval suite across all 20 cases

## Key deployment notes
- Always `source external/rag/deploy/compose/nvdev.env` before any RAG compose command
- NGC_API_KEY must have BOTH NGC Catalog AND AI Foundations scope
  OR: use registry key for docker login, then set NGC_API_KEY=inference key for compose
- After any rag-server recreate: `docker network connect nvidia-rag amms-aiq-agent`
