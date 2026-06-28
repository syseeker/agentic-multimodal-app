# Implementation Learnings

Lessons from past implementation attempts. Update this file after each phase.
Future Claude instances and developers must read this before starting a phase.

---

## Meta: What Went Wrong on the Previous Instance

The previous Claude instance did not follow the skill-first rule strictly enough.
Key failure modes observed:

1. **Did not read skill MD files first.** The `aiq-deploy` and `rag-blueprint` skills
   contain the exact Docker images, env var names, config file names, and verification
   commands. Improvising without reading these leads to divergence from the SME path.

2. **Disk space not monitored.** The instance ran out of disk mid-Phase 3. Always check
   available disk before pulling large container images.
   ```bash
   df -h /  # check root disk
   docker system df  # check Docker space usage
   ```

3. **Phase 3 was started before Phases 1-2 were fully verified and committed.** Each
   phase must be confirmed before the next begins.

---

## General Rules Learned

### Always Check Disk Before Pulling Images
Docker images for NVIDIA NIMs and blueprints can be several GB each.
```bash
df -h /
docker system df
# Clean unused images if needed (ask user before running):
# docker image prune -f
```

### Docker Project Name is `amms`
All containers for this project run under `COMPOSE_PROJECT_NAME=amms`.
This isolates them from any other AI-Q or RAG stack on the host.
Never run `docker compose` in the blueprint directories directly — always use the
project's deploy scripts or override files that set this project name.

### AI-Q Runs on Port 8100 (Not 8000)
The compose override maps AI-Q to host port 8100 to avoid collisions.
Health check: `curl -sf http://localhost:8100/health`
The default AI-Q port (8000) must remain unmapped to the host.

### RAG Blueprint Network
RAG Blueprint and AI-Q communicate over the `nvidia-rag` Docker network.
This network is created by the RAG Blueprint compose stack.
AI-Q must be connected to it after RAG is deployed.

### Web Search Must Be OFF
AI-Q must use a config that has web search disabled.
Config file: `config_web_default_llamaindex.yml` (no FRAG) or `config_web_frag.yml` (with FRAG).
Both disable web search — confirmed in Phase 1 and 2 respectively.
Never use a config with web tools enabled (air-gapped requirement).

### FRAG = AI-Q's RAG Integration Point
FRAG is AI-Q's built-in mechanism to wire an external RAG server as its knowledge layer.
The RAG Blueprint is connected to AI-Q via FRAG by setting:
- `BACKEND_CONFIG=config_web_frag.yml`
- `RAG_SERVER_URL=http://rag-server:8081`
- `RAG_INGEST_URL=http://ingestor-server:8082`

### Elasticsearch is the Default Vector Store
The previous instance confirmed: Elasticsearch (not Milvus) is the default for both
RAG Blueprint v2.6.0 and VSS CA-RAG. Milvus/cuVS is an optional production swap for GPU.
Do not assume Milvus — use Elasticsearch unless the user explicitly requests otherwise.

---

## Phase 1 Learnings (AI-Q Deployment)

*(Populated from PHASE1_AIQ.md — previous instance, re-verify on redeploy)*

- Clone AI-Q to `external/aiq` (gitignored). Tag: `v2.1.0`.
- The compose override file `deploy/compose.amms.override.yaml` handles:
  - Container name prefixing (`amms-aiq-agent`, `amms-aiq-postgres`)
  - Port mapping to 8100
  - Project isolation
- Bring up only `aiq-agent` service (not the full stack, which includes the UI).
- Postgres tables `aiq_jobs` and `aiq_checkpoints` must exist before declaring healthy.
- Agents endpoint: `GET http://localhost:8100/v1/agents`
  Should return `deep_researcher` and `shallow_researcher`.

## Phase 2 Learnings (RAG Blueprint) — CRITICAL: Previous approach caused Phase 3 failures

The previous agent only partially read the rag-blueprint skill. Three things were missed
that caused Phase 3 (cited deep-research) to keep failing:

### What was missed:

1. **Agentic RAG not enabled.** RAG-BP has an internal LangGraph pipeline
   (`ENABLE_AGENTIC_RAG=true`) that produces significantly better, cited answers.
   Without it, FRAG uses basic retrieval and citation quality is poor.
   Always enable this in Phase 2 before testing the citation chain.

2. **Phase 2 checkpoint was too shallow — citations not verified.** The previous agent
   only checked that AI-Q and RAG-BP could reach each other (HTTP 200). It deferred
   ingestion and citation verification to Phase 3 — wrong. Phase 2 must verify:
   ingest a sample doc → AI-Q queries via FRAG → answer includes citations.
   If this doesn't work in Phase 2, Phase 3 has no foundation.

3. **RAG-BP MCP server not set up.** RAG-BP exposes a FastMCP server wrapping RAG
   (`/v1/generate`, `/v1/search`) AND Ingestor tools. Phase 7 needs this to register
   RAG-BP as a callable tool in AI-Q (for ingestion during active cases).
   Set it up in Phase 2 and record the endpoint for Phase 7.

### Architecture clarification learned:
- **FRAG**: AI-Q's integration point — routes knowledge-layer queries through RAG-BP
- **Agentic RAG**: RAG-BP's internal LangGraph pipeline, activated by `ENABLE_AGENTIC_RAG=true`
  or per-request `agentic: true`. Transparent to AI-Q — AI-Q still uses FRAG, but
  RAG-BP internally uses planner/synthesizer.
- **MCP**: Separate capability layered on top — exposes RAG + Ingestor as callable tools.
  FRAG and MCP can coexist.
- **CRITICAL**: `agentic: true` requests inside RAG-BP BYPASS NeMo Guardrails and query
  decomposition. Apply Sherlock's safety policy at the AI-Q layer (Phase 7), not inside RAG-BP.

### Correct Phase 2 approach:
See `deploy/PHASE2_RAG.md` for the full revised implementation.
Short version:
1. Deploy RAG-BP (NVIDIA-hosted NIMs, Elasticsearch) — same as before
2. Enable `ENABLE_AGENTIC_RAG=true` on rag-server — NEW
3. Wire to AI-Q via FRAG — same as before
4. Set up RAG-BP MCP server on port 8083 — NEW
5. MANDATORY checkpoint: ingest test doc → query via FRAG → verify citations in answer — NEW

## Phase 3 Learnings (Forensic Config + Demo Cases)

*(Not yet completed on any instance — populate after doing it)*

- Read `aiq-deploy` skill's `references/configs.md` before touching AI-Q config.
- Read `data-designer` skill before generating synthetic case data.
- Forensic prompts must be in a separate config file that overrides AI-Q defaults.
  Do not edit AI-Q's checked-in config files — create overlay configs.
- Collections must be namespaced by case: `sherlock_{case_id}`
- AI-Q's FRAG config must specify the correct collection name for each case query.

---

## Disk Space Reference (approximate image sizes)

| Component | Approx disk |
|---|---|
| AI-Q backend image | ~5-8 GB |
| RAG Blueprint (ES + ingestor + rag-server) | ~10-15 GB |
| NV-Ingest | ~5 GB |
| VSS (full lvs profile) | ~20-30 GB |
| Parakeet ASR NIM | ~3-5 GB |
| MERaLiON-3 (self-hosted) | ~8-12 GB |

**Ensure at least 80 GB free before starting Phase 1-2. 200 GB+ for Phase 5 (VSS).**
