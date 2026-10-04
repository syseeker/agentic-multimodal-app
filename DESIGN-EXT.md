# Sherlock — Agent & Tool Map

A reference for every AI agent and automated tool in the Sherlock system:
where it lives, what it does, what skills and tools it holds, and where its memory is stored.
Implementation checked against `main` on 2026-10-02; the original tool-map layout is retained.
[DESIGN.md §8](DESIGN.md#8-installation-and-evidence-data-flows) adds setup/upload/modality diagrams.
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
│    (no sub-agents — all capabilities are tools)         │
├─────────────────────────────────────────────────────────┤
│  TOOL / SKILL LAYER                                     │
│  Sherlock MCP Server (:9901)  ← graph + audio tools             │
│  RAG Blueprint (:8081/:8082)  ← knowledge retrieval     │
│  Parakeet ASR + MERaLiON      ← audio analysis          │
│  VLM Image Captioning          ← image analysis (not built)  │
│  Graph ER Extraction           ← Neo4j population       │
├─────────────────────────────────────────────────────────┤
│  STORAGE LAYER                                          │
│  Elasticsearch · Neo4j · Postgres · SeaweedFS · Disk    │
└─────────────────────────────────────────────────────────┘
```

---

## Agents

### 1. AI-Q "Sherlock" — Lead Agent `[User]`

The investigator's primary interface. Runs the active shallow tool loop;
classifier/clarifier/deep components are configured alternatives, not active sub-agents.
Runs headless (no built-in web UI); the workbench proxies all traffic to it.

| Attribute | Value |
|-----------|-------|
| **Container** | `amms-aiq-agent` |
| **Port** | Host `8100` → container `8000` |
| **Image** | `aiq:release` (built from `external/aiq/`) |
| **Active config** | `external/aiq/configs/config_sherlock_frag.yml` |
| **Prompts** | `deploy/aiq-prompts/shallow_researcher/researcher.j2` (forensic persona)<br>`deploy/aiq-prompts/clarifier/plan_generation.j2` (HITL planning) |
| **Phase** | 1 (base) · 7 (forensic extensions) |

**What it does:**
- Receives investigator questions via SSE chat stream
- Uses `shallow_research_workflow`; deep routing is available only with a different workflow
- Calls graph tools via MCP to query entities, relationships, and run graph algorithms
- Workbench detects plans and submits approval/revision as chat feedback; no server-side execution gate
- Returns cited findings with inline source references [1], [2]
- Web search is **OFF** in this config; hosted model calls mean the PoC is not air-gapped

**Tools registered:**

| Tool | Type | What it calls |
|------|------|--------------|
| `knowledge_search` | FRAG adapter | RAG Blueprint `:8081` — semantic search over ingested case docs |
| `graph_query_tool` | MCP | Sherlock MCP `:9901` — list persons, suspects, evidence from Neo4j |
| `graph_analyze_tool` | MCP | Sherlock MCP `:9901` — centrality, communities, shortest-path |
| `extract_entities_tool` | MCP | Sherlock MCP `:9901` — NER on new text → write to Neo4j |
| `list_cases` | MCP | Sherlock MCP `:9901` — all case IDs + entity counts |
| `mcp_vss_agent` | MCP | VSS Sherlock MCP `:9903` — `list_case_videos`, `ask_video`, `summarize_video` |

**Internal sub-components (AI-Q built-in):**

| Sub-component | Role |
|--------------|------|
| Intent Classifier | Configured alternative: routes shallow/deep when a routing workflow is selected |
| Clarifier Agent | Configured alternative; approval disabled and inactive in current shallow path |
| Shallow Research Agent | Active tool selection, retrieval/graph/audio/video results and answer synthesis |
| Deep Research Agent | Configured alternative; inactive under `shallow_research_workflow` |

**Memory & knowledge stores:**

| Store | What's in it |
|-------|-------------|
| Elasticsearch `:9200` | Embeddings of all ingested case text, transcripts, captions |
| Neo4j `:7687` | Forensic entity graph (Person, Org, Location, Evidence + relations) |
| Postgres `:5432` | AI-Q job store, checkpoints, event stream (internal, not queried directly) |
| NeMo Guardrails | Draft, not runtime enforcement: forensic safety policy: `guardrails/sherlock_forensic_safety_v1.0.0.md` |

**Key env vars:**
```
NVIDIA_API_KEY          # Hosted inference used by the current PoC
BACKEND_CONFIG          # Path to active YAML config
RAG_SERVER_URL          # http://rag-server:8081/v1
SHERLOCK_MCP_URL        # http://sherlock-mcp:9901/mcp
COLLECTION_NAME         # multimodal_data
```

---

### 2. Video Analysis — Custom MCP Tools `[System]`

Video is reached as a **tool, not a sub-agent**. VSS's own agent MCP (`LVS_ENABLE_MCP`)
added ~31 s of overhead per call and dropped MCP sessions, so it stays off; a custom MCP
server calls the VLM directly instead. The ~4 s figure is a recorded deployment
result; current latency depends on the profile/model/workload.

| Attribute | Value |
|-----------|-------|
| **Container** | `amms-vss-sherlock-mcp` (:9903) → `vss-rtvi-vlm` (:8018) |
| **Script** | `mcp/vss_sherlock_mcp.py` |
| **Serving** | vLLM inside the rtvi-vlm container, OpenAI-compatible `/v1/chat/completions` |
| **Blueprint** | `external/vss-3.2.0/` (NVIDIA VSS, LVS profile) |
| **Phase** | 5 (VSS deployment) · 7 (MCP registration) |

**MCP tools exposed to AI-Q:**

| Tool | Purpose |
|------|---------|
| `list_case_videos` | List videos on local case disk; registration must be checked separately |
| `ask_video` | Ask a question about a specific video |
| `summarize_video` | Forensic narrative summary of a video |

Videos are registered with VIOS on upload; **analysis runs on demand**, not at upload.
Lookups use case/stem matching and prefer the most recent registration. The earlier
across-case bug was addressed, but substring matching still needs exact asset identity.

**Known gap:** this path writes **no** Elasticsearch document, so every question re-runs
inference and a `summarize_video` citation points at a process rather than a stored
artifact. `ask_video` falls back to `vss-agent /generate`; `summarize_video` can use
LVS `/v1/summarize` then `vss-agent /generate`. The recorded LVS fallback had not succeeded
on the original host; this is historical evidence, not a current universal status.

---

## System-Facing Tools (Automated Pipelines)

These can run as setup/batch processing or upload-triggered workers. Completion is
not centrally coordinated; upload acknowledgements do not establish store readiness.

### 3. RAG Blueprint — Knowledge Ingest & Retrieval `[System]` `[Developer]`

Ingests case documents, embeds them, and serves semantic retrieval to AI-Q.

| Attribute | Value |
|-----------|-------|
| **Containers** | `rag-server` `:8081`, `ingestor-server` `:8082`, `elasticsearch`, `seaweedfs`, `redis`, `nv-ingest-ms` |
| **Blueprint** | `external/rag/` (NVIDIA RAG Blueprint v2.6.0) |
| **Skill** | `~/skills/skills/rag-blueprint/` |
| **Phase** | 2 |

**What it does:**
- Accepts document uploads via the ingestor documents API (multipart, supported formats)
- Extracts + chunks text using NV-Ingest (PDF, TXT, JSON, Markdown)
- Embeds chunks using NVIDIA embedding NIM → stores in Elasticsearch
- Offers an agentic generation path; current Sherlock FRAG calls retrieve chunks for AI-Q synthesis
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
- Writes per-file transcript + real MERaLiON results where available, otherwise stub status
- Aggregates into `audio_analysis.txt`
- Ingests transcript text into RAG-BP (`multimodal_data` collection)

**Model options** (set via `ASR_MODEL` env var; current connection is hosted NVCF
and requests `en-US`, with no automatic model/language router):

| Model | Strength |
|-------|---------|
| `ai-parakeet-1_1b-rnnt-multilingual-asr` *(default)* | English, Mandarin, Malay, Vietnamese, Filipino |
| `ai-parakeet-ctc-1_1b-asr` | Best English accuracy + word timestamps |
| `ai-whisper-large-v3` | Configurable alternative; this script still calls the hosted endpoint |
| `ai-nemotron-asr-streaming` | English + speaker diarization |
| `ai-canary-1b-asr` | Configurable alternative; local serving requires adapter changes |

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

### 5. MERaLiON Paralinguistics `[System]`

Extracts emotion, stress level, and language identification from audio.

| Attribute | Value |
|-----------|-------|
| **Model** | `MERaLiON/MERaLiON-3-10B` (`MERALION_MODEL` to override) |
| **Serving** | Local HTTP `meralion_server.py` on `:8500` preferred; in-process Transformers fallback |
| **Script** | `data/audio/process_audio.py::meralion_paralinguistics()` |
| **Phase** | 4 (pipeline) · 7 (`analyze_audio` MCP tool) |
| **Requires** | CUDA GPU + `HF_TOKEN`; memory is model/host-specific; recordings are windowed (30 s default) |
| **Status** | Working on x86_64 + GPU. Returns a `status: "stub"` dict when GPU or token is absent — still the case on GB10/aarch64, which is untested. |

**What it does:**
- Classify emotion (neutral, angry, fearful, stressed)
- Estimate speaker stress level
- Identify language per segment
- Write structured output into `audio_analysis.txt`

**Memory:** writes to `data/cases/<id>/audio_analysis.txt` → read by Sentiment panel in workbench.

---

### 6. VLM Image Captioning `[System]` — **NOT IMPLEMENTED**

Generates natural-language descriptions of image evidence.

| Attribute | Value |
|-----------|-------|
| **Script** | `data/image/caption_images.py` — **this file does not exist** |
| **Phase** | not scheduled |
| **Status** | Not implemented. The workbench detects images on upload and reports `image_caption_unavailable`; it no longer spawns the missing script (which failed silently, because `_spawn` discards stderr). |

**What it would do, if built:**
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
| **Triggered by** | Phase 6 batch or Workbench upload (launched last, without waiting for media completion) |
| **LLM** | `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` (via `integrate.api.nvidia.com`) |
| **Phase** | 6 |

**What it does:**
- Reads root TXT files in a case directory (reports, completed transcripts, chats); no direct PDF/DOCX graph extraction
- Calls LLM with a structured extraction prompt → JSON entities + relations
- MERGE into Neo4j (idempotent — safe to re-run, deduplicates by `name + case_id`)
- Records `source_file` and `case_id`; later MERGE can overwrite source, so this is not immutable multi-source provenance

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
LLM_NAME=nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
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
| `list_audio_files` | `(case_id)` | Audio inventory and heuristic transcript status |
| `get_audio_analysis` | `(case_id)` | Aggregated stored audio analysis |
| `analyze_audio` | `(case_id, filename)` | Fresh audio processing; container dependencies/write permissions need validation |

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
| `POST /api/cases/upload` | Create case from metadata + selected files; dispatch implemented workers |
| `POST /api/cases/{id}/evidence/upload` | Append evidence; audio/video/graph workers, no extra-text RAG dispatch |
| `POST /api/cases/{id}/audio/analyze` | Upload/analyze one audio file |
| `POST /api/chat` | SSE proxy → AI-Q `/v1/chat/stream` (600s timeout) |
| `GET /api/health` | AI-Q + Neo4j connectivity check |

**Upload auto-dispatch:**
```
POST /api/cases/upload
  ├─ text files  → RAG ingest (async)
  ├─ audio files → Parakeet ASR (subprocess)
  ├─ image files → save/view; image_caption_unavailable
  ├─ video files → VIOS registration (subprocess; inference is on demand)
  └─ root TXT    → Graph ER extraction (independent subprocess, may race audio)
```

**Memory / state:**
- `data/cases/<case_id>/` — local filesystem (case metadata JSON, evidence files)
- Reads Neo4j for graph data
- No internal state — all state is in the stores above

---

## Storage Map

| Store | Type | Data | Shared between |
|-------|------|------|---------------|
| **Elasticsearch** `:9200` | Vector DB | RAG document embeddings; upload-time video caption indexing is not wired | RAG-BP + VSS |
| **Neo4j** `:7687` | Graph DB | Custom text entities + relations with case/source properties; isolation incomplete | Graph ER + Sherlock MCP |
| **Postgres** `:5432` | Relational | AI-Q job store, event stream, checkpoints | AI-Q only |
| **SeaweedFS** `:9010` | Object store | Original uploaded blobs (PDFs, docs) | RAG-BP only |
| **Disk** `data/cases/` | Filesystem | Evidence files: audio/, images/, video/, text; `metadata.json` per case | Workbench + all pipelines |
| **NeMo Guardrails** | Policy file | `guardrails/sherlock_forensic_safety_v1.0.0.md` — draft safety rules, not deployed | proposed policy |

---

## Persona Summary

### User-facing (investigator interacts directly)
| Agent / Component | What the investigator sees |
|-------------------|---------------------------|
| AI-Q Sherlock (lead agent) | Chat panel — ask questions, get cited answers |
| Workbench plan detection (clarifier inactive) | Approval/revision banner sends follow-up chat; not an execution gate |
| Video MCP tools (via AI-Q) | Video evidence answers in chat, with citations |
| Case Workbench SPA | 4-panel UI: Chat · Entity Graph · Evidence · Paralinguistics |

### System-facing (automated, no human trigger per-run)
| Agent / Tool | Trigger |
|-------------|---------|
| Parakeet ASR | Case file upload (audio detected) |
| MERaLiON Paralinguistics | Case file upload (audio; needs GPU + `HF_TOKEN`) |
| ~~VLM Image Captioning~~ | Not implemented — see §6 |
| Graph ER Extraction | Case upload (launched independently), or Phase 6 batch |
| RAG ingest | Prepared/new-case text and derived audio; not extra-evidence text |

### Developer-facing (engineer configures once, then it runs)
| Component | Where developer configures it |
|-----------|------------------------------|
| AI-Q config | Source: `deploy/aiq-configs/config_sherlock_frag_mcp.yml`; copied to `external/aiq/configs/config_sherlock_frag.yml` |
| Forensic prompts | `deploy/aiq-prompts/` (volume-mounted into AI-Q) |
| RAG Blueprint | `external/rag/deploy/compose/` + env vars |
| Sherlock MCP Server | `mcp/sherlock_mcp.py` + `deploy/compose.sherlock_mcp.yaml` |
| Neo4j schema | `graph/schema.py` (auto-initialized, idempotent) |
| ASR model selection | `ASR_MODEL` env var in `data/audio/process_audio.py` |
| Safety guardrails | `guardrails/sherlock_forensic_safety_v1.0.0.md` |
| Phase deployment | `docs/archive/phases/PHASE*.md` (historical what/why) + `deploy/phase*.sh` (current setup scripts) |

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

Inventory from the phase records, not a live health check. VSS ownership changes
Elasticsearch/Redis names/tags; inspect the selected hardware profile on the lab host.

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
| `amms-sherlock-mcp` | `python:3.11-slim` | 9901 | Graph/audio tools MCP | 7 ✅ |
| `amms-workbench` | `amms-workbench:latest` | 8200 | Case workbench | 8 ✅ |

---

## Model Inventory

### Integrated models

| Model | Version | Which components | Location of model |
|-------|---------|------------------|-------------------|
| **Nemotron 3 Nano Omni Reasoning** — `nemotron-3-nano-omni-30b-a3b-reasoning` | Nemotron 3; hosted build unpinned | AI-Q Sherlock reasoning/tool calling; graph entity extraction | **NVIDIA hosted:** `integrate.api.nvidia.com/v1` |
| **Nemotron 3 Nano** — `nemotron-3-nano-30b-a3b` | Nemotron 3; hosted build unpinned | VSS reasoning LLM; recorded synthetic-case generation through Data Designer's `nvidia-text` alias | **NVIDIA hosted:** `integrate.api.nvidia.com` |
| **Nemotron 3 Super** — `nemotron-3-super-120b-a12b` | Nemotron 3; hosted build unpinned | RAG Blueprint generation, summarization and agentic RAG roles; current Sherlock FRAG retrieves chunks for AI-Q synthesis | **NVIDIA hosted:** `integrate.api.nvidia.com/v1` |
| **Llama Nemotron Embed VL 1B** — `llama-nemotron-embed-vl-1b-v2` | **v2** | RAG/NV-Ingest document embeddings and query embeddings | **NVIDIA hosted:** `integrate.api.nvidia.com/v1` |
| **Llama Nemotron Rerank VL 1B** — `llama-nemotron-rerank-vl-1b-v2` | **v2** | RAG retrieval reranking; Sherlock explicitly overrides the older reranker default | **NVIDIA hosted:** retrieval API, URL resolved from model ID |
| **Cosmos Reason2-8B** | **Reason2**, recorded NGC artifact `hf-1208` | VSS video understanding; recorded deployment and MCP model default | **On-prem GPU:** VSS RT-VLM, port `8018`; assets from **NGC** |
| **Cosmos Reason1-7B** | **Reason1** | Current x86 GPU installer's default VLM alternative | **On-prem GPU:** VSS RT-VLM, port `8018`; assets through VSS/NGC |
| **Parakeet multilingual RNNT 1.1B** — `ai-parakeet-1_1b-rnnt-multilingual-asr` | Hosted release unpinned | Default audio-evidence transcription through the Riva client | **NVIDIA hosted NVCF:** `grpc.nvcf.nvidia.com:443` |
| **MERaLiON-3-10B** | **3**; Hugging Face revision unpinned | Audio emotion, stress, language identification and paralinguistics | **On-prem GPU:** service on `8500`, with in-process fallback; weights from **Hugging Face** |
| **Magpie multilingual TTS** — `ai-magpie-tts-multilingual` | Hosted release unpinned | Synthetic witness/interview/phone-call audio generation | **NVIDIA hosted NVCF:** `grpc.nvcf.nvidia.com:443` |
| **MERaLiON OmniVoice Hokkien TTS** | Release/revision unpinned | Optional Hokkien synthetic-audio generation | **On-prem GPU:** OmniVoice process; weights from **Hugging Face** |
| **OpenAI gpt-oss-120b** | Hosted release unpinned | AI-Q/NAT evaluation judge; used when evaluation runs | **NVIDIA hosted:** `integrate.api.nvidia.com/v1` |

Sources: [AI-Q configuration](deploy/aiq-configs/config_sherlock_frag_mcp.yml), [graph extraction](graph/tools.py), [RAG configuration at v2.6.0](https://github.com/NVIDIA-AI-Blueprints/rag/blob/v2.6.0/deploy/compose/nvdev.env), [Sherlock RAG deployment](deploy/phase2_rag.sh), [VSS deployment](deploy/phase5_vss.sh), [VSS MCP model selection](mcp/vss_sherlock_mcp.py), [recorded Cosmos deployment](benchmark/examples/rtx_pro6000-2026-08-31/summary.md), [audio processing](data/audio/process_audio.py), [MERaLiON service](data/audio/meralion_server.py), [synthetic speech generation](data/sim/generate_audio_samples.py), [evaluation configuration](deploy/aiq-configs/eval_fragment.yml), [recorded Data Designer model](docs/archive/phases/PHASE3_DATA_SIM.md), [current Data Designer generator](data/sim/forensic_cases.py).

### Blueprint model settings and selectable alternatives

| Model | Version | Which components / status | Location of model |
|-------|---------|---------------------------|-------------------|
| **Nemotron Page Elements** | **v3** | NV-Ingest document-layout detection; used by applicable extraction paths | **NVIDIA hosted:** `ai.api.nvidia.com/v1/cv/nvidia/nemotron-page-elements-v3` |
| **Nemotron OCR** | **v1** | NV-Ingest OCR for applicable document formats | **NVIDIA hosted:** `ai.api.nvidia.com/v1/cv/nvidia/nemotron-ocr-v1` |
| **Nemotron Graphic Elements** | **v1** | Blueprint chart extraction endpoint; **chart extraction disabled** by Sherlock's installer | **NVIDIA hosted:** `ai.api.nvidia.com/v1/cv/nvidia/nemotron-graphic-elements-v1` |
| **Nemotron Table Structure** | **v1** | Blueprint table extraction endpoint; **table extraction disabled** by Sherlock's installer | **NVIDIA hosted:** `ai.api.nvidia.com/v1/cv/nvidia/nemotron-table-structure-v1` |
| **Nemotron Nano 12B VL** — `nemotron-nano-12b-v2-vl` | **v2** | Blueprint image-captioning default; **disabled on the reviewed default path** | Configured **NVIDIA hosted** endpoint |
| **Nemotron Parse** — `nvidia/nemotron-parse` | Unpinned | Alternative blueprint extraction model; **not selected/deployed** by Sherlock's installer | Upstream local-service default: `nemotron-parse:8000` |
| **Parakeet CTC 1.1B** — `ai-parakeet-ctc-1_1b-asr` | Hosted release unpinned | Selectable English ASR alternative | **NVIDIA hosted NVCF** |
| **OpenAI Whisper Large** — `ai-whisper-large-v3` | **Large v3** | Selectable ASR alternative | **NVIDIA hosted NVCF** |
| **Nemotron ASR Streaming** — `ai-nemotron-asr-streaming` | Hosted release unpinned | Selectable ASR alternative | **NVIDIA hosted NVCF** |
| **Canary 1B** — `ai-canary-1b-asr` | Hosted release unpinned | Selectable ASR/translation alternative | **NVIDIA hosted NVCF** |

Sources: [pinned blueprint model settings](https://github.com/NVIDIA-AI-Blueprints/rag/blob/v2.6.0/deploy/compose/nvdev.env), [blueprint extraction defaults](https://github.com/NVIDIA-AI-Blueprints/rag/blob/v2.6.0/deploy/compose/docker-compose-ingestor-server.yaml), [Sherlock extraction switches](deploy/phase2_rag.sh), [selectable ASR models](data/audio/process_audio.py).
