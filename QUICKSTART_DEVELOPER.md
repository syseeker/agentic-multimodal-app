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

The investigator-facing UI is at **[http://localhost:8200](http://localhost:8200)**.

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


| File                              | What it is                                                 |
| --------------------------------- | ---------------------------------------------------------- |
| `DESIGN.md`                       | Full architecture decisions — read before any major change |
| `deploy/PHASE*.md`                | What was deployed, why, what failed — one per phase        |
| `deploy/phase*.sh`                | The actual deploy commands — run these                     |
| `deploy/start_all.sh`             | Bring up all services after first-time setup               |
| `deploy/aiq-prompts/`             | Sherlock's Jinja2 persona prompts (committed, editable)    |
| `.claude/CLAUDE.md`               | Context file loaded by Claude Code automatically           |
| `.claude/context/phase-status.md` | Current deployment status, phase by phase                  |


---



## Prerequisites

Before running anything, you need:


| Requirement                | Where to get it                                                                                             |
| -------------------------- | ----------------------------------------------------------------------------------------------------------- |
| Docker + Docker Compose v2 | [https://docs.docker.com/engine/install/](https://docs.docker.com/engine/install/)                          |
| `NVIDIA_API_KEY`           | [https://build.nvidia.com](https://build.nvidia.com) → API Keys (AI Foundations scope)                      |
| `NGC_API_KEY`              | [https://org.ngc.nvidia.com](https://org.ngc.nvidia.com) → API Keys (Catalog + AI Foundations scopes)       |
| `HF_TOKEN`                 | [https://huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) (for MERaLiON gated model) |
| Node.js 20+                | `sudo apt-get install nodejs` or see Step 0 below                                                           |


---



## First-time setup (Option A: phase-by-phase)

Run these phases **in this order** on a new instance. Each phase is a one-time operation.
After all phases are done, use `bash deploy/start_all.sh` as the daily driver.

> **Recommended order: 1 → 2 → 5 → 3 → 4 → 6 → 7 → 8**
>
> Phase 5 (VSS) must run before Phase 3 and Phase 4 because VSS takes ownership of
> Elasticsearch and Redis. If Phase 3/4 run first, they must be re-run after Phase 5
> to re-ingest into the new VSS-owned Elasticsearch. Running Phase 5 first avoids this.
>
> Phase 3 (text cases) runs before Phase 4 (audio) because Phase 4 reads the text files
> Phase 3 generates to synthesise audio samples.



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

### Phase 5 — VSS video analysis

```bash
bash deploy/phase5_vss.sh
```

The script asks what GPU setup you have and picks the right path automatically:

```
1) Local GPU in this machine   (PATH A — full VSS + rtvi-vlm NVDEC here)
2) No GPU in this machine      (PATH C — VSS infra only, no video analysis)
```

**Choose** `1`**.** VSS must run on the machine that has the GPU. On x86_64 the script
detects the card and picks the hardware profile itself (e.g. RTX Pro 6000 →
`RTXPRO6000BW`); override with `export VSS_HW_PROFILE=<H100|L40S|RTXPRO6000BW|RTXPRO4500BW>`
only if the detection warns it fell back to `OTHER`.

Choose `2` only on a box with no GPU. You get vss-agent, Elasticsearch, Redis, Kafka,
Kibana and Phoenix, but **no video analysis** — `rtvi-vlm` is stripped from the compose
because it needs an NVDEC hardware decoder. Text/audio RAG, the entity graph, and the
workbench all still work.

> **There is no remote-GPU option, by design.** Running VSS on a CPU host with
> `rtvi-vlm` on a separate GPU box was tried and does not work: the LVS pipeline assumes
> a single machine (VIOS hands `rtvi-vlm` a *local file path* it cannot read across the
> network, and LVS's GStreamer cannot probe duration over HTTP → `end_offset: 0`, zero
> chunks, empty summary). Full write-up in
> `.claude/context/implementation-learnings.md` → *"CPU-to-Remote-GPU rtvi-vlm
> Integration"*. Put the GPU in the box that runs VSS.

**Checkpoint:** `curl -sf http://localhost:8000/health` → `{"value":{"isAlive":true}}`

> **Note for GB10/DGX Spark (Jovan):** the script detects `aarch64` automatically and
> uses the DGX-SPARK profile — the prompt above is x86_64 only.



#### Phase 5 — Required follow-up: apply rtvi-vlm patches

VSS 3.2.1 has two bugs with Cosmos Reason2-8B that prevent video analysis from working.
**Run this immediately after Phase 5 completes** (on the same instance, every time Phase 5 is re-run):

```bash
bash deploy/patch_vss_rtvi_vlm.sh
```

This patches two files inside the running `vss-rtvi-vlm` container and restarts it:

1. **Model name mismatch** — rtvi-vlm rejects `nvidia/cosmos-reason2-8b` even though the model is loaded; patch normalises it to the NIM format
2. **VIOS URL resolution** — vss-lvs sends an invalid GET path to rtvi-vlm; patch adds a UUID-based fallback that resolves the correct `temp_files` download URL

⚠️ These patches live in the container's writable layer and are **lost on container recreation** (e.g., Phase 5 re-run). Re-run `patch_vss_rtvi_vlm.sh` every time Phase 5 redeploys.

After patching, re-register any videos via the workbench Evidence tab or:

```bash
rm data/cases/<case_id>/<video_stem>_analysis.txt   # remove stale placeholder
uv run data/video/process_video.py --case-id <case_id>
```



### Phase 3 — Forensic cases + data simulation

nv-ingest must be running before Phase 3. Start it first:

```bash
bash deploy/ingest_start.sh
```

This starts nv-ingest, reconnects ingestor-server to VSS's Elasticsearch (with all API keys),  
and patches nv-ingest's `/etc/hosts` so it can reach VSS-owned Redis. Then run Phase 3 (optionally limit to N cases first to verify the pipeline):

```bash
CASE_LIMIT=5 bash deploy/phase3_data_sim.sh   # test with 5 cases first
bash deploy/phase3_data_sim.sh                # ingest all cases
bash deploy/ingest_stop.sh                    # Stop it when done to free ~10 GB RAM:
```

**Checkpoint:** AI-Q answers "who is the suspect in case SC-2024-03C5F0E4?" with a cited answer.

### Phase 4 — Audio pipeline

Generates speech WAVs from case text files, transcribes them with Parakeet ASR, runs MERaLiON paralinguistics (GPU), and ingests transcripts into RAG.

**Step 1 — Install uv** (needed to run the scripts; skip if already installed):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh && source $HOME/.local/bin/env
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
```

**Step 2 — Generate audio** for each case from its text evidence files:

```bash
export PATH="$HOME/.local/bin:$PATH"

# Generate for one case first to verify TTS works
uv run data/sim/generate_audio_samples.py --case SC-2026-F4A2B8C1 --tts magpie

# Then generate for all 20 cases
uv run data/sim/generate_audio_samples.py --all --tts magpie
```

Each case produces two WAVs in `data/cases/<id>/audio/`:

- `witness_interview.wav` — `witness_statement.txt` read by Sofia (EN-US F)
- `phone_call_recording.wav` — `whatsapp_chat.txt` with each speaker auto-assigned a voice matched to their name's language and gender (Vietnamese/Chinese/Indian/English detected automatically)

Requires `NVIDIA_API_KEY` in `.env` for Magpie TTS (cloud, no GPU needed).

**B — Two-voice synthesis from a specific WhatsApp chat file (Magpie)**

Use `--file --chat` to synthesise a single chat file with two distinct voices assigned per speaker.
Speaker names are analysed for gender/language (Vietnamese/Chinese/Indian/Malay/English) automatically.

```bash
uv run data/sim/generate_audio_samples.py \
  --file data/cases/SC-2026-F4A2B8C1/whatsapp_chat.txt \
  --output data/cases/SC-2026-F4A2B8C1/audio/phone_call_recording.wav \
  --tts magpie --chat
```

**C — Hokkien TTS for any text file (GPU +** `HF_TOKEN` **required)**

Input must be Chinese hanzi — translate English witness statements first.
Mixed Chinese-English (Singlish code-switching) is supported by the model.

```bash
export PATH="$HOME/.local/bin:$PATH"
export HF_TOKEN=$(grep '^HF_TOKEN=' .env | cut -d= -f2- | tr -d '[:space:]')

# Synthesize a specific text file (English, Chinese, or mixed) into a case's audio dir
uv run data/sim/generate_audio_samples.py \
  --file data/cases/SC-2024-3D5C4EE1/witness_statement.txt \
  --case SC-2024-3D5C4EE1 \
  --tts hokkien
# Output: data/cases/SC-2024-3D5C4EE1/audio/witness_statement.wav
```

Note: `witness_statement.txt` must be Chinese hanzi for best results.
Mixed content (e.g. "Block 123对面的小贩中心，police截住一个穿黑色jacket的男子") also works.

**Step 3 — Run Phase 4:**

```bash
bash deploy/phase4_audio.sh
```

**Checkpoint:** `data/cases/SC-2024-03C5F0E4/audio_analysis.txt` exists and AI-Q answers "what was said in the audio evidence for case SC-2024-03C5F0E4?" with cited transcript content.

### Phase 6 — Entity graph (Neo4j)

```bash
GRAPH_CASE_LIMIT=3 bash deploy/phase6_graph.sh
bash deploy/phase6_graph.sh
```

Starts Neo4j, runs LLM-based entity/relation extraction over all 20 case files,
writes the graph to Neo4j namespaced by `case_id`.

Note the variable is `GRAPH_CASE_LIMIT` here, **not** the `CASE_LIMIT` used in Phase 3 — it defaults to `0` (all cases), and an unset/misspelled name is silently ignored, so confirm the script echoes `(GRAPH_CASE_LIMIT=N)` rather than `for all cases` before letting it run.

**Checkpoint:** Neo4j browser at [http://localhost:7474](http://localhost:7474) shows entities across cases.
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

**Checkpoint:** [http://localhost:8200](http://localhost:8200) (or Brev: `https://8200-<env-id>.brevlab.com`)
loads the Sherlock workbench. Select a case, type "who are the suspects?" and
verify a cited answer comes back.

---



## After first-time setup: daily operations

All commands below run **on the server** (the Linux machine where Docker is installed),
not on your laptop. SSH in first:

```bash
ssh <user>@<server-ip>
cd ~/agentic-multimodal-app
```



### Starting the stack

```bash
# Start everything: VSS → Neo4j → RAG → Sherlock MCP → VSS Sherlock MCP → AI-Q → Workbench
bash deploy/start_all.sh
```

VSS (step 0) is started first because it owns Elasticsearch and Redis. If Phase 5 was
never run, the VSS step is skipped gracefully. After a Phase 5 re-run, also apply the
rtvi-vlm patches before starting the stack:

```bash
bash deploy/patch_vss_rtvi_vlm.sh   # only needed after Phase 5 re-deploy
bash deploy/start_all.sh
```

`start_all.sh` waits for each service to be healthy before starting the next one.
When it finishes you will see the service URLs printed — the workbench is the last one.

### Accessing the UI from your laptop

The UI runs on the server at port 8200. Your laptop browser cannot reach `localhost:8200`
because `localhost` means *your laptop*, not the server.

**Option A — Direct IP** (simplest, requires port 8200 open in the firewall):

```
http://<server-ip>:8200
```

Replace `<server-ip>` with the server's public IP. Run `curl ifconfig.me` on the server
to find it if you don't know it.

**Option B — SSH tunnel** (works through any firewall, no port needs to be open):
Run this on your laptop (keep the terminal open while you work):

```bash
ssh -L 8200:localhost:8200 <user>@<server-ip>
```

Then open `http://localhost:8200` in your browser. All traffic is routed securely through
your SSH connection.

### Stopping the stack

```bash
# On the server — stops all containers
docker compose -p amms down
```



### Checking service health

```bash
curl http://localhost:8100/health       # AI-Q
curl http://localhost:8081/health       # RAG
curl http://localhost:8200/api/health   # Workbench (also shows AI-Q + Neo4j status)
```



### Tailing logs

```bash
docker logs -f amms-aiq-agent
docker logs -f amms-sherlock-mcp
docker logs -f amms-workbench
```



### Re-ingest a case (after adding new evidence files)

```bash
python3 graph/ingest_entities.py --case SC-2024-XXXXXXXX
```



### Running the workbench outside Docker (dev mode)

If you are iterating on the UI and don't want to rebuild the Docker image each time:

```bash
# On the server — kills any existing instance, starts fresh
kill $(lsof -ti:8200) 2>/dev/null
python3 ui/server.py &
```

Access via SSH tunnel (Option B above) or direct IP.

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

Run Phase 5 **on the machine that has the RTX PRO 6000 or GB10** — VSS and the GPU must
be the same box:

```bash
bash deploy/phase5_vss.sh   # prompts for GPU setup — choose 1 (local GPU)
```

After Phase 5 completes, re-ingest case documents: `bash deploy/phase3_data_sim.sh`
(VSS takes ownership of Elasticsearch, so the old index is gone.)

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

---



## Appendix — Removing Data from Each Store

Quick reference for resetting or reingesting data after a pipeline change.

### What each port is


| Port    | Service                        | What it stores                                                                                                                                                                     |
| ------- | ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `:8082` | RAG Blueprint **ingestor** API | Accepts uploads; manages documents in Elasticsearch. Use this API (not ES directly) to add/remove documents — it also maintains the `document_info` and `metadata_schema` indices. |
| `:8081` | RAG Blueprint **rag-server**   | Query-only. Does not store data.                                                                                                                                                   |
| `:9200` | **Elasticsearch**              | Actual vector store. Owned by VSS (mdx project) after Phase 5. Indices: `multimodal_data` (RAG chunks), `document_info` (file registry), `metadata_schema` (collection schema).    |
| `:6379` | **Redis**                      | nv-ingest task queue (transient — empty when no ingest is running). Owned by VSS after Phase 5.                                                                                    |
| `:7687` | **Neo4j** Bolt                 | Entity/relationship graph. All cases namespaced by `case_id`.                                                                                                                      |


---



### Phase 3 / Phase 4 — Remove documents from RAG (port 8082)

```bash
# Remove specific documents (by the prefixed filename used at upload time)
curl -X DELETE "http://localhost:8082/documents?collection_name=multimodal_data" \
  -H "Content-Type: application/json" \
  -d '["SC-2024-XXXXX_case_report.txt", "SC-2024-XXXXX_audio_analysis.txt"]'

# Remove ALL documents in the collection (wipe and recreate)
curl -X DELETE "http://localhost:8082/collections" \
  -H "Content-Type: application/json" \
  -d '["multimodal_data"]'

# Recreate the empty collection (required before re-ingesting after deletion)
curl -X POST "http://localhost:8082/v1/collection" \
  -H "Content-Type: application/json" \
  -d '{"collection_name":"multimodal_data","metadata_schema":[]}'

# Verify doc count in ES
curl -sf "http://localhost:9200/multimodal_data/_count" | python3 -m json.tool
```

To find the exact prefixed filename for a document:

```bash
curl -sf -X POST http://localhost:8081/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query":"SC-2024-XXXXX audio","collection_name":"multimodal_data","top_k":5}' \
  | python3 -c "import sys,json; [print(r['document_name']) for r in json.load(sys.stdin).get('results',[])]"
```

---



### Phase 4 — Remove per-case audio transcripts from disk

```bash
# Remove transcripts and aggregated analysis for one case (WAVs are kept)
rm data/cases/SC-2024-XXXXX/audio/*_transcript.txt
rm data/cases/SC-2024-XXXXX/audio_analysis.txt

# Remove from RAG as well (see above), then re-run:
bash deploy/phase4_audio.sh
```

---



### Phase 5 — Wipe VSS Elasticsearch indices

VSS owns Elasticsearch after Phase 5. Its indices are separate from RAG's `multimodal_data`.

```bash
# List all indices and their doc counts
curl -sf "http://localhost:9200/_cat/indices?v&h=index,docs.count"

# Delete a specific VSS index (e.g. video dense-caption index)
curl -X DELETE "http://localhost:9200/<index-name>"

# Nuclear: wipe all non-system indices (RAG + VSS — requires re-ingesting everything)
curl -sf "http://localhost:9200/_cat/indices?h=index" | grep -v '^\.' | \
  xargs -I{} curl -X DELETE "http://localhost:9200/{}"
```

---



### Phase 5 — Flush Redis task queue (nv-ingest)

Redis is a transient task queue — only relevant if a job got stuck mid-ingest.

```bash
# Check queue depth (should be 0 when idle)
docker exec redis redis-cli DBSIZE

# Flush all queued jobs (only if ingest is stuck — stops all pending work)
docker exec redis redis-cli FLUSHALL
```

---



### Phase 6 — Remove entities from Neo4j

```bash
# Delete all entities for one case
docker exec amms-neo4j cypher-shell -u neo4j -p sherlock_dev \
  "MATCH (n {case_id: 'SC-2024-XXXXX'}) DETACH DELETE n"

# Check node count per case
docker exec amms-neo4j cypher-shell -u neo4j -p sherlock_dev \
  "MATCH (n) RETURN n.case_id AS case_id, count(n) AS nodes ORDER BY nodes DESC"

# Wipe the entire graph (all cases)
docker exec amms-neo4j cypher-shell -u neo4j -p sherlock_dev \
  "MATCH (n) DETACH DELETE n"
```

---



### Full pipeline reset (re-run from Phase 3)

```bash
# 1. Wipe RAG collection
curl -X DELETE "http://localhost:8082/collections" \
  -H "Content-Type: application/json" -d '["multimodal_data"]'
curl -X POST "http://localhost:8082/v1/collection" \
  -H "Content-Type: application/json" \
  -d '{"collection_name":"multimodal_data","metadata_schema":[]}'

# 2. Wipe Neo4j graph
docker exec amms-neo4j cypher-shell -u neo4j -p sherlock_dev "MATCH (n) DETACH DELETE n"

# 3. Remove audio transcripts and analysis files from disk
find data/cases -name "*_transcript.txt" -delete
find data/cases -name "audio_analysis.txt" -delete

# 4. Re-run phases
bash deploy/phase3_data_sim.sh
uv run data/sim/generate_audio_samples.py --all --tts magpie
bash deploy/phase4_audio.sh
bash deploy/phase6_graph.sh
```

