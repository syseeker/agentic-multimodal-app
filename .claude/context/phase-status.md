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

## Phase 3 — Forensic Config + Demo Cases ⬜
Not started on this instance. Previous instance lost (disk space).
Skills to read first: `aiq-deploy` (configs ref) + `data-designer`

## Phases 4–9 ⬜
Not started.

## Key deployment notes
- Always `source external/rag/deploy/compose/nvdev.env` before any RAG compose command
- NGC_API_KEY must have BOTH NGC Catalog AND AI Foundations scope
  OR: use registry key for docker login, then set NGC_API_KEY=inference key for compose
- After any rag-server recreate: `docker network connect nvidia-rag amms-aiq-agent`
