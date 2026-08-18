# Phase Status

Current implementation state. History and root-cause write-ups live in
`implementation-learnings.md` — this file describes only what is true now.

Last updated: 2026-08-18

---

## Status by machine

| | RTX Pro 6000 Blackwell (x86_64, 96 GB) | GB10 / DGX Spark (aarch64, 128 GB UMA) |
|---|---|---|
| Phases 1–4, 6, 7, 8 | ✅ complete | ✅ complete |
| Phase 5 (VSS + video) | ✅ complete, video E2E verified | ⬜ not deployed |
| MERaLiON-3-10B paralinguistics | ✅ real model | ⬜ aarch64 path untested — falls back to stub |
| Phase 9 (observability / eval / profiling / guardrails) | ⬜ not started | ⬜ not started |

**Deployment order: `1 → 2 → 5 → patch_vss_rtvi_vlm → 3 → 4 → 6 → 7 → 8`.**
Phase 5 must precede Phase 3: VSS takes ownership of Elasticsearch and Redis, and the RAG
ingest has to be pointed at VSS's ES.

---

## Phase 0 — Design ✅
`DESIGN.md` is the authoritative design. `DESIGN-EXT.md` maps agents, tools and personas.

## Phase 1 — AI-Q backend ✅
- `amms-aiq-agent` on **:8100**, `amms-aiq-postgres` internal only.
- Active config: `config_sherlock_frag_mcp.yml` (set via `BACKEND_CONFIG`).
- After any AI-Q recreate, re-run `deploy/patch_aiq_runner.sh` — it re-applies the
  `nat/runtime/runner.py` ContextVar patch that stops MCP tool results being dropped, then
  re-attaches the `nvidia-rag` network.

## Phase 2 — RAG Blueprint ✅
- `rag-server` **:8081**, `ingestor-server` **:8082**, nv-ingest, SeaweedFS.
- Elasticsearch and Redis are **owned by VSS** on a GPU box; on a no-VSS box RAG starts its own.
- `ENABLE_AGENTIC_RAG=true` (LangGraph plan-execute).
- FRAG wired: AI-Q → `http://rag-server:8081/v1`, `COLLECTION_NAME=multimodal_data`.
- `ingest_start.sh` / `ingest_stop.sh` manage the nv-ingest lifecycle. Run nv-ingest
  **on demand only** — it must never idle co-run with VSS (memory contention).

## Phase 3 — Data simulation ✅
- **21 forensic cases** generated with NeMo Data Designer (`nvidia/nemotron-3-nano-30b-a3b`).
- Per case: `case_report.txt`, `witness_statement.txt`, `lab_report.txt`,
  `whatsapp_chat.txt`, `metadata.json`, plus `audio/`, `images/`, `video/`.
- Audio simulation via Magpie TTS with per-speaker voice selection; Hokkien statements via
  `MERaLiON-OmniVoice-Hokkien-TTS`. Sample media in `data/audio/sample/`, `data/video/sample/`.
- `CASE_LIMIT=N` supports partial ingest.

## Phase 4 — Audio pipeline ✅
- `data/audio/process_audio.py`: scan → normalise → **Parakeet RNNT Multilingual** (NVCF
  gRPC, function ID discovered at runtime) → transcript → `audio_analysis.txt` → RAG ingest.
- **MERaLiON-3-10B** paralinguistics runs in-process (`transformers`, bf16, sdpa, CUDA).
  Requires a GPU and `HF_TOKEN`; returns a `status: "stub"` dict when either is absent.
  Exposed to Sherlock as the `analyze_audio` MCP tool. ~20 GB VRAM.
  The encoder caps at 30 s per pass, so longer recordings are **split into windows and
  aggregated** — peak stress is reported as the headline (mean alongside), and the
  per-window timeline is returned in `segments` because emotion shifting mid-call is
  itself evidence. Tune with `MERALION_WINDOW_S` / `MERALION_MIN_TAIL_S`.
- `process_audio.py --file <name>` processes a single file.

