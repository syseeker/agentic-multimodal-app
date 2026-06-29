# Sherlock — Agent & Tool Map

A reference for every AI agent and automated tool in the Sherlock system:
where it lives, what it does, what skills and tools it holds, and where its memory is stored.
See [AGENTS.md](AGENTS.md) for the agentic framework internals (Plan/Act/Observe/Refine, orchestrator, NemoClaw comparison).

---

## Persona Classification

Three personas interact with or operate inside Sherlock:

| Persona | Who | Interacts with |
|---------|-----|----------------|
| **User** | Forensic investigator | Chat panel, evidence viewer, entity graph, plan approval |
| **System** | Automated pipeline (no human) | Data ingest, ASR, entity extraction, graph population |
| **Developer** | Engineer building Sherlock | Docker compose, configs, env vars, phase scripts |

Each agent/tool below is tagged: `[User]` `[System]` `[Developer]`.

---

## Layer Overview

```
┌─────────────────────────────────────────────────────────┐
│  USER LAYER                                             │
│  Sherlock Case Workbench (Svelte SPA + FastAPI :8200)   │
│  ↕ REST / SSE                                           │
├─────────────────────────────────────────────────────────┤
│  AGENT LAYER                                            │
│  AI-Q "Sherlock" lead agent (:8100)                     │
│    └── vss-agent sub-agent via MCP (GPU-deferred)       │
├─────────────────────────────────────────────────────────┤
│  TOOL / SKILL LAYER                                     │
│  Sherlock MCP Server (:9901)  ← graph tools             │
│  RAG Blueprint (:8081/:8082)  ← knowledge retrieval     │
│  Parakeet ASR + MERaLiON      ← audio analysis          │
│  VLM Image Captioning          ← image analysis (stub)  │
│  Graph ER Extraction           ← Neo4j population       │
├─────────────────────────────────────────────────────────┤
│  STORAGE LAYER                                          │
│  Elasticsearch · Neo4j · Postgres · SeaweedFS · Disk    │
└─────────────────────────────────────────────────────────┘
```

---

## Agents

### 1. AI-Q "Sherlock" — Lead Agent `[User]`

The investigator's primary interface. Orchestrates all sub-agents and tools.
Runs headless (no built-in web UI); the workbench proxies all traffic to it.

| Attribute | Value |
|-----------|-------|
| **Container** | `amms-aiq-agent` |
| **Port** | `8100` (internal + host) |
| **Image** | `aiq:release` (built from `external/aiq/`) |
| **Active config** | `external/aiq/configs/config_sherlock_frag.yml` |
| **Prompts** | `deploy/aiq-prompts/shallow_researcher/researcher.j2` (forensic persona)<br>`deploy/aiq-prompts/clarifier/plan_generation.j2` (HITL planning) |
| **Phase** | 1 (base) · 7 (forensic extensions) |

**What it does:**
- Receives investigator questions via SSE chat stream
- Routes to shallow research (fast vector lookup) or deep research (multi-turn reasoning)
- Calls graph tools via MCP to query entities, relationships, and run graph algorithms
- Implements human-in-the-loop (HITL): detects investigation plans, blocks until investigator approves
- Returns cited findings with inline source references [1], [2]
- Web search is permanently **OFF** (air-gapped forensic deployment)

**Tools registered:**

| Tool | Type | What it calls |
|------|------|--------------|
| `knowledge_search` | FRAG adapter | RAG Blueprint `:8081` — semantic search over ingested case docs |
| `graph_query_tool` | MCP | Sherlock MCP `:9901` — list persons, suspects, evidence from Neo4j |
| `graph_analyze_tool` | MCP | Sherlock MCP `:9901` — centrality, communities, shortest-path |
| `extract_entities_tool` | MCP | Sherlock MCP `:9901` — NER on new text → write to Neo4j |
| `list_cases` | MCP | Sherlock MCP `:9901` — all case IDs + entity counts |
| `mcp_vss_agent` | MCP | VSS agent `:8000` — video search/summarize *(GPU-deferred)* |

**Internal sub-components (AI-Q built-in):**

| Sub-component | Role |
|--------------|------|
| Intent Classifier | Routes question: shallow vs. deep research |
| Clarifier Agent | Detects plans, handles HITL approval turns |
| Shallow Research Agent | Fast vector DB lookup + answer synthesis |
| Deep Research Agent | Multi-turn reasoning, calls multiple tools |

