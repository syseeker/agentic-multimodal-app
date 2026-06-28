# Developer QUICKSTART — Sherlock Forensic Co-Worker

---

## What this MVP is

Sherlock is a forensic investigation co-worker built on the NVIDIA stack. It takes a case
folder (WhatsApp chat exports, witness statements, lab reports, audio recordings) and:

- Answers questions about suspects, timelines, and relationships — with cited sources
- Extracts entities and builds a relationship graph (who knows whom, who was where)
- Proposes investigation plans and waits for investigator approval before proceeding
- Processes audio statements through ASR + paralinguistic analysis

It runs entirely on-premise (air-gapped). The GPU-accelerated components (ASR, video
analysis, content safety) can be switched between hosted NVIDIA APIs (dev) and
self-hosted NIMs on a GB10 / RTX PRO 6000 (production).

The investigator-facing UI is at **http://localhost:8200**.

---

## Architecture

```
┌── Investigator UI (Svelte + FastAPI :8200) ─────────────────────────────────┐
│   Case selector · Chat with HITL approve/reject · Entity graph · Evidence   │
└─────────────────────────────┬───────────────────────────────────────────────┘
                              │ REST + SSE
┌── AI-Q "Sherlock" (:8100) ──┴───────────────────────────────────────────────┐
│   Lead agent · Forensic persona · HITL plan approval built-in                │
│   ├── knowledge_search  →  RAG Blueprint (:8081/:8082)                       │
│   │     Elasticsearch (text/image/doc search)                                │
│   └── mcp_sherlock_tools  →  Sherlock MCP (:9901)                           │
│         graph_query · graph_analyze · extract_entities · list_cases          │
└─────────────────────────────────────────────────────────────────────────────┘
┌── Storage ──────────────────────────────────────────────────────────────────┐
│   Neo4j (:7474/:7687)      Entity/relationship graph, namespaced by case_id  │
│   Elasticsearch (:9200)    Document vectors for RAG                          │
│   SeaweedFS                Binary blob store (images, audio)                 │
│   PostgreSQL               AI-Q job state                                    │
└─────────────────────────────────────────────────────────────────────────────┘
┌── GPU services (start when GPU instance ready) ─────────────────────────────┐
│   VSS vss-agent (:8000)    Video analysis via rtvi-vlm                       │
│   Parakeet ASR             Audio → transcript (via NVCF cloud or local NIM)  │
│   MERaLiON                 Paralinguistic analysis (Singlish/SEA audio)      │
│   Nemotron Content Safety  Forensic guardrails policy enforcement            │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Key files:**

| File | What it is |
|---|---|
| `DESIGN.md` | Full architecture decisions — read before any major change |
| `deploy/PHASE*.md` | What was deployed, why, what failed — one per phase |
| `deploy/phase*.sh` | The actual deploy commands — run these |
| `deploy/start_all.sh` | Bring up all services after first-time setup |
| `deploy/aiq-prompts/` | Sherlock's Jinja2 persona prompts (committed, editable) |
| `.claude/CLAUDE.md` | Context file loaded by Claude Code automatically |
| `.claude/context/phase-status.md` | Current deployment status, phase by phase |

---

## Prerequisites

Before running anything, you need:

| Requirement | Where to get it |
|---|---|
| Docker + Docker Compose v2 | https://docs.docker.com/engine/install/ |
| `NVIDIA_API_KEY` | https://build.nvidia.com → API Keys (AI Foundations scope) |
| `NGC_API_KEY` | https://org.ngc.nvidia.com → API Keys (Catalog + AI Foundations scopes) |
| `HF_TOKEN` | https://huggingface.co/settings/tokens (for MERaLiON gated model) |
| Node.js 20+ | `sudo apt-get install nodejs` or see Step 0 below |

---

## First-time setup (Option A: phase-by-phase)

Run these phases in order on a new instance. Each phase is a one-time operation.
After all phases are done, use `bash deploy/start_all.sh` as the daily driver.

### Step 0 — Clone and configure

```bash
# Clone this repo
git clone https://github.com/syseeker/agentic-multimodal-app ~/agentic-multimodal-app
cd ~/agentic-multimodal-app

