# Phase 2 — RAG Blueprint: Deploy + FRAG + Agentic RAG + MCP

**NVIDIA skills used:** `rag-blueprint` (full skill, ALL reference files) + `aiq-deploy → references/frag.md`

**Goal (DESIGN.md Phase 2):** Deploy RAG Blueprint, wire as AI-Q's FRAG knowledge layer,
verify citations end-to-end (ingest → AI-Q retrieves with citations). Set up Agentic RAG
and MCP server so Phase 3 and Phase 7 have the foundation they need.

---

## What the Previous Implementation Got Wrong

The previous Phase 2 only partially read the rag-blueprint skill and missed:

1. **Agentic RAG not enabled** (`ENABLE_AGENTIC_RAG=true` missing).
   RAG-BP has an internal LangGraph pipeline (planner → task executor → seed generator →
   synthesis) that produces significantly better, more cited answers. Without it, FRAG
   uses basic retrieval — and Phase 3 (cited deep-research over case files) kept failing
   because citations were weak or missing.

2. **Phase 2 checkpoint was too shallow.** Only verified that AI-Q and RAG-BP were
   reachable from each other (HTTP 200 on `/health`). Did NOT verify the full citation
   chain: ingest doc → AI-Q queries via FRAG → answer includes citations back to the doc.
   Ingestion was "deferred to Phase 3" — wrong. If citation doesn't work in Phase 2,
   Phase 3 has nothing to stand on.

3. **MCP server on RAG-BP not set up.** RAG-BP exposes a FastMCP server wrapping both
   RAG tools (`/v1/generate`, `/v1/search`, `/v1/get_summary`) and Ingestor tools
   (`create_collection`, `upload_documents`, etc.). This is needed in Phase 7 when AI-Q
   registers RAG-BP as a tool (for ingestion during an active case). Missing this means
   Phase 7 would have had to revisit Phase 2 work.

4. **Agentic RAG bypasses guardrails and query decomposition.** This is documented in the
   skill and was not noted in the previous implementation. Relevant for Phase 7 when we
   configure guardrails: agentic RAG requests (`agentic: true`) bypass NeMo Guardrails
   and query decomposition — so guardrails must be applied at the AI-Q layer, not relied
   upon inside RAG-BP.

---

## Corrected Phase 2 Design

### Integration strategy (from full skill reading)

FRAG is correct as the primary integration (as per DESIGN.md). It routes AI-Q's
knowledge-layer queries through RAG-BP's `/v1/generate` endpoint. Enabling Agentic RAG
on RAG-BP makes those FRAG-driven queries use the richer LangGraph pipeline transparently
— AI-Q still uses FRAG, but RAG-BP internally uses planner/synthesizer.

MCP is a separate capability layered on top — it exposes RAG + Ingestor as callable tools
for Phase 7's AI-Q extension. Both can coexist.

```
AI-Q (Sherlock)
  ├── FRAG (knowledge layer) ──────► RAG-BP /v1/generate (Agentic RAG pipeline)
  │                                          │ cites sources back via FRAG response
  └── MCP tool (Phase 7) ───────────► RAG-BP MCP server (ingest + query as tools)
```

### What changes from previous approach

| Aspect | Previous | Corrected |
|---|---|---|
| Agentic RAG | Not enabled | `ENABLE_AGENTIC_RAG=true` on rag-server |
| Phase 2 checkpoint | Reachability only | Full citation chain verified |
| Ingestion in Phase 2 | Deferred to Phase 3 | Done in Phase 2 checkpoint |
| MCP server | Not set up | Set up, port noted for Phase 7 |
| Guardrail note | Not documented | Agentic RAG bypasses guardrails — apply at AI-Q layer |

---

## Deployment Steps

### Prerequisites (from skill `references/deploy.md` Phase 1-3)

```bash
# Env analysis — auto-detect per skill
docker --version && docker compose version
nvidia-smi 2>/dev/null || echo "No GPU — will use NVIDIA-hosted NIMs"
df -h /  # Need ~20GB free for RAG stack
echo "NGC_API_KEY length: $(grep -c . <<< "$NGC_API_KEY") chars"

# No GPU = nvidia-hosted mode (skill deploy.md Phase 4 routing)
```

### Step 1: Clone RAG Blueprint (locate-or-clone pattern)

