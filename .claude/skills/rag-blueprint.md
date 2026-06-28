# SME Summary: rag-blueprint skill

Source: `~/skills/skills/rag-blueprint/`
Skill version: 2.6.0 — compatible with RAG Blueprint 2.6.0
Always re-read the full skill files before implementing; this summary is a quick reference.

---

## What This Skill Does

Deploy, configure, troubleshoot, and manage the NVIDIA RAG Blueprint using Docker Compose or Helm.
For this project: Docker Compose deployment with NVIDIA-hosted NIMs (dev mode).

**Autonomy principle from the skill:** Auto-detect everything via commands. Ask only when
user action is required (API key, data deletion, choosing between valid options).

---

## Intent Routing (read the right reference for your task)

| Intent | Reference file |
|---|---|
| Deploy / install / start RAG | `references/deploy.md` |
| Configure a feature | See configure table below |
| Troubleshoot / debug / fix | `references/troubleshoot.md` |
| Stop / shutdown / clean up | `references/shutdown.md` |

---

## Configuration Reference Files

| Feature | Reference |
|---|---|
| VLM / image captioning | `references/configure/vlm.md` |
| Guardrails | `references/configure/guardrails.md` |
| Agentic RAG | `references/configure/agentic-rag.md` |
| Audio ingestion, OCR, batch | `references/configure/ingestion.md` |
| Search, retrieval, hybrid, reranker | `references/configure/search-and-retrieval.md` |
| Model changes, vector DB swap | `references/configure/models-and-infrastructure.md` |
| MCP server/client | `references/configure/mcp.md` |
| Observability (tracing, Grafana) | `references/configure/observability.md` |
| Multimodal query | `references/configure/multimodal-query.md` |
| Evaluation (RAGAS) | `references/configure/evaluation.md` |

---

## Prerequisites

```bash
# Check before deploying
nvidia-smi                          # GPU driver present
docker --version                    # Docker available
docker compose version              # Compose v2
docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi  # GPU accessible to Docker
echo $NVIDIA_API_KEY | wc -c       # API key set (check length only, not value)
df -h /                             # Disk space (need ~20 GB for RAG stack)
```

---

## Deployment Config Locations

| Deployment type | Config location |
|---|---|
| NVIDIA-hosted NIMs (dev) | `external/rag/deploy/compose/nvdev.env` |
| Self-hosted NIMs (prod) | `external/rag/deploy/compose/.env` |

**For this project in dev mode:** use `nvdev.env` profile.

---

## Hardware Restrictions

| GPU | Restriction |
|---|---|
| B200 | No VLM, No Guardrails, No Nemotron Parse |
| RTX PRO 6000 | No Nemotron Parse, No Audio on Helm |

---

## Key Services and Ports

| Service | Default port | Purpose |
|---|---|---|
| rag-server | 8081 | Main RAG API (query endpoint) |
| ingestor-server | 8082 | Document ingestion |
| elasticsearch | 9200 | Vector store |
| seaweedfs | varies | Blob storage |
| nv-ingest | internal | Document parsing / NV-Ingest |
| redis | 6379 | Message queue for ingestor |
| rag-frontend | 3000 (or mapped) | Optional browser UI |

---

## Verification Commands

```bash
# Basic health
curl -sf http://localhost:8081/v1/health
# Expected: {"status":"OK"}

# Full dependency check (LLM, embedding, NV-Ingest all healthy)
curl -sf "http://localhost:8081/v1/health?check_dependencies=true"

# Ingestor health
curl -sf http://localhost:8082/health

# Elasticsearch
curl -sf http://localhost:9200/_cluster/health | jq .status
# Expected: "green" or "yellow"

# List ingested documents
curl -sf http://localhost:8082/v1/documents | jq .
```

---

## Ingest a Document

```bash
# Ingest a PDF
curl -X POST http://localhost:8082/v1/documents \
  -H "Content-Type: multipart/form-data" \
  -F "file=@/path/to/document.pdf" \
  -F "collection_name=sherlock_case_001"

# Query after ingestion
curl -X POST http://localhost:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"What entities are mentioned?"}],
       "collection_name":"sherlock_case_001"}'
```

---

## FRAG Integration with AI-Q

When RAG Blueprint is running, wire it to AI-Q as its knowledge layer:
- `RAG_SERVER_URL=http://rag-server:8081` (use Docker service name, not localhost)
- `RAG_INGEST_URL=http://ingestor-server:8082`
- AI-Q must be on the `nvidia-rag` Docker network

See `~/skills/skills/aiq-deploy/references/frag.md` for exact wiring steps.

---

## Project-Specific Notes

- Clone RAG Blueprint to `external/rag/` (gitignored).
- Tag: `v2.6.0`
- Use the **NVIDIA-hosted NIMs** profile (`nvdev.env`) for dev mode.
- The `nvidia-rag` Docker network is created by the RAG Blueprint compose stack.
- **Vector store: Elasticsearch** (confirmed — this is the default, not Milvus).
  Milvus/cuVS is an optional GPU/prod swap documented in `references/configure/models-and-infrastructure.md`.
- Do not run `docker compose down -v` without user confirmation — destroys ingested data.
- SeaweedFS stores raw documents; Elasticsearch stores embeddings. Both must be healthy.

---

## Common Failure Modes

| Symptom | Likely cause | Fix |
|---|---|---|
| rag-server unhealthy | LLM NIM not reachable | Check NVIDIA_API_KEY; verify NIM endpoint |
| Ingestor 404 on upload | Wrong ingestor URL format | Use `http://host:port` without `/v1`; code appends it |
| Empty retrieval results | Collection name mismatch | Check `--collection` matches what was used at ingest time |
| Elasticsearch red | Insufficient memory | Requires at least 4 GB RAM for ES |
| NV-Ingest failure | Redis not ready | Ensure redis is healthy before ingestor starts |