## Phase 5 — VSS LVS profile ✅ (RTX Pro 6000)
Full record: `deploy/PHASE5_VSS.md`.
- `vss-agent` **:8000**, UI **:7777**, `vss-rtvi-vlm` **:8018**, `vss-lvs` **:38111**.
- The VLM runs on **vLLM inside the rtvi-vlm container** (OpenAI-compatible `/v1`).
- Hardware profile `RTXPRO6000BW`, image tags `3.2.1`. LLM is remote Nemotron Nano 9B.
- **`patch_vss_rtvi_vlm.sh` must be re-run after every Phase 5 re-deploy** — the patches
  live in the container's writable layer and are lost on recreate.
- VSS LVS is **single-machine**: the GPU must be in the box that runs VSS.

## Phase 6 — Entity graph ✅
- Neo4j Community (`amms-neo4j`, :7474 browser, :7687 Bolt).
- `graph/tools.py`: `extract_entities`, `graph_query`, `graph_analyze`.
- `graph/ingest_entities.py` batch runner; `GRAPH_CASE_LIMIT` for partial ingest.
- Entity extraction uses the model in **`LLM_NAME`** (not `LLM_MODEL`).

## Phase 7 — AI-Q extensions ✅
- **Sherlock MCP :9901** — `graph_query`, `graph_analyze`, `extract_entities`, `list_cases`,
  `analyze_audio`.
- **VSS Sherlock MCP :9903** (`mcp/vss_sherlock_mcp.py`) — `list_case_videos`, `ask_video`,
  `summarize_video`. Calls rtvi-vlm `/v1/chat/completions` directly (~4 s); the `vss-lvs`
  `/v1/summarize` path exists as a fallback but has never succeeded here.
- Both registered in `config_sherlock_frag_mcp.yml` with `tool_call_timeout: 300`.
- Web search OFF. Forensic prompts applied to `shallow_researcher` + `clarifier`.
- Safety policy drafted at `guardrails/sherlock_forensic_safety_v1.0.0.md`; enforcement is
  Phase 9d.

## Phase 8 — Case workbench ✅
- FastAPI backend **:8200**; Svelte SPA (chat + HITL, Cytoscape graph, evidence viewer,
  paralinguistics panel).
- HITL plan approval via `detectPlan()` in the workbench (AI-Q's own
  `enable_plan_approval` is off).
- Evidence upload: audio → Parakeet + MERaLiON; video → VIOS registration only (analysis is
  on demand via chat); **images → not implemented** (`data/image/caption_images.py` does not
  exist; the upload response reports `image_caption_unavailable`).

## Phase 9 — Observability, evaluation, profiling, guardrails ⬜
Plan: `deploy/PHASE9_PLAN.md`. Sub-phases 9a Phoenix · 9b `nat eval` · 9b-rag RAGAS ·
9c profiling · 9c-rag `rag-perf` · 9d guardrails.
**9e — inference benchmark (RAG / VLM / MERaLiON)**: `deploy/PHASE9E_INFERENCE_BENCHMARK.md`.

---

## Open items

| Item | Owner / note |
|---|---|
| **VLM identity unresolved** | `phase5_vss.sh` deploys `cosmos-reason1-7b`; `vss_sherlock_mcp.py` requests `nim_nvidia_cosmos-reason2-8b_hf-1208`. Resolve empirically: `curl -s http://<host>:8018/v1/models`. See `deploy/PHASE5_VSS.md`. |
| VLM VRAM figure | Recorded as both ~46 GB and ~62 GB. Phase 9e measures it. |
| Video analysis persists nothing | `summarize_video` re-runs inference per question and writes no ES document, so its citation points at a process, not an artifact. |
| Image captioning not implemented | `data/image/caption_images.py` missing. |

| Phase 5 + MERaLiON on GB10 | Jovan. `phase5_vss.sh` has the aarch64 PATH A ready but unrun. |
| Semantic video search | Needs 2 GPUs (VSS `search` profile). |

## Key deployment notes
- Always `source external/rag/deploy/compose/nvdev.env` before any RAG compose command.
- `NGC_API_KEY` needs both NGC Catalog and AI Foundations scope, or use a registry key for
  `docker login` and an inference key for compose.
- After any rag-server recreate: `docker network connect nvidia-rag amms-aiq-agent`.
- `phase5_vss.sh`'s RAG reconnect step must preserve `APP_*_APIKEY` / `AGENTIC_*_APIKEY` /
  `ENABLE_AGENTIC_RAG`, or agentic RAG silently switches off and the embedder 401s.