**Memory & knowledge stores:**

| Store | What's in it |
|-------|-------------|
| Elasticsearch `:9200` | Embeddings of all ingested case text, transcripts, captions |
| Neo4j `:7687` | Forensic entity graph (Person, Org, Location, Evidence + relations) |
| Postgres `:5432` | AI-Q job store, checkpoints, event stream (internal, not queried directly) |
| NeMo Guardrails | Forensic safety policy: `guardrails/sherlock_forensic_safety_v1.0.0.md` |

**Key env vars:**
```
NVIDIA_API_KEY          # Hosted NIM access (dev); self-hosted in prod
BACKEND_CONFIG          # Path to active YAML config
RAG_SERVER_URL          # http://rag-server:8081/v1
SHERLOCK_MCP_URL        # http://sherlock-mcp:9901/mcp
COLLECTION_NAME         # multimodal_data
```

---

### 2. VSS Video Agent — Specialist Sub-Agent `[User]` *(GPU-deferred)*

A specialist called by AI-Q over MCP when a question requires video evidence analysis.
Mirrors a real forensic team: Sherlock (generalist lead) delegates to a video analyst.

| Attribute | Value |
|-----------|-------|
| **Container** | Not yet deployed (requires GPU + Phase 5) |
| **Blueprint** | `external/video-search-and-summarization/` (NVIDIA VSS) |
| **Protocol** | Model Context Protocol (MCP), `LVS_ENABLE_MCP=true` |
| **Port** | `8000` (video service, when deployed) |
| **Phase** | 5 (VSS deployment) · 7 (MCP registration) |

**What it does:**
- Dense-caption extraction from video frames using VLM
- Semantic search over video content stored in Elasticsearch
- Frame-level summarization on demand
- Populates shared Elasticsearch + Neo4j with video entities (merged by `name + case_id`)

**MCP tools exposed to AI-Q:**

| Tool | Purpose |
|------|---------|
| `summarize_video` | Temporal summary of a video file |
| `search_video` | Keyword/semantic search across all ingested video |
| `describe_frame` | VLM caption for a specific timestamp/frame |

**Memory & knowledge stores:**

| Store | What's in it |
|-------|-------------|
| Elasticsearch `:9200` | Dense-caption embeddings from video frames (shared with RAG-BP) |
| Neo4j `:7687` | Video entity-relationship graph (merged with non-video ER) |

---

## System-Facing Tools (Automated Pipelines)

These run without human interaction — triggered by case upload or by the entity extraction pipeline. They populate the stores that AI-Q queries.

### 3. RAG Blueprint — Knowledge Ingest & Retrieval `[System]` `[Developer]`

Ingests case documents, embeds them, and serves semantic retrieval to AI-Q.

| Attribute | Value |
|-----------|-------|
| **Containers** | `rag-server` `:8081`, `ingestor-server` `:8082`, `elasticsearch`, `seaweedfs`, `redis`, `nv-ingest-ms` |
| **Blueprint** | `external/rag/` (NVIDIA RAG Blueprint v2.6.0) |
| **Skill** | `~/skills/skills/rag-blueprint/` |
| **Phase** | 2 |

**What it does:**
- Accepts document uploads via `POST /v1/documents` (multipart, any format)
- Extracts + chunks text using NV-Ingest (PDF, TXT, JSON, Markdown)
- Embeds chunks using NVIDIA embedding NIM → stores in Elasticsearch
- Serves agentic RAG queries: planner → task executor → seed generator → cited synthesis
- Exposes `knowledge_search` tool consumed by AI-Q

**Skills / tools it holds:**
- NV-Ingest MS runtime (text extraction, chunking)
- NVIDIA Embedding NIM (embedding generation)
- Agentic RAG planner (enabled via `ENABLE_AGENTIC_RAG=true`)

**Memory:**

| Store | What's in it |
|-------|-------------|
| Elasticsearch `:9200` | Document chunk embeddings (collection: `multimodal_data`) |
| SeaweedFS `:9010` | Original uploaded blobs (PDFs, text files) |
| Redis | Ingest task queue |

**Key env vars:**
```
ENABLE_AGENTIC_RAG=true
COLLECTION_NAME=multimodal_data
NVIDIA_API_KEY
NGC_API_KEY
```

---

### 4. Parakeet ASR Pipeline `[System]`

Transcribes audio evidence files. Triggered automatically when audio files are uploaded.

