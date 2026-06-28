# Phase 7 — AI-Q Forensic Extensions

Custom proposal. Follows DESIGN.md §7.

## What Phase 7 delivers

1. **Sherlock MCP server** — FastMCP server exposing graph tools over streamable-http (:9901)
2. **AI-Q MCP integration** — `mcp_client` function group: 4 tools auto-registered into AI-Q
3. **Sherlock AI-Q config** — `config_sherlock_frag.yml`: web search OFF, graph+RAG only
4. **Forensic system prompts** — patched `shallow_researcher` + `clarifier` Jinja2 templates
5. **Safety policy** — Nemotron Content Safety policy for forensic deployment (guardrails/sherlock_forensic_safety_v1.0.0.md)

## Architecture

```
Investigator
      │
      ▼
AI-Q Sherlock (:8100)  ← config_sherlock_frag.yml
  │  Persona: Singapore PD forensic co-investigator
  │  HITL: plan-approval enabled
  │  Web search: DISABLED (air-gapped)
  │
  ├─── knowledge_search → RAG-BP (:8081)
  │      Case reports, witness statements, lab reports, transcripts
  │
  └─── mcp_sherlock_tools → Sherlock MCP (:9901)
         graph_query_tool     — entities/suspects from Neo4j
         graph_analyze_tool   — centrality/communities
         extract_entities_tool — ER ingest for new evidence
         list_cases            — discover available cases
```

## Files

| File | Purpose |
|---|---|
| `mcp/sherlock_mcp.py` | FastMCP server wrapping graph/tools.py |
| `deploy/compose.sherlock_mcp.yaml` | Docker Compose for amms-sherlock-mcp |
| `external/aiq/configs/config_sherlock_frag.yml` | AI-Q Sherlock config |
| `deploy/compose.amms.override.yaml` | Updated: prompts mount + Sherlock config env |
| `external/aiq/src/.../shallow_researcher/prompts/researcher.j2` | Patched: Sherlock forensic persona |
| `external/aiq/src/.../clarifier/prompts/plan_generation.j2` | Patched: forensic investigation plan |
| `guardrails/sherlock_forensic_safety_v1.0.0.md` | Safety policy (Nemotron Content Safety) |
| `guardrails/sherlock_forensic_safety_v1.0.0_system_prompt.txt` | Drop-in inference prompts |

## Commands

```bash
# Start Sherlock MCP server
docker compose -p amms -f deploy/compose.sherlock_mcp.yaml up -d

# Restart AI-Q with Sherlock config (from external/aiq/deploy/compose/)
cd external/aiq/deploy/compose
docker compose -p amms --env-file ../.env \
  -f docker-compose.yaml \
  -f /path/to/repo/deploy/compose.amms.override.yaml \
  up -d --no-build aiq-agent

# Check data sources
curl -s http://localhost:8100/v1/data_sources | python3 -m json.tool
```

## Verification (2026-06-28)

```
AI-Q health: {"isAlive": true} at :8100
Sherlock MCP: healthy (port 9901 open, streamable-http)

Tools registered in AI-Q:
  mcp_sherlock_tools__graph_query_tool    ✅
  mcp_sherlock_tools__graph_analyze_tool  ✅
  mcp_sherlock_tools__extract_entities_tool ✅
  mcp_sherlock_tools__list_cases          ✅

Data sources exposed by API:
  knowledge_layer → "Case Documents"  ✅
  graph_tools     → "Case Graph"      ✅

Config active: /app/configs/config_sherlock_frag.yml ✅
Prompts: shallow_researcher + clarifier patched (Sherlock persona) ✅
```

## Design decisions

- **MCP for graph tools**: same pattern as vss-agent; config-only, no Python plugin inside AI-Q
- **Separate Sherlock MCP container**: joins `amms_aiq-network` so AI-Q resolves `sherlock-mcp:9901`
- **Web search disabled**: forensic deployment is air-gapped; no external data leakage
- **Prompts via volume mount**: only `prompts/` subdirs mounted, preserving agent Python code in image
- **Safety policy generated now**: Nemotron Content Safety model deployed at Phase 9 (needs GPU)
- **VSS MCP deferred**: `mcp_vss_agent` config commented out; uncomment when GPU ready + `LVS_ENABLE_MCP=true`

## Known limitations

- Sherlock MCP container installs deps at startup (~60s). Production should use a pre-built image.
- The MCP `streamable-http` reconnects every ~5s (NAT client keep-alive) — expected behavior.
- Safety policy not yet enforced — Nemotron-Content-Safety-Reasoning-4B needs GPU (Phase 9).
- Deep research agent (`gpt_oss_llm`) requires `openai/gpt-oss-120b` availability on build.nvidia.com.
