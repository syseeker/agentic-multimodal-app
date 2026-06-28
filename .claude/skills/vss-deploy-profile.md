# SME Summary: vss-deploy-profile skill

Source: `~/skills/skills/vss-deploy-profile/`
Skill version: 3.2.0
Always re-read the full skill files before implementing; this summary is a quick reference.

---

## What This Skill Does

Selects, configures, deploys, verifies, debugs, and tears down a VSS (Video Search and
Summarization) profile. For this project we use the **lvs** profile (live video summarization
with CA-RAG into Neo4j).

---

## VSS Profiles

| Profile | Reference | Use for this project? |
|---|---|---|
| base | `references/base.md` | No (no CA-RAG) |
| lvs | `references/lvs-profile.md` | **YES — dense captions + CA-RAG + Neo4j + MCP** |
| search | `references/search.md` | No |
| warehouse | `references/warehouse.md` | No |
| edge | `references/edge.md` | No |

---

## LVS Profile Purpose (for this project)

LVS = live video summarization. In CA-RAG mode it:
- Runs RT-VLM to generate dense captions from video
- Embeds captions with RT-Embed (Cosmos-Embed1)
- Writes entity/relationship graph to **shared Neo4j** (CA-RAG)
- Exposes VSS agent via MCP (`LVS_ENABLE_MCP=true`)

The VSS agent is then registered as a sub-agent in AI-Q (Phase 7).

---

## Deployment Flow (from skill)

The skill enforces this exact sequence:
1. Tear down any existing VSS deployment + clear data volumes
2. Validate credentials before any env mutation
3. Gather context (profile, repo path, hardware, LLM/VLM placement, API keys, network addressing)
4. Prepare data directory layout
5. Initialize `generated.env` from source `.env` (never edit source `.env` directly)
6. Build env_overrides dict
7. Apply overrides + dry-run: `docker compose config > resolved.yml`
8. Verify `resolved.yml` has no unexpanded `${...}` tokens
9. Verify NGC artifact access
10. Normalize `resolved.yml` (strip dangling `depends_on`)
11. Review and get user confirmation
12. Deploy: `docker compose up -d`
13. Wait for readiness (cold deploys take 10-20 min)

---

## Prerequisites

```bash
# GPU driver
nvidia-smi

# Docker + NVIDIA Container Toolkit
docker run --rm --gpus all ubuntu nvidia-smi

# NGC credentials
docker login nvcr.io -u '$oauthtoken' -p $NGC_API_KEY

# Disk (VSS full lvs profile ~20-30 GB images)
df -h /
```

Required credentials:
- `NGC_CLI_API_KEY` — local NIM pulls
- `NVIDIA_API_KEY` — remote NIM access (dev mode)
- `HF_TOKEN` — gated models (optional for dev)

---

## Key Environment Variables

| Variable | Purpose | Value for this project |
|---|---|---|
| `PROFILE` | Which profile to deploy | `lvs` |
| `HOST_IP` | In-cluster dial address | auto-detect: `$(hostname -I \| awk '{print $1}')` |
| `EXTERNAL_IP` | Browser-facing address | same as HOST_IP for local dev |
| `HAPROXY_PORT` | Ingress port | `7777` (default) |
| `LLM_MODE` | LLM placement | `remote` (dev: use hosted NIM) |
| `VLM_MODE` | VLM placement | `remote` (dev: use hosted NIM) |
| `LLM_BASE_URL` | Remote LLM endpoint | hosted NIM URL |
| `VLM_BASE_URL` | Remote VLM endpoint | hosted NIM URL |
| `LVS_ENABLE_MCP` | Enable MCP for vss-agent | `true` |
| `LVS_EMB_ENABLE` | Enable RT-Embed for CA-RAG | `true` |

---

## Shared Neo4j Configuration

VSS CA-RAG writes entity/relationship graph to Neo4j.
For this project, VSS shares the **same Neo4j instance** as the non-video ER step (Phase 6).
Cases are namespaced by `case_id` label/property.

Read `references/lvs-profile.md` for exact Neo4j connection env vars.

**Do not deploy a separate Neo4j for VSS** — it must use the shared instance.

---

## MCP for vss-agent (Phase 7 prerequisite)

Setting `LVS_ENABLE_MCP=true` exposes the VSS agent as an MCP endpoint.
AI-Q connects to this endpoint to call the `vss-agent` as a sub-agent (specialist).
Read `references/lvs-profile.md` for the MCP endpoint URL and how to register it in AI-Q.

---

## Readiness Gates

1. Container count > 0 and >= expected for lvs profile
2. Every documented endpoint responds (cold deploys: 10-20 min)
3. UI/API/WS links browser-reachable
4. NIM models warmed and responding

```bash
# Check containers
docker compose -p amms ps

# VSS API health
curl -sf http://localhost:8000/docs  # or appropriate port from lvs profile

# Neo4j connected
# (check vss logs for "Connected to Neo4j" or similar)
```

---

## Project-Specific Notes

- Clone VSS to `external/vss/` (gitignored).
- Always use `generated.env` (skill-managed) — never edit source `.env` directly.
- The dry-run (`docker compose config > resolved.yml`) must show zero unexpanded `${...}` tokens.
- VSS lvs profile starts RT-VLM (dense captioning), RT-Embed, Neo4j CA-RAG, haproxy.
- Startup takes 10-20 minutes on first run due to NIM model warm-up.
- Read `references/lvs-profile.md` in full before starting Phase 5.

---

## Verification for Phase 5

```bash
# After VSS is running:
# 1. Upload a sample video via VIOS or VST sensor API
# 2. Trigger dense captioning
# 3. Query Neo4j for entities/relations from that video
# Phase 5 checkpoint: entities/relations queryable in Neo4j
```