| Attribute | Value |
|-----------|-------|
| **Script** | `data/audio/process_audio.py` |
| **Triggered by** | Workbench upload endpoint (`_spawn` async subprocess) |
| **Skill** | `~/skills/skills/nemotron-speech/` |
| **Phase** | 4 |

**What it does:**
- Normalizes audio to mono WAV 16kHz 16-bit PCM
- Discovers NVCF function-id dynamically (never hardcoded)
- Calls Parakeet via cloud gRPC (`grpc.nvcf.nvidia.com:443`)
- Writes per-file transcript + paralinguistics stub
- Aggregates into `audio_analysis.txt`
- Ingests transcript text into RAG-BP (`multimodal_data` collection)

**Model options** (set via `ASR_MODEL` env var):

| Model | Strength |
|-------|---------|
| `ai-parakeet-1_1b-rnnt-multilingual-asr` *(default)* | English, Mandarin, Malay, Vietnamese, Filipino |
| `ai-parakeet-ctc-1_1b-asr` | Best English accuracy + word timestamps |
| `ai-whisper-large-v3` | 99 languages, offline |
| `ai-nemotron-asr-streaming` | English + speaker diarization |
| `ai-canary-1b-asr` | Offline + bidirectional translation |

**Memory / outputs:**

| Location | What's written |
|----------|---------------|
| `data/cases/<id>/audio/*_transcript.txt` | Per-file transcript |
| `data/cases/<id>/audio_analysis.txt` | Aggregated audio + paralinguistics |
| RAG-BP Elasticsearch | Transcript text ingested as searchable chunks |

**Key env vars:**
```
NVIDIA_API_KEY      # NVCF function discovery + cloud ASR
INGESTOR_URL        # http://localhost:8082
COLLECTION          # multimodal_data
ASR_MODEL           # (optional override)
```

---

### 5. MERaLiON Paralinguistics `[System]` *(GPU-deferred, stub)*

Extracts emotion, stress level, and language identification from audio.

| Attribute | Value |
|-----------|-------|
| **Script** | `data/audio/process_audio.py` (stub section) |
| **Phase** | 7 (GPU required) |
| **Status** | Stub only — outputs placeholder values until GPU deployed |

**What it will do (when GPU available):**
- Classify emotion (neutral, angry, fearful, stressed)
- Estimate speaker stress level (0–1 scale)
- Identify language per segment
- Write structured JSON into `audio_analysis.txt`

**Memory:** writes to `data/cases/<id>/audio_analysis.txt` → read by Sentiment panel in workbench.

---

### 6. VLM Image Captioning `[System]` *(GPU-deferred, stub)*

Generates natural-language descriptions of image evidence.

| Attribute | Value |
|-----------|-------|
| **Script** | `data/image/caption_images.py` |
| **Phase** | 7 (GPU required) |
| **Status** | Stub only |

**What it will do (when GPU available):**
- Call Vision Language Model (VLM) on each uploaded image
- Write captions to `data/cases/<id>/image_captions.txt`
- Ingest captions into RAG-BP for semantic retrieval
- Feed captions into Graph ER extraction (step 7 below)

---

### 7. Graph Entity Extraction `[System]`

LLM-driven Named Entity Recognition: reads case text → extracts persons, orgs, locations, evidence → writes to Neo4j.

| Attribute | Value |
|-----------|-------|
| **Script** | `graph/ingest_entities.py` |
| **Module** | `graph/tools.py` (reused by Sherlock MCP) |
| **Triggered by** | Workbench upload (final step, after all other pipelines) |
| **LLM** | `nvidia/nemotron-3-nano-30b-a3b` (via `integrate.api.nvidia.com`) |
| **Phase** | 6 |

**What it does:**
- Reads all text files in a case directory (reports, transcripts, chats, captions)
- Calls LLM with a structured extraction prompt → JSON entities + relations
- MERGE into Neo4j (idempotent — safe to re-run, deduplicates by `name + case_id`)
- Records provenance: every node carries `source_file` and `case_id`

**Neo4j schema written:**

```
Nodes:  Case | Person | Organization | Location | Evidence
Edges:  SUSPECT_IN | WITNESS_IN | VICTIM_IN | OFFICER_IN
        ASSOCIATED_WITH (strength) | LOCATED_AT | MEMBER_OF
        INVOLVED_IN | LINKED_TO | IMPLICATES
```

**Memory:**