```bash
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RAG_DIR="$ROOT/external/rag"
RAG_REF="${RAG_REF:-v2.6.0}"

[ -d "$RAG_DIR/.git" ] || git clone https://github.com/NVIDIA-AI-Blueprints/rag.git "$RAG_DIR"
cd "$RAG_DIR"
git fetch --depth 1 origin tag "$RAG_REF" 2>/dev/null || true
git checkout "$RAG_REF" 2>/dev/null || true
echo "RAG Blueprint at: $(git describe --tags 2>/dev/null || git rev-parse --short HEAD)"
# Verify compose files per skill
test -f deploy/compose/docker-compose-rag-server.yaml && echo "rag-server compose: OK"
test -f deploy/compose/nvdev.env && echo "nvdev.env: OK"
```

### Step 2: Environment setup (skill `env-and-secrets.md` pattern)

```bash
# Propagate shared keys from project root .env
"$ROOT/deploy/propagate_env.sh" "$RAG_DIR/deploy/compose/.env"

# Source NVIDIA-hosted NIM endpoints (nvdev.env has cloud model URLs pre-configured)
# This is the nvidia-hosted mode per skill docker-nvidia-hosted.md
set -a
source "$RAG_DIR/deploy/compose/nvdev.env"
set +a

# Presence check (never print values)
grep -q '^NVIDIA_API_KEY=.\+' "$RAG_DIR/deploy/compose/.env" \
  && echo "NVIDIA_API_KEY=SET" \
  || { echo "NVIDIA_API_KEY MISSING — fill project .env then re-run"; exit 2; }
```

### Step 3: Deploy vector DB (Elasticsearch + SeaweedFS)

```bash
# Per skill docker-nvidia-hosted.md: start vectordb first, wait healthy
cd "$RAG_DIR"
PROJECT="amms"
COMPOSE_VDB="docker compose -p $PROJECT --env-file deploy/compose/.env \
  --env-file deploy/compose/nvdev.env -f deploy/compose/vectordb.yaml"

$COMPOSE_VDB up -d

# Wait for Elasticsearch (skill: 5-10 min first run for NVIDIA-hosted)
echo "Waiting for Elasticsearch..."
until curl -sf "http://localhost:9200/_cluster/health" | python3 -c \
  "import sys,json; s=json.load(sys.stdin)['status']; sys.exit(0 if s in ['green','yellow'] else 1)" 2>/dev/null; do
  sleep 10; echo "  ...waiting"
done
echo "Elasticsearch=healthy"
```

### Step 4: Deploy Ingestor (NV-Ingest, ingestor-server, redis)

```bash
COMPOSE_INGEST="docker compose -p $PROJECT --env-file deploy/compose/.env \
  --env-file deploy/compose/nvdev.env -f deploy/compose/docker-compose-ingestor-server.yaml"

$COMPOSE_INGEST up -d

# Wait for ingestor health
until curl -sf "http://localhost:8082/health" >/dev/null 2>&1; do
  sleep 10; echo "  ...waiting for ingestor"
done
echo "Ingestor=healthy"
```

### Step 5: Deploy RAG server with Agentic RAG enabled

**NEW vs previous implementation.** `ENABLE_AGENTIC_RAG=true` activates the LangGraph
pipeline (planner → task executor → seed generator → synthesis) which produces richer,
cited answers — essential for Phase 3.

```bash
COMPOSE_RAG="docker compose -p $PROJECT --env-file deploy/compose/.env \
  --env-file deploy/compose/nvdev.env -f deploy/compose/docker-compose-rag-server.yaml"

# Enable Agentic RAG — this sets the LangGraph pipeline for all /v1/generate calls
# IMPORTANT: agentic RAG bypasses NeMo Guardrails and query decomposition.
# Guardrails for Sherlock must be applied at the AI-Q layer (Phase 7), not here.
export ENABLE_AGENTIC_RAG=true

$COMPOSE_RAG up -d

# Wait for RAG server with full dependency check (LLM, embedding, NV-Ingest)
# Per skill: NVIDIA-hosted mode 5 min max
echo "Waiting for RAG server (with dependencies)..."
DEADLINE=$(( $(date +%s) + 300 ))
until curl -sf "http://localhost:8081/v1/health?check_dependencies=true" | \
  python3 -c "import sys,json; r=json.load(sys.stdin); sys.exit(0 if r.get('status')=='healthy' else 1)" 2>/dev/null; do
  [ $(date +%s) -gt $DEADLINE ] && { echo "RAG server health timeout"; exit 3; }
  sleep 10; echo "  ...waiting for RAG server"
done
echo "RAG server=healthy (Agentic RAG enabled)"
```

### Step 6: Wire AI-Q via FRAG (aiq-deploy skill `references/frag.md`)

