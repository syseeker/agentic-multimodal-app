# Phase 2 — RAG Blueprint · Deployment Proof

**NVIDIA skills followed:**
- `rag-blueprint` v2.6.0 — SKILL.md + ALL references/ + references/configure/ read in full
- `aiq-deploy` — `references/frag.md` read for FRAG wiring

**References used (in order):**
`SKILL.md` · `references/deploy.md` · `references/deploy/docker-nvidia-hosted.md`
· `references/configure/agentic-rag.md` · `references/configure/mcp.md`
+ canonical deploy doc: `external/rag/docs/deploy-docker-nvidia-hosted.md`
+ FRAG wiring: `~/skills/skills/aiq-deploy/references/frag.md`

**Goal (DESIGN.md Phase 2):** RAG Blueprint as AI-Q's knowledge layer via FRAG.
Agentic RAG enabled. AI-Q queries produce cited answers from ingested documents.

---

## What the previous agent missed (lessons from Phase 3 failures)

1. **Agentic RAG not enabled** — previous agent never set `ENABLE_AGENTIC_RAG=true`.
   RAG-BP has its own LangGraph pipeline (planner→task executor→seed generator→synthesis)
   that produces dramatically better cited answers than basic RAG.
2. **Shallow skill reading** — previous agent read only deployment files, skipped
   `references/configure/agentic-rag.md` and `references/configure/mcp.md`.
3. **NVIDIA_BUILD_API_KEY gotcha** — the nv-ingest compose YAML maps
   `NVIDIA_BUILD_API_KEY=${NGC_API_KEY}`. NGC_API_KEY must have API inference scope
   (not just NGC Catalog scope) for embedding calls to work.
4. **nvdev.env must be sourced before every compose up/down** — RAG compose stacks
   use cloud endpoints only when nvdev.env is sourced first. Without it, containers
   start with self-hosted container names (e.g. `nemotron-ocr:8000`) that don't exist.

---

## Steps Executed — Skill Reference → Command → Actual Result

| # | Skill ref | Action | Actual result |
|---|---|---|---|
| 1 | `deploy/docker-nvidia-hosted.md` prereq | Disk space check | 521GB free ✓ |
| 2 | `deploy/docker-nvidia-hosted.md` step 4 | `docker login nvcr.io` with NGC_API_KEY (NGC Catalog scope) | `Login Succeeded` ✓ |
| 3 | `deploy/docker-nvidia-hosted.md` step 3 | `source nvdev.env && docker compose -f vectordb.yaml up -d` | `elasticsearch`, `seaweedfs` started; `nvidia-rag` network created ✓ |
| 4 | `deploy/docker-nvidia-hosted.md` step 4 | `docker compose -f docker-compose-ingestor-server.yaml up -d` | `ingestor-server`, `compose-nv-ingest-ms-runtime-1`, `compose-redis-1` started ✓ |
| 5 | `configure/agentic-rag.md` | Start rag-server with `ENABLE_AGENTIC_RAG=true` | `rag-server`, `rag-frontend` started ✓ |
| 6 | `deploy/docker-nvidia-hosted.md` step 6 | Health check: `curl :8082/v1/health?check_dependencies=true` | Embeddings, SummaryLLM, ES, SeaweedFS, Redis all healthy ✓ |
| 7 | `deploy/docker-nvidia-hosted.md` step 6 | Health check: `curl :8081/v1/health?check_dependencies=true` | LLM, Embeddings, Ranking, ES, SeaweedFS all healthy ✓ |
| 8 | `frag.md` (aiq-deploy) | Set `RAG_SERVER_URL=http://rag-server:8081/v1`, `RAG_INGEST_URL=http://ingestor-server:8082/v1`, `BACKEND_CONFIG=config_web_frag.yml`, `COLLECTION_NAME=multimodal_data` in AI-Q deploy/.env | applied ✓ |
| 9 | `frag.md` (aiq-deploy) | Restart amms-aiq-agent; `docker network connect nvidia-rag amms-aiq-agent` | AI-Q can reach `rag-server:8081` and `ingestor-server:8082` from inside container ✓ |
| 10 | Manual verification | Ingest test forensic doc to `multimodal_data` collection | `documents_completed: 1 / 1` ✓ |
| 11 | `configure/agentic-rag.md` | Direct RAG query confirming agentic pipeline | "John Doe, age 42… DNA #DNA-7731" with citation `test_case.txt score: 0.886` ✓ |
| 12 | `frag.md` (aiq-deploy) | AI-Q FRAG end-to-end: `aiq.py chat "What evidence in SC-2024-001?"` | "DNA evidence reference #DNA-7731… References: [1] test_case.txt" ✓ |

**Gate: PASSED** — AI-Q Sherlock produces cited answers from RAG Blueprint knowledge base.

---

## Container Inventory (all services up)