| Store | What's written |
|-------|---------------|
| Neo4j `:7687` | Entity nodes + relationship edges, `case_id`-namespaced |

**Key env vars:**
```
NEO4J_URI=bolt://localhost:7687
LLM_BASE_URL=https://integrate.api.nvidia.com/v1
LLM_NAME=nvidia/nemotron-3-nano-30b-a3b
NVIDIA_API_KEY
```

---

### 8. Sherlock MCP Server `[System]` `[Developer]`

Wraps `graph/tools.py` functions as Model Context Protocol tools so AI-Q can call them over HTTP.

| Attribute | Value |
|-----------|-------|
| **Container** | `amms-sherlock-mcp` |
| **Port** | `9901` |
| **Source** | `mcp/sherlock_mcp.py` (FastMCP) |
| **Compose** | `deploy/compose.sherlock_mcp.yaml` |
| **Phase** | 7 |

**MCP tools exposed:**

| Tool name | Signature | What it does |
|-----------|-----------|-------------|
| `graph_query_tool` | `(case_id, query_type)` | Read entities: persons, suspects, associates, all_entities |
| `graph_analyze_tool` | `(case_id, algorithm)` | Run graph algorithms: centrality, communities, shortest_path |
| `extract_entities_tool` | `(case_id, content, content_type, source_file)` | LLM NER → write to Neo4j |
| `list_cases` | `()` | All case IDs + entity counts from Neo4j |

**Memory:** reads/writes Neo4j directly via `graph/tools.py`. No persistent state of its own.

**AI-Q registration** (in `config_sherlock_frag.yml`):
```yaml
function_groups:
  mcp_sherlock_tools:
    _type: mcp_client
    server:
      transport: streamable-http
      url: ${SHERLOCK_MCP_URL:-http://sherlock-mcp:9901/mcp}
```

---

## Developer-Facing Services

### 9. Case Workbench Backend `[User]` `[Developer]`

FastAPI backend that glues all components together and serves the Svelte SPA.

| Attribute | Value |
|-----------|-------|
| **Container** | `amms-workbench` |
| **Port** | `8200` |
| **Source** | `ui/server.py` |
| **Compose** | `deploy/compose.workbench.yaml` |
| **Phase** | 8 |

**API surface:**

| Route | Purpose |
|-------|---------|
| `GET /api/cases` | List all cases |
| `GET /api/cases/{id}/graph` | Neo4j → Cytoscape.js elements |
| `GET /api/cases/{id}/evidence` | File list (text, audio, image, video) |
| `GET /api/cases/{id}/evidence/{file}` | Text file content |
| `GET /api/cases/{id}/media/{path}` | Stream audio / image / video (Range-supported) |
| `GET /api/cases/{id}/sentiment` | Parse `audio_analysis.txt` |
| `POST /api/cases/upload` | Multimodal upload → auto-dispatch all pipelines |
| `POST /api/chat` | SSE proxy → AI-Q `/v1/chat/stream` (600s timeout) |
| `GET /api/health` | AI-Q + Neo4j connectivity check |

**Upload auto-dispatch:**
```
POST /api/cases/upload
  ├─ text files  → RAG ingest (async)
  ├─ audio files → Parakeet ASR (subprocess)
  ├─ image files → VLM captioning (subprocess, stub)
  └─ all files   → Graph ER extraction (subprocess)
```

**Memory / state:**
- `data/cases/<case_id>/` — local filesystem (case metadata JSON, evidence files)
- Reads Neo4j for graph data
- No internal state — all state is in the stores above

---

## Storage Map

| Store | Type | Data | Shared between |
|-------|------|------|---------------|
| **Elasticsearch** `:9200` | Vector DB | Document embeddings (RAG-BP) + video dense-captions (VSS) | RAG-BP + VSS |
| **Neo4j** `:7687` | Graph DB | Entities + relations, `case_id`-namespaced; source provenance on every node | Graph ER + VSS + Sherlock MCP |
| **Postgres** `:5432` | Relational | AI-Q job store, event stream, checkpoints | AI-Q only |
| **SeaweedFS** `:9010` | Object store | Original uploaded blobs (PDFs, docs) | RAG-BP only |
| **Disk** `data/cases/` | Filesystem | Evidence files: audio/, images/, video/, text; `metadata.json` per case | Workbench + all pipelines |
| **NeMo Guardrails** | Policy file | `guardrails/sherlock_forensic_safety_v1.0.0.md` — forensic safety rules | AI-Q only |