```bash
# Per frag.md: configure AI-Q to point at RAG server and ingestor
AIQ_DIR="$ROOT/external/aiq"
cd "$AIQ_DIR"

# Update AI-Q deploy/.env to FRAG config
python3 - <<'PY'
from pathlib import Path
path = Path("deploy/.env")
updates = {
    "BACKEND_CONFIG": "/app/configs/config_web_frag.yml",
    "RAG_SERVER_URL": "http://rag-server:8081",
    "RAG_INGEST_URL": "http://ingestor-server:8082",
}
lines = path.read_text().splitlines(); seen = set(); out = []
for ln in lines:
    s = ln.strip()
    if s and not s.startswith("#") and "=" in s:
        k = s.split("=",1)[0].strip()
        if k in updates:
            out.append(f"{k}={updates[k]}"); seen.add(k); continue
    out.append(ln)
for k, v in updates.items():
    if k not in seen: out.append(f"{k}={v}")
path.write_text("\n".join(out) + "\n")
print("AI-Q FRAG config updated")
PY

# Restart AI-Q with new FRAG config
OVERRIDE="$ROOT/deploy/compose.amms.override.yaml"
PROJECT="amms"
COMPOSE_AIQ="docker compose -p $PROJECT --env-file deploy/.env \
  -f deploy/compose/docker-compose.yaml -f $OVERRIDE"
BUILD_TARGET=release $COMPOSE_AIQ up -d --build aiq-agent

# Per frag.md: connect AI-Q container to nvidia-rag network
# Note: must repeat if amms-aiq-agent is recreated
docker network connect nvidia-rag amms-aiq-agent 2>/dev/null || true
echo "AI-Q connected to nvidia-rag network"

# AI-Q health check
curl --retry 10 --retry-delay 5 --retry-all-errors -sf \
  "http://localhost:${AIQ_PORT:-8100}/health" >/dev/null \
  && echo "AI-Q backend=healthy on FRAG config"
```

### Step 7: Set up RAG-BP MCP server (NEW — missed in previous implementation)

**Why:** Phase 7 needs AI-Q to call RAG-BP as a tool (for ingestion during active cases).
RAG-BP's MCP server wraps both RAG tools and Ingestor tools via FastMCP.
Set it up now and record the endpoint for Phase 7.

```bash
cd "$RAG_DIR"
# MCP server is in examples/nvidia_rag_mcp/mcp_server.py
# Transport: sse (HTTP-based, long-running)
# Port: default varies — use 8083 to avoid collision
# Requires: python 3.11+, RAG-BP running (rag-server:8081, ingestor:8082)
pip install fastmcp 2>/dev/null || true
MCP_PORT=8083
APP_VECTORSTORE_URL="http://localhost:9200" \
RAG_SERVER_URL="http://localhost:8081" \
RAG_INGEST_URL="http://localhost:8082" \
python examples/nvidia_rag_mcp/mcp_server.py --transport sse --port $MCP_PORT &
MCP_PID=$!
sleep 5
curl -sf "http://localhost:$MCP_PORT" >/dev/null 2>&1 \
  && echo "RAG-BP MCP server=up on :$MCP_PORT (PID=$MCP_PID)" \
  || echo "MCP server startup check — verify manually"
echo "MCP_ENDPOINT=http://localhost:$MCP_PORT  # record for Phase 7"
```

### Step 8: Phase 2 checkpoint — END-TO-END citation test (NEW — critical)

**The previous implementation deferred ingestion to Phase 3. This was the root cause of
Phase 3 failures.** Phase 2 is not done until we verify the full chain:
ingest → AI-Q queries via FRAG → citations appear in the answer.