| Container | Image | Ports | Purpose |
|---|---|---|---|
| `elasticsearch` | `docker.elastic.co/elasticsearch:9.3.0` | `9200` (internal) | Vector store (default for RAG-BP) |
| `seaweedfs` | `chrislusf/seaweedfs:3.73` | `9010` (internal) | Object store (document blobs) |
| `compose-redis-1` | `redis` | internal | Task queue for nv-ingest |
| `compose-nv-ingest-ms-runtime-1` | `nvcr.io/nvidia/nv-ingest:...` | internal | NV-Ingest extraction pipeline |
| `ingestor-server` | `nvcr.io/nvidia/blueprint/ingestor-server:2.6.0` | `0.0.0.0:8082→8082` | Ingestion API |
| `rag-server` | `nvcr.io/nvidia/blueprint/rag-server:2.6.0` | `0.0.0.0:8081→8081` | RAG query/generate API |
| `rag-frontend` | `nvcr.io/nvidia/blueprint/rag-frontend:2.6.0` | `0.0.0.0:3001→3001` | RAG UI (not used in Sherlock) |

All on Docker network `nvidia-rag`. AI-Q container `amms-aiq-agent` also connected to `nvidia-rag` via `docker network connect`.

---

## Agentic RAG

Enabled via `ENABLE_AGENTIC_RAG=true` in the shell environment when starting rag-server.
The RAG-BP LangGraph pipeline (planner → task executor → seed generator → synthesis)
runs on every query. All four agentic LLMs use `nvidia/nemotron-3-super-120b-a12b`
via the NVIDIA API Catalog (cloud-hosted, no GPU required).

**WARNING:** Agentic RAG bypasses NeMo Guardrails inside RAG-BP.
Guardrails must be applied at the AI-Q layer (Phase 7).

---

## FRAG Wiring (AI-Q → RAG Blueprint)

```
AI-Q config: config_web_frag.yml
  knowledge_search:
    backend: foundational_rag
    rag_url: http://rag-server:8081/v1       ← RAG_SERVER_URL env var
    ingest_url: http://ingestor-server:8082/v1  ← RAG_INGEST_URL env var
    collection_name: multimodal_data         ← COLLECTION_NAME env var
```

AI-Q's FRAG adapter calls `POST /v1/search` with `collection_names: ["multimodal_data"]`.
AI-Q container joined to `nvidia-rag` network to resolve container names.

---

## Key Gotchas (must-know for on-prem replay)

### 1. Single NGC API key must have BOTH scopes
The RAG Blueprint compose YAML maps `NVIDIA_BUILD_API_KEY=${NGC_API_KEY}` in nv-ingest.
This means `NGC_API_KEY` is used for BOTH image pulls (nvcr.io) AND inference API calls.
The key at ngc.nvidia.com must have:
- **NGC Catalog** scope → image pulls from nvcr.io
- **AI Foundations** or **API** scope → hosted NIM inference calls

**Workaround with two separate keys:**
- Log in to nvcr.io with the registry key first (`docker login nvcr.io -u '$oauthtoken' --password-stdin`)
- Then set `NGC_API_KEY` = inference key when sourcing nvdev.env and running compose
- Docker uses `~/.docker/config.json` for image pulls (not the runtime env var)

### 2. Always source nvdev.env before compose up/down
```bash
cd external/rag
source deploy/compose/nvdev.env
export NVIDIA_API_KEY=<inference-key>
export NGC_API_KEY=<inference-key>   # see note above
```
Without this, nv-ingest gets self-hosted container names (nemotron-ocr:8000 etc.) that
don't exist in NVIDIA-hosted mode.

### 3. propagate_env.sh does not handle RAG Blueprint's compose .env
RAG Blueprint's `deploy/compose/.env` uses `export KEY=${OTHER_KEY}` format.
Shell env vars set before compose up always take precedence over the `.env` file.
Do NOT use propagate_env.sh for RAG Blueprint — set via shell before compose.

### 4. Default RAG collection is `multimodal_data`
AI-Q FRAG config (`config_web_frag.yml`) defaults to `collection_name: ${COLLECTION_NAME:-test_collection}`.
Set `COLLECTION_NAME=multimodal_data` in AI-Q deploy/.env to match RAG-BP default.

### 5. FRAG adapter uses `collection_names` (plural array) not `collection_name`
The search call is: `POST /v1/search {"collection_names": ["multimodal_data"], ...}`.
The collection must exist in Elasticsearch or the call returns HTTP 400.

---

## On-Prem Replay (air-gapped — images pre-pulled)

```bash
# Pre-pull images on internet-connected machine, then transfer
docker pull docker.elastic.co/elasticsearch/elasticsearch:9.3.0
docker pull chrislusf/seaweedfs:3.73
docker pull nvcr.io/nvidia/blueprint/ingestor-server:2.6.0
docker pull nvcr.io/nvidia/blueprint/rag-server:2.6.0
# (save with docker save | gzip > images.tar.gz, load on air-gapped machine)

# On air-gapped machine:
cd /path/to/agentic-multimodal-app/external/rag
source deploy/compose/nvdev.env
export NGC_API_KEY=<self-hosted-or-inference-key>
export NVIDIA_API_KEY=<self-hosted-nim-key>

docker compose -f deploy/compose/vectordb.yaml up -d
docker compose -f deploy/compose/docker-compose-ingestor-server.yaml up -d
ENABLE_AGENTIC_RAG=true docker compose -f deploy/compose/docker-compose-rag-server.yaml up -d

# Wire AI-Q
docker network connect nvidia-rag amms-aiq-agent
```

For air-gapped, switch NIM endpoints in nvdev.env from `integrate.api.nvidia.com`
to your on-prem NIM endpoints. All model names remain the same.
