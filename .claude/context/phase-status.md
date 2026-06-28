# Phase Status

Last updated: 2026-06-28

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
- `data/audio/generate_test_audio.py`: synthetic WAV generator for pipeline testing
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

## Phase 8 — Case Workbench UI ⬜
Purpose-built forensic case workbench (not AI-Q's research UI, not VSS's video UI).

## Phase 9 — Eval + Hardening ⬜
Evaluation, hardening, on-prem replay verification.

## Key deployment notes
- Always `source external/rag/deploy/compose/nvdev.env` before any RAG compose command
- NGC_API_KEY must have BOTH NGC Catalog AND AI Foundations scope
  OR: use registry key for docker login, then set NGC_API_KEY=inference key for compose
- After any rag-server recreate: `docker network connect nvidia-rag amms-aiq-agent`