```bash
COLLECTION="sherlock_phase2_test"

# 8a. Create a test collection
curl -sf -X POST "http://localhost:8082/v1/collection" \
  -H "Content-Type: application/json" \
  -d "{\"collection_name\": \"$COLLECTION\"}" | python3 -c \
  "import sys,json; r=json.load(sys.stdin); print('Collection:', r)"

# 8b. Ingest a sample forensic document (use a text file as minimal test)
cat > /tmp/test_evidence.txt << 'EOF'
CASE SHK-TEST-001 — Interview transcript
Date: 2025-01-15
Subject: Tan Ah Kow (DOB 1985-03-12)
Location: Jurong Police Division

Q: Where were you on the night of 10 January 2025?
A: I was at Changi Airport, Terminal 3, meeting a business partner named John Lim.
Q: What was the nature of the meeting?
A: We discussed a cargo shipment arriving from Bangkok.
EOF

curl -sf -X POST "http://localhost:8082/v1/documents" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@/tmp/test_evidence.txt" \
  -F "collection_name=$COLLECTION" \
  -F "document_name=test_evidence_transcript.txt" \
  | python3 -c "import sys,json; r=json.load(sys.stdin); print('Ingest:', r)"

# Wait for ingestion to complete
sleep 15

# 8c. Query via RAG-BP directly first (verify RAG-BP citing works independently)
curl -sf -X POST "http://localhost:8081/v1/generate" \
  -H "Content-Type: application/json" \
  -d "{
    \"messages\": [{\"role\": \"user\", \"content\": \"Where was Tan Ah Kow on 10 January 2025?\"}],
    \"collection_name\": \"$COLLECTION\",
    \"use_knowledge_base\": true,
    \"agentic\": true
  }" | python3 -c "
import sys,json
r=json.load(sys.stdin)
print('RAG-BP answer:', r.get('choices',[{}])[0].get('message',{}).get('content','(empty)')[:300])
"

# 8d. Verify AI-Q retrieves via FRAG with citations
# (AI-Q must be able to reach rag-server:8081 via the nvidia-rag network)
AIQ_URL="http://localhost:${AIQ_PORT:-8100}"
python3 skills/aiq-research/scripts/aiq.py chat \
  "Using the RAG knowledge base, what was Tan Ah Kow's location on 10 January 2025?" \
  2>/dev/null || echo "aiq.py chat — check manually at $AIQ_URL"

echo "=== Phase 2 checkpoint complete ==="
echo "Verify: AI-Q answer should cite 'test_evidence_transcript.txt'"
echo "If citations are absent, Phase 3 (cited deep-research) will fail."
echo "Do NOT proceed to Phase 3 until citations are verified."
```

---

## Key Architecture Notes for Future Phases

### For Phase 3 (Forensic config + demo cases)
- Collections are namespaced by case: `sherlock_{case_id}`
- Ingest via `POST /v1/documents` with `collection_name=sherlock_{case_id}`
- AI-Q's FRAG config must be told which collection to query (configure in AI-Q's
  forensic config overlay, Phase 3)
- Agentic RAG is now on — demo cases should show rich cited answers

### For Phase 7 (Extend AI-Q)
- RAG-BP MCP endpoint: `http://localhost:8083` (set up in Step 7 above)
- MCP tools available: `generate`, `search`, `get_summary` (RAG) + `create_collection`,
  `upload_documents` (Ingestor) — AI-Q can ingest new evidence during an active case
- **Guardrails WARNING**: `agentic: true` requests bypass NeMo Guardrails inside RAG-BP.
  Apply Sherlock's safety policy at the AI-Q layer (`nemotron-policy-generator` output),
  not inside RAG-BP.
- Register MCP endpoint in AI-Q's forensic config overlay (Phase 7)

---

## Container Inventory (project `amms`)

| Container | Purpose | Port |
|---|---|---|
| `amms-aiq-agent` | AI-Q backend (FRAG mode) | 8100 |
| `amms-aiq-postgres` | AI-Q job/checkpoint store | (internal) |
| `elasticsearch` | Vector store (shared: RAG-BP + VSS) | 9200 |
| `seaweedfs` (or equiv.) | Blob/object store | varies |
| `ingestor-server` | Document ingestion + NV-Ingest | 8082 |
| `amms-nv-ingest-ms-runtime-*` | Document parsing | (internal) |
| `amms-redis-*` | Ingestor message queue | (internal) |
| `rag-server` | RAG query + Agentic RAG LangGraph | 8081 |
| `rag-frontend` | RAG browser UI (optional) | 8090 |
| RAG-BP MCP server | MCP tool server (for Phase 7) | 8083 (process, not container) |

Networks: `amms_default`, `nvidia-rag` (RAG-BP creates; AI-Q connects to it)

---

## Caveats and Lessons Learned

1. **Read the ENTIRE skill before implementing.** The previous agent skipped
   `configure/agentic-rag.md` and `configure/mcp.md` — that caused Phase 3 failures.
2. **Don't defer the checkpoint.** If citation doesn't work in Phase 2, Phase 3 has
   no foundation. Verify the full chain here.
3. **Agentic RAG bypasses guardrails inside RAG-BP.** Apply guardrails at AI-Q.
4. **frag.md caveat:** If `amms-aiq-agent` is recreated, re-run `docker network connect nvidia-rag amms-aiq-agent`.
5. **MCP server is a process, not a container** (in this deploy). Consider containerizing
   it in a later iteration for production robustness.
6. **`ENABLE_AGENTIC_RAG=true` affects all requests** to rag-server. Per-request override:
   pass `agentic: false` in the API payload to use basic RAG for a specific call.