# Clone NVIDIA skills repo (SME knowledge — required alongside this repo)
git clone https://github.com/NVIDIA/skills ~/skills

# Fill in API keys
cp .env.example .env
nano .env
# Required: NVIDIA_API_KEY, NGC_API_KEY, HF_TOKEN
# Leave as-is: COMPOSE_PROJECT_NAME=amms, AIQ_PORT=8100

# Install Node.js 20+ (needed to build the Svelte UI)
# Option A (with sudo):
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash -
sudo apt-get install -y nodejs
# Option B (no sudo — downloads portable binary):
curl -fsSL https://nodejs.org/dist/v20.18.1/node-v20.18.1-linux-x64.tar.xz \
  | tar -xJ -C /tmp/
echo 'export PATH="/tmp/node-v20.18.1-linux-x64/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

### Phase 1 — AI-Q backend

```bash
bash deploy/phase1_aiq.sh
```

This clones the AI-Q blueprint (`external/aiq/`), configures it for the `amms` project
(port 8100, web search off), and starts the agent container.

**Checkpoint:** `curl -sf http://localhost:8100/health` returns `{"isAlive":true}`

### Phase 2 — RAG Blueprint

```bash
bash deploy/phase2_rag.sh
```

Clones the RAG blueprint (`external/rag/`), starts Elasticsearch + SeaweedFS +
ingestor + RAG server. Wires RAG as AI-Q's knowledge source (FRAG pattern).

**Checkpoint:** `curl -sf http://localhost:8081/health` → OK. After Phase 3 ingest,
AI-Q answers questions citing document sources.

### Phase 3 — Forensic cases + data simulation

```bash
bash deploy/phase3_data_sim.sh
```

Generates 20 synthetic Singapore forensic cases using `data-designer` (Nemotron Nano 30B).
Ingests all case files into RAG Blueprint.

**Checkpoint:** AI-Q answers "who is the suspect in case SC-2024-03C5F0E4?" with a cited answer.

### Phase 4 — Audio pipeline

```bash
bash deploy/phase4_audio.sh
```

Processes any audio files in `data/cases/*/audio/` through Parakeet ASR → transcript →
paralinguistic stub → ingests to RAG. Generates test audio if none exists.

**Checkpoint:** `audio_analysis.txt` appears in at least one case folder.

### Phase 5 — VSS video analysis (GPU required)

```bash
# Only run this when a GPU instance is available (RTX PRO 6000 or GB10)
bash deploy/phase5_vss.sh
```

Deploys VSS with the LVS profile (Elasticsearch, Redis, Kafka stack). rtvi-vlm requires
GPU hardware — skip on CPU-only instances and revisit when the GPU node is ready.

**Checkpoint (GPU):** `curl -sf http://localhost:8000/isAlive` → `{"isAlive":true}`

### Phase 6 — Entity graph (Neo4j)

```bash
bash deploy/phase6_graph.sh
```

Starts Neo4j, runs LLM-based entity/relation extraction over all 20 case files,
writes the graph to Neo4j namespaced by `case_id`.

**Checkpoint:** Neo4j browser at http://localhost:7474 shows entities across cases.
`python3 graph/tools.py` returns suspects for a test case.

### Phase 7 — Sherlock AI-Q config + MCP tools

```bash
bash deploy/phase7_extensions.sh
```

Starts the Sherlock MCP server (graph tools over HTTP), switches AI-Q to
`config_sherlock_frag.yml` (web search off, graph + RAG tools), applies the forensic
prompt templates from `deploy/aiq-prompts/`.

**Checkpoint:** `curl -sf http://localhost:8100/v1/data_sources` returns
`Case Documents` and `Case Graph`. AI-Q responds with Sherlock forensic persona.

### Phase 8 — Case workbench UI

```bash
bash deploy/phase8_workbench.sh
```

Builds the Docker image (node:20 Svelte build + python:3.11 FastAPI serve) and
starts the workbench container.

