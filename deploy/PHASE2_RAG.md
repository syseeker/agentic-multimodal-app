# Phase 2 — RAG Blueprint as AI-Q FRAG · proof of skill use ✅

**NVIDIA skills used:** `nvidia/skills → rag-blueprint` (deploy) + `aiq-deploy → references/frag.md` (wire).
Refs followed: `rag-blueprint/references/deploy.md`, `.../deploy/docker-nvidia-hosted.md`,
the RAG repo's `docs/deploy-docker-nvidia-hosted.md`, and `aiq-deploy/references/frag.md`.

**Goal (DESIGN.md Phase 2):** deploy the RAG Blueprint and wire it as AI-Q's FRAG
retrieval substrate, into the harmonized `amms` stack.

## Design correction made first (no silent drift)
DESIGN said "one Milvus (cuVS)". Verified that was wrong: RAG-BP
(`docker-nvidia-hosted.md`: "use **default Elasticsearch**") and VSS CA-RAG
(`elasticsearch_db`) both **default to Elasticsearch**; Milvus/cuVS is an optional
GPU swap. DESIGN/README/QUICKSTART amended to **Elasticsearch** before deploying
(commit `5f5f686`).

## Steps executed (each maps to a skill instruction)

| # | Skill ref | Action | Result (evidence) |
|---|---|---|---|
| 1 | `deploy.md` Phase 1 | env analysis | no GPU → **nvidia-hosted** mode (`deploy.md` Phase 4) |
| 2 | `docker-nvidia-hosted.md` | `docker login nvcr.io` with the key | `Login Succeeded` |
| 3 | `locate-or-clone` (repo) | clone RAG-BP fresh `external/rag`, checkout **v2.6.0** | compose files present |
| 4 | single `.env` (our overlay) | `propagate_env.sh` → key into root `.env`; `export NGC_API_KEY`; `source nvdev.env` | cloud endpoints + shared models loaded |
| 5 | `docker-nvidia-hosted.md` | `vectordb.yaml up` (project `amms`) | **Elasticsearch + SeaweedFS** healthy |
| 6 | `docker-nvidia-hosted.md` | `docker-compose-ingestor-server.yaml up` | ingestor + nv-ingest + redis up |
| 7 | `docker-nvidia-hosted.md` | `docker-compose-rag-server.yaml up` | rag-server + rag-frontend up |
| 8 | `docker-nvidia-hosted.md` | health (`?check_dependencies=true`) | rag-server + ingestor: **ES, object-store, NIMs (LLM nemotron-3-super-120b, embed llama-nemotron-embed-vl-1b-v2), NV-Ingest all healthy** ("Using NVIDIA API Catalog") |
| 9 | `frag.md` + `configs.md` | AI-Q `.env`: `BACKEND_CONFIG=config_web_frag.yml`, `RAG_SERVER_URL=http://rag-server:8081`, `RAG_INGEST_URL=http://ingestor-server:8082`; recreate `amms-aiq-agent` | agent restarted on FRAG config |
| 10 | `frag.md` | `docker network connect nvidia-rag amms-aiq-agent` | connected |
| 11 | `frag.md` + `validation.md` | AI-Q `/health`; agent→RAG reachability | `/health` healthy; agent→`rag-server:8081`=**200**, →`ingestor-server:8082`=**200** |

Reproducible: [`deploy/phase2_rag.sh`](phase2_rag.sh). Stack (project `amms`):
`elasticsearch`, `seaweedfs`, `ingestor-server`, `amms-nv-ingest-ms-runtime-1`,
`amms-redis-1`, `rag-server`, `rag-frontend`, plus Phase-1 `amms-aiq-agent` (:8100),
`amms-aiq-postgres`.

## Isolation / harmonization
All RAG-BP services run in project **`amms`** (the harmonized stack). RAG-BP's
default container names/ports were free (the host's existing AI-Q stack is untouched).
Agent↔RAG join via the `nvidia-rag` network (per `frag.md`).

## Notes / caveats
- **Dev vs prod:** NVIDIA-hosted NIMs (key + internet). Air-gapped prod self-hosts
  NIMs on the GPU host (serving phase).
- **frag.md caveat:** if `amms-aiq-agent` is recreated, re-run the `nvidia-rag`
  network connect (TODO: declare `nvidia-rag` as external in the override to persist).
- **Document ingestion** (ingestor `POST /collections` + `POST /documents`) is
  **deferred to Phase 3** ("ingest demo cases; cited deep-research"), done via the
  ingestion skill rather than improvising the API here.

**Gate: PASSED (deploy + wire)** — RAG Blueprint deployed (Elasticsearch, hosted
NIMs), healthy, and wired as AI-Q's FRAG substrate with reachability proven. The
ingest→cite end-to-end is the first task of Phase 3.
