# Phase Implementation Status

Last updated: 2026-06-28
Instance: New instance (previous instance ran out of disk space mid-Phase 3)

---

## Status Table

| Phase | Goal | Status | Notes |
|---|---|---|---|
| 0 | Design sign-off | ✅ Complete | DESIGN.md is the signed-off authoritative design |
| 1 | AI-Q backend (headless, web OFF) | ⬜ Not deployed on this instance | PHASE1_AIQ.md documents what was done on previous instance. Must redo. |
| 2 | RAG Blueprint + FRAG wiring | ⬜ Not deployed on this instance | PHASE2_RAG.md documents previous instance. Must redo. |
| 3 | Forensic config + demo cases | ⬜ Not started (lost with previous instance) | Partially done on previous instance; lost when disk ran out. |
| 4 | Audio: Parakeet ASR + MERaLiON | ⬜ Not started | |
| 5 | VSS (lvs) + Neo4j CA-RAG | ⬜ Not started | |
| 6 | Non-video ER → Neo4j + cuGraph | ⬜ Not started | |
| 7 | Extend AI-Q (vss-agent MCP, tools, forensic prompts, HITL) | ⬜ Not started | |
| 8 | Custom case-workbench UI | ⬜ Not started | |
| 9 | Observability / eval / benchmark | ⬜ Not started | |

---

## What Was Confirmed on Previous Instance

### Phase 1 (AI-Q backend) — previously confirmed, NOT on this instance
Documented in `deploy/PHASE1_AIQ.md`:
- AI-Q v2.1.0 deployed headless under Docker project `amms`
- Container: `amms-aiq-agent` on host port 8100
- Health check: `curl -sf http://localhost:8100/health` → `{"status":"healthy"}`
- Web search OFF (config_web_default_llamaindex.yml)
- Agents: `deep_researcher`, `shallow_researcher`

### Phase 2 (RAG Blueprint) — previously confirmed, NOT on this instance
Documented in `deploy/PHASE2_RAG.md`:
- RAG Blueprint v2.6.0 deployed (Elasticsearch, NVIDIA-hosted NIMs)
- Wired as AI-Q's FRAG (AI-Q config updated to config_web_frag.yml)
- Containers: elasticsearch, seaweedfs, ingestor-server, nv-ingest, redis, rag-server, rag-frontend
- RAG-BP connected to AI-Q over `nvidia-rag` Docker network
- **Design correction confirmed**: vector store is Elasticsearch (not Milvus as originally assumed)

### Phase 3 — partial, lost
- Some forensic prompts/config may have been written on the previous instance
- Demo case data may have been partially generated
- All lost when previous instance's disk ran out
- Must redo from scratch starting from Phase 1

---

## What To Do Next

**Start at Phase 1 on this new instance.**

Before each phase:
1. Read the relevant skill's MD files at `~/skills/skills/<skill-name>/`
2. Read `.claude/skills/<skill>.md` for the extracted SME summary
3. Follow the skill strictly — no improvising
4. Verify at the checkpoint
5. Update this file

---

## Update Log

| Date | Update |
|---|---|
| 2026-06-28 | New instance started. Previous instance lost at Phase 3 (disk full). Phase 1 and 2 need redeployment. .claude/ directory created with full institutional knowledge. |