**Checkpoint:** http://localhost:8200 loads the Sherlock workbench. Select a case,
type "who are the suspects?" and verify a cited answer comes back.

---

## After first-time setup: daily operations

```bash
# Start everything (Neo4j → RAG → AI-Q → Sherlock MCP → Workbench)
bash deploy/start_all.sh

# Stop everything
docker compose -p amms down

# Tail logs
docker logs -f amms-aiq-agent
docker logs -f amms-sherlock-mcp
docker logs -f amms-workbench

# Re-ingest a case (if you add new evidence files)
python3 graph/ingest_entities.py --case SC-2024-XXXXXXXX
```

---

## Common "what do I do next" scenarios

### I want to edit Sherlock's persona or investigation plan format

The prompts are Jinja2 templates committed in `deploy/aiq-prompts/`:

```
deploy/aiq-prompts/shallow_researcher/researcher.j2   ← research persona + rules
deploy/aiq-prompts/clarifier/plan_generation.j2       ← investigation plan format
```

Edit them directly. Then restart AI-Q to pick up the change:

```bash
docker compose -p amms \
  -f external/aiq/deploy/compose/docker-compose.yaml \
  -f deploy/compose.amms.override.yaml \
  up -d --no-build aiq-agent
```

### I want to use Milvus instead of Elasticsearch for RAG

1. Open `DESIGN.md` and read the storage section
2. Check if the RAG Blueprint skill has a Milvus config option:
   ```bash
   cd ~/skills && git pull
   grep -r -i milvus ~/skills/skills/rag-blueprint/
   ```
3. Prompt Claude Code:
   > Read `~/skills/skills/rag-blueprint/` and check if there's a Milvus vector store
   > option. Compare with our current Elasticsearch setup in `deploy/PHASE2_RAG.md` and
   > `deploy/phase2_rag.sh`. Recommend the swap if viable, then update the scripts.

### A new version of the AI-Q skill dropped — should I update?

```bash
cd ~/skills && git pull
```

Then prompt Claude Code:
> The `aiq-deploy` skill was just updated. Read `~/skills/skills/aiq-deploy/` and
> compare it against our current deployment in `deploy/PHASE1_AIQ.md` and
> `deploy/phase1_aiq.sh`. List any breaking changes, deprecated config keys, or new
> features we should adopt. Recommend which ones to apply now vs defer.

### I want to add a new tool to Sherlock (e.g. a timeline builder)

1. Add the tool function to `graph/tools.py` or a new `tools/timeline.py`
2. Expose it via the Sherlock MCP server in `mcp/sherlock_mcp.py`
3. Rebuild the MCP container:
   ```bash
   docker compose -p amms -f deploy/compose.sherlock_mcp.yaml up -d --build
   ```
4. The tool auto-registers in AI-Q — no config change needed

### I want to change the LLM model Sherlock uses

The model is set in `external/aiq/configs/config_sherlock_frag.yml` (gitignored, created
by Phase 7). Prompt Claude Code:

> Read `~/skills/skills/aiq-deploy/references/configs.md` to find the LLM config key.
> Then update `external/aiq/configs/config_sherlock_frag.yml` to use
> `nvidia/llama-3.1-nemotron-ultra-253b-v1` instead of the current model.
> Restart AI-Q after the change.

### I want to add a new forensic case

```bash
# 1. Create the case folder
mkdir -p data/cases/SC-2024-NEWCASE/{audio,images,video}

# 2. Drop in your evidence files
cp /path/to/files/* data/cases/SC-2024-NEWCASE/

# 3. Write metadata.json (copy and edit from an existing case)
cp data/cases/SC-2024-03C5F0E4/metadata.json data/cases/SC-2024-NEWCASE/metadata.json

# 4. Ingest to RAG
bash data/sim/ingest_cases.sh SC-2024-NEWCASE

# 5. Extract entities to graph
python3 graph/ingest_entities.py --case SC-2024-NEWCASE
```

### I want to enable GPU services (VSS + Content Safety)

When your RTX PRO 6000 or GB10 is ready:

1. Set `RTVI_VLM_URL=http://<GPU_IP>:8018` in `.env`
2. Run Phase 5: `bash deploy/phase5_vss.sh`
3. Uncomment `mcp_vss_agent` in `external/aiq/configs/config_sherlock_frag.yml`
4. Restart AI-Q: `docker compose -p amms -f ... up -d aiq-agent`

For Nemotron Content Safety enforcement, see Phase 9.

---

## Using Claude Code to continue development

This repo ships a `.claude/` directory that gives any Claude Code instance full context
automatically. When you open this repo in Claude Code, it loads `.claude/CLAUDE.md` and
knows the project history, architecture, and operating rules.

**The pattern for every task:**

```
1. cd ~/skills && git pull               # get latest NVIDIA SME knowledge
2. Read the relevant skill files         # Claude does this if you tell it the path
3. Prompt Claude with context            # example prompts below
4. Verify at the checkpoint              # run the curl/docker commands
5. Claude updates .claude/context/       # phase-status.md + implementation-learnings.md
```

**Example prompts:**

```
# Resume from last confirmed phase
"Check .claude/context/phase-status.md and tell me where we left off.
 What's the next phase and what does it require?"

# Read a skill before doing anything
"Read all files in ~/skills/skills/aiq-deploy/ then check whether our
 deploy/phase1_aiq.sh is still aligned with the current skill. List any drift."

# Make a change safely
"I want to swap our RAG vector store from Elasticsearch to Milvus.
 Read ~/skills/skills/rag-blueprint/ first. Then recommend the change
 with tradeoffs before touching any code."

# Debug a running service
"amms-aiq-agent is returning 500 errors on /v1/chat/stream.
 Read docker logs and the current config, then diagnose."
```

**Non-negotiable rules Claude follows in this repo** (from `.claude/CLAUDE.md`):
- Reads the NVIDIA skill before implementing any component
- Surfaces design choices as recommendations before coding
- Updates `.claude/context/` after every phase
- Never prints API key values
- Never edits `external/` prompt files (edit `deploy/aiq-prompts/` instead)

---

## Repo layout reference

```
agentic-multimodal-app/
├── DESIGN.md                        Full architecture and design decisions
├── QUICKSTART_DEVELOPER.md          This file
├── QUICKSTART_INVESTIGATOR.md       End-user guide
├── .env.example                     Template — copy to .env and fill
├── .claude/
│   ├── CLAUDE.md                    Auto-loaded context for Claude Code
│   └── context/
│       ├── phase-status.md          Current deployment state
│       └── implementation-learnings.md  Lessons learned, gotchas
├── deploy/
│   ├── start_all.sh                 Daily driver — start all services
│   ├── phase1_aiq.sh .. phase8_workbench.sh  First-time phase scripts
│   ├── PHASE1_AIQ.md .. PHASE8_WORKBENCH.md  What was deployed + why
│   ├── aiq-prompts/                 Sherlock prompt templates (committed)
│   ├── compose.amms.override.yaml  Docker Compose overlay for AI-Q
│   ├── compose.neo4j.yaml
│   ├── compose.sherlock_mcp.yaml
│   └── compose.workbench.yaml
├── graph/
│   ├── tools.py                     graph_query, graph_analyze, extract_entities
│   ├── schema.py                    Neo4j schema + ER extraction prompt
│   └── ingest_entities.py           Batch ER runner
├── mcp/
│   └── sherlock_mcp.py              FastMCP server (exposes graph tools to AI-Q)
├── ui/
│   ├── server.py                    FastAPI backend (:8200)
│   ├── src/                         Svelte SPA source
│   └── dist/                        Built SPA (committed — no Node needed to run)
├── data/
│   ├── cases/<SC-YYYY-XXXXXXXX>/    Case folders (evidence files)
│   └── sim/                         Data simulation scripts
├── guardrails/
│   └── sherlock_forensic_safety_v1.0.0.md  Nemotron Content Safety policy
└── external/                        Gitignored — blueprints cloned at deploy time
    ├── aiq/                         AI-Q blueprint (phase1_aiq.sh clones this)
    └── rag/                         RAG Blueprint (phase2_rag.sh clones this)
```