---

## Persona Summary

### User-facing (investigator interacts directly)
| Agent / Component | What the investigator sees |
|-------------------|---------------------------|
| AI-Q Sherlock (lead agent) | Chat panel — ask questions, get cited answers |
| Clarifier Agent (inside AI-Q) | HITL plan approval banner — approve or reject investigation plans |
| VSS sub-agent (via AI-Q) | Video evidence answers in chat *(GPU-deferred)* |
| Case Workbench SPA | 4-panel UI: Chat · Entity Graph · Evidence · Paralinguistics |

### System-facing (automated, no human trigger per-run)
| Agent / Tool | Trigger |
|-------------|---------|
| Parakeet ASR | Case file upload (audio detected) |
| MERaLiON Paralinguistics | Case file upload (audio, GPU-deferred) |
| VLM Image Captioning | Case file upload (images, GPU-deferred) |
| Graph ER Extraction | Case file upload (always, final step) |
| RAG ingest | Case file upload (text files) |

### Developer-facing (engineer configures once, then it runs)
| Component | Where developer configures it |
|-----------|------------------------------|
| AI-Q config | `external/aiq/configs/config_sherlock_frag.yml` |
| Forensic prompts | `deploy/aiq-prompts/` (volume-mounted into AI-Q) |
| RAG Blueprint | `external/rag/deploy/compose/` + env vars |
| Sherlock MCP Server | `mcp/sherlock_mcp.py` + `deploy/compose.sherlock_mcp.yaml` |
| Neo4j schema | `graph/schema.py` (auto-initialized, idempotent) |
| ASR model selection | `ASR_MODEL` env var in `data/audio/process_audio.py` |
| Safety guardrails | `guardrails/sherlock_forensic_safety_v1.0.0.md` |
| Phase deployment | `deploy/PHASE*.md` (what/why) + `deploy/phase*.sh` (how to run) |

---

## Skills Location Reference

NVIDIA SME skills live in the separately-cloned skills repo. Always `git pull` before using.

| Phase | Skill directory | What it covers |
|-------|----------------|---------------|
| 1 | `~/skills/skills/aiq-deploy/` | AI-Q deploy, config format, extension points |
| 2 | `~/skills/skills/rag-blueprint/` | RAG Blueprint v2.6.0, agentic RAG, NV-Ingest |
| 3 | `~/skills/skills/data-designer/` | Synthetic forensic data generation |
| 4 | `~/skills/skills/nemotron-speech/` | Parakeet ASR models, NVCF gRPC, MERaLiON |
| 5 | `~/skills/skills/vss-deploy-profile/` | VSS LVS profile, MCP flag, Kafka/Redis |
| 7 | `~/skills/skills/nemotron-policy-generator/` | NeMo Guardrails policy generation |

Skills are **authoritative**. When a skill and intuition conflict, the skill wins.

---

## Container Inventory

| Container | Image | Host Port | Purpose | Phase |
|-----------|-------|-----------|---------|-------|
| `amms-aiq-agent` | `aiq:release` | 8100 | Lead agent (Sherlock) | 1 ✅ |
| `amms-aiq-postgres` | `postgres:16-alpine` | — | AI-Q job store | 1 ✅ |
| `elasticsearch` | `docker.elastic.co/elasticsearch:9.3.0` | — | Vector store | 2 ✅ |
| `seaweedfs` | `chrislusf/seaweedfs:3.73` | — | Blob store | 2 ✅ |
| `compose-redis-1` | `redis` | — | Ingest task queue | 2 ✅ |
| `compose-nv-ingest-ms-runtime-1` | nvcr.io nv-ingest | — | NV-Ingest extraction | 2 ✅ |
| `ingestor-server` | nvcr.io ingestor-server:2.6.0 | 8082 | Ingest API | 2 ✅ |
| `rag-server` | nvcr.io rag-server:2.6.0 | 8081 | RAG query API | 2 ✅ |
| `rag-frontend` | nvcr.io rag-frontend:2.6.0 | 3001 | RAG UI (unused) | 2 ✅ |
| `amms-neo4j` | `neo4j:5.20-community` | 7474 / 7687 | Graph store | 6 ✅ |
| `amms-sherlock-mcp` | `python:3.11-slim` | 9901 | Graph tools MCP | 7 ✅ |
| `amms-workbench` | `amms-workbench:latest` | 8200 | Case workbench | 8 ✅ |
