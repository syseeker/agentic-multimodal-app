# Phase 5 — VSS LVS Profile Deployment

Skill: `vss-deploy-profile` (lvs profile). Blueprint: video-search-and-summarization v3.2.0
(rtvi-vlm / LVS images pinned to **3.2.1** on x86_64).

**Status:** ✅ Complete on RTX Pro 6000 Blackwell (x86_64), 2026-07-28 — full stack
including `rtvi-vlm`, video E2E verified through Sherlock.
⬜ Not yet deployed on GB10 / DGX Spark (aarch64) — the PATH A branch is written but unrun.

> Rewritten 2026-08-18 to describe the local-GPU deploy that actually shipped. The original
> 2026-06-28 CPU-only record is preserved verbatim in the appendix at the bottom — it is
> the PATH C baseline and still accurate for GPU-less hosts. Everything above the appendix
> supersedes it.

---

## What Phase 5 deploys

VSS LVS (Long Video Summarization) profile — the video capability behind Sherlock.

| Service | Role | PATH A (local GPU) | PATH C (no GPU) |
|---|---|---|---|
| `vss-agent` | REST API: video search, summarization, analytics | ✅ | ✅ |
| `vss-rtvi-vlm` | Frame decode (NVDEC) + VLM inference | ✅ | ❌ omitted |
| `vss-lvs` | Long-video analysis server (waits on rtvi-vlm) | ✅ | ❌ |
| Elasticsearch | Vector + metadata store, **shared with RAG-BP** | ✅ | ✅ |
| Redis | VSS message queue, **shared** | ✅ | ✅ |
| Kafka + Logstash | Event streaming | ✅ | ✅ |
| Kibana / Phoenix | Analytics / tracing | ✅ | ✅ |
| VST (VIOS) stack | Video ingestion, storage, streaming | ✅ | ✅ |

On PATH C there is **no video analysis on that host**. The rest of Sherlock (text/audio
RAG, graph, workbench) works normally.

## Deployment paths

`deploy/phase5_vss.sh` selects the path at runtime from `uname -m` + GPU presence:

- **PATH A — local GPU.** The whole stack, rtvi-vlm included, on one machine.
  `aarch64` → GB10/DGX-SPARK (`dev-profile.sh up -p base -H DGX-SPARK`).
  `x86_64` → e.g. RTX Pro 6000 (`dev-profile.sh up -p lvs -H <profile>`).
- **PATH C — no GPU.** Infra only; rtvi-vlm deleted from `resolved.yml`.

> **There is deliberately no remote-GPU path.** Splitting VSS across a CPU host and a
> remote GPU was investigated at length and **does not work**: VIOS hands rtvi-vlm a local
> file path it cannot read across machines, and LVS's GStreamer cannot probe duration over
> HTTP (`end_offset: 0`). PATH B and `gpu_reconnect.sh` were **deleted 2026-07-27**.
> Do not re-add it — put the GPU in the box that runs VSS.
> Full write-up: `.claude/context/implementation-learnings.md` → "CPU-to-Remote-GPU".

## Deployment environment (the verified run)

| | |
|---|---|
| Machine | RTX Pro 6000 Blackwell Server Edition, 96 GB GDDR7, x86_64 (Brev) |
| Hardware profile | `RTXPRO6000BW` (auto-detected from `nvidia-smi`; override `VSS_HW_PROFILE`) |
| Profile / mode | `lvs` / `2d` |
| LLM | `nvidia/nvidia-nemotron-nano-9b-v2` — **remote** (integrate.api.nvidia.com) |
| VLM | **`nvidia/cosmos-reason2-8b`** — **local**, in rtvi-vlm, loaded as `nim_nvidia_cosmos-reason2-8b_hf-1208` (see the ⚠️ below) |
| Image tags | `RTVI_VLM_IMAGE_TAG=3.2.1`, `LVS_TAG=3.2.1` (x86_64 uses non-sbsa tags) |
| UI | `http://localhost:7777` |

> ### ⚠️ Unresolved inconsistency: which VLM does Phase 5 actually load?
>
> **The verified run used Cosmos Reason2-8B**, made to work by `patch_vss_rtvi_vlm.sh`
> Patch 1, which normalises the friendly name to the `nim_` form. Evidence:
> - `mcp/vss_sherlock_mcp.py` — `RTVI_VLM_MODEL` defaults to
>   `nim_nvidia_cosmos-reason2-8b_hf-1208`. This is the code path that produced the
>   verified ~4.3 s results, and it was last edited **2026-08-07, after** the Reason1
>   change, still on Reason2.
> - `QUICKSTART_DEVELOPER.md` — "VSS 3.2.1 has two bugs with **Cosmos Reason2-8B** … run
>   this immediately after Phase 5, every time." Patch 1 is meaningless under Reason1.
> - `deploy/phase3_data_sim.sh` — `_VLM_CTR="nvidia-cosmos-reason2-8b"`.
> - `patch_vss_rtvi_vlm.sh` header, and the phase-status.md RTX Pro 6000 section.
>
> **But `deploy/phase5_vss.sh` defaults to `--vlm nvidia/cosmos-reason1-7b`**, with
> Reason2-8B preserved commented out just above it, and
> `implementation-learnings.md` → "Cosmos Reason2-8B VLM Naming Bug" records switching to
> Reason1-7B as the "workaround (current)". Both landed in the same commit (`13d3d6a`).
>
> Read together: changing the model and patching the container were **two competing fixes
> for the same bug**; the patch is the one that shipped and is documented as mandatory,
> while the script default was left on the other. **A fresh PATH A deploy today would load
> Reason1-7B while the MCP client asks for `nim_nvidia_cosmos-reason2-8b_hf-1208`** — a
> mismatch that Patch 1 does not repair, since it aliases toward the Reason2 name.
> Override with `VIA_VLM_OPENAI_MODEL_DEPLOYMENT_NAME` (MCP) or `VSS_VLM_MODEL` (deploy)
> until this is settled.
>
> **This needs a decision from whoever last ran the box — do not assume either side.**
> VRAM figures also disagree and are not trustworthy as recorded: phase-status.md says
> ~46 GB for Reason2-8B, while the learnings say ~62 GB for Reason2 and ~45–55 GB for
> Reason1. Note also that per the LVS skill, Reason2-8B is **not** on the officially
> supported VLM list (only Reason1-7B and Reason3 Nano are) — which is the argument for
> the Reason1 side.

## Commands

```bash
# 1. Deploy (path selected automatically; prompts on x86_64)
bash deploy/phase5_vss.sh

# 2. PATH A only — re-apply the rtvi-vlm container patches
bash deploy/patch_vss_rtvi_vlm.sh
```

**Recommended phase order:** `1 → 2 → 5 → patch_vss → 3 → 4 → 6 → 7 → 8`.
Phase 5 must precede Phase 3, because VSS takes ownership of Elasticsearch and Redis and
the RAG-BP ingest has to be pointed at VSS's ES.

`phase5_vss.sh` also handles, in order: nvidia-runtime + git-lfs preflight, `nvcr.io`
login, clone to `external/vss-3.2.0`, image-tag patching of the profile `.env`, removal of
the conflicting RAG-BP `elasticsearch`/`compose-redis-1` containers, the deploy itself,
the RAG-BP → VSS-ES reconnect, an nv-ingest `/etc/hosts` fix for `redis`, and the AI-Q
`nvidia-rag` re-attach. First boot waits up to **30 min** — rtvi-vlm downloads ~15 GB of
weights from NGC and builds a TRT engine before `vss-agent` reports healthy.

## Verification

```bash
curl -sf http://localhost:8000/health          # {"value":{"isAlive":true}}
curl -sf -o /dev/null http://localhost:7777    # UI
docker ps --filter "label=com.docker.compose.project=mdx" \
  --format "{{.Names}}\t{{.Status}}" | sort
```

**Video E2E through Sherlock, verified 2026-07-28** (both cited in the workbench as
`[1] mcp_vss_agent__summarize_video`, ~4.3 s inference at 1 fps):

| Clip | Case | Result |
|---|---|---|
| `men_assault.mp4` | homicide | green bottle assault, victim falls, attacker flees |
| `drug-seize.mp4` | drug trafficking | tactical team, 250 g white powder, arrest |

## Key gotchas

### 1. VSS uses `network_mode: host` — it owns Elasticsearch and Redis
Almost every VSS service binds directly to the host, so :9200 and :6379 collide with
RAG-BP's own containers. `phase5_vss.sh` stops and removes `elasticsearch` and
`compose-redis-1`, then re-points rag-server at VSS's ES on the host IP.
This is why **Phase 5 runs before Phase 3**, and why `start_all.sh` brings VSS up as step 0.

### 2. The rtvi-vlm patches live in the container's writable layer and are LOST on recreate
`patch_vss_rtvi_vlm.sh` applies two fixes inside the running `vss-rtvi-vlm` container:
1. `rtvi_vlm_server.py` — accept friendly model-name aliases for the `nim_` format
   (the Reason2-8B naming bug; see gotcha 3).
2. `asset_manager.py` — VIOS URL fallback: name-based `GET` returns 400, so fall back to a
   UUID `timelines` lookup; parse with `json.loads(text())` because VIOS answers
   `text/plain`.

**Re-run after every Phase 5 re-deploy or any `--force-recreate`.** Verify it actually
applied — do not trust exit 0:
```bash
docker exec vss-rtvi-vlm python3 -c "print('friendly name aliases' in open('/opt/nvidia/rtvi/rtvi/server/rtvi_vlm_server.py').read())"
```
> **`docker exec ... python3 -` needs `-i`.** Without it Docker does not forward stdin,
> python reads EOF, runs an empty program and **exits 0** — the patch silently no-ops
> while the script reports success. Same trap bit `patch_aiq_runner.sh`.

### 3. Cosmos Reason2-8B naming bug in rtvi-vlm 3.2.1
vss-lvs sends `generate_captions` with the correct `nim_nvidia_cosmos-reason2-8b_hf-1208`,
but rtvi-vlm's `cosmos-reason2` code path calls its internal vLLM as
`nvidia/cosmos-reason2-8b` → `400 BadParameters: No such model`. The `/v1/chat/completions`
endpoint on :8018 accepts the friendly name (the RTVI frontend routes it), so only the
internal captioning path fails. Reason2-8B is also **not** on the LVS supported-VLM list —
only Reason1-7B and Reason3 Nano are.
**Two competing fixes exist — see the ⚠️ box above.** The one that demonstrably shipped
and is mandatory in the playbook is `patch_vss_rtvi_vlm.sh` Patch 1 (alias the name, keep
Reason2-8B). Switching to Reason1-7B was the other, and is what `phase5_vss.sh` defaults
to. Unreconciled.

### 4. `up -d` against a live VSS stack recreates rtvi-vlm and wipes its patches
`start_all.sh` step 0 therefore **skips** the bring-up when `vss-agent` is already healthy.

### 5. VIOS: no delete, and re-registering 409s
Re-registering a sensor returns 409, and there is **no working delete** in VSS 3.2.1
(by name → 400, by UUID → 400). Never probe a live VIOS with throwaway data: it stays in
`/vst/api/v1/storage/timelines` until storage is wiped. Consequences the MCP layer must
handle: scope every lookup to the case, and among multiple matches take the **most recent
by `startTime`** — an earlier version matched across cases and pulled another case's
footage, which is evidence contamination, not a cosmetic bug.

### 6. `VLM_NAME` must equal the basename of `RTVI_VLM_MODEL_PATH`
Rule: `ngc:nim/<org>/<model>:<tag>` → `nim_<org>_<model>_<tag>`.
Remote endpoint uses the catalog name (`nvidia/cosmos-reason2-8b`); an integrated/local NIM
uses the `nim_...` form. Mismatch → `400 BadParameters: No such model`.

### 7. `RTVI_VLM_ENDPOINT` has `/v1`; `LLM_BASE_URL` and `VLM_BASE_URL` do NOT
```
LLM_BASE_URL=https://integrate.api.nvidia.com          # no /v1
VLM_BASE_URL=https://integrate.api.nvidia.com          # no /v1
RTVI_VLM_ENDPOINT=https://integrate.api.nvidia.com/v1  # WITH /v1 (RT-VLM quirk)
```

### 8. Elasticsearch is built, not pulled
The compose has a `build:` for `Dockerfiles/elasticsearch.Dockerfile`. The first pull
attempt fails against `docker.io/library/elasticsearch:latest`, then falls back to building
(pulls `docker.elastic.co/elasticsearch/elasticsearch:9.3.3`, 692 MB). Expected, not an error.

### 9. `normalize_resolved_yml.py` needs `uv` on PATH
`export PATH="$HOME/.local/bin:$PATH"` before `uv run normalize_resolved_yml.py resolved.yml`.

### 10. PATH A must still emit a `resolved.yml` snapshot
`dev-profile.sh` drives compose itself and never writes a top-level `resolved.yml`, but
`start_all.sh` gates its VSS step on that file existing — so PATH A boxes reported "VSS not
deployed" on every start. PATH A now emits the same snapshot **read-only** (`config` +
normalize, no rtvi-vlm strip).

## Known gaps carried out of Phase 5

- **Video analysis persists nothing (provenance gap).** Verified: 5 `summarize_video` calls
  → 5 rtvi-vlm `/v1/chat/completions` → **0** new ES documents. The direct-to-rtvi-vlm path
  bypasses CA-RAG, so every video question re-runs inference (no caching) and a
  `[N] summarize_video` citation points at a **non-deterministic process, not a stored
  artifact** — weaker than a document citation, which matters for a court-defensible
  deliverable. Tracked in TODO.md → "Persist video analysis to RAG + Neo4j".
- **`LVS /v1/summarize` is unproven here** — 4 lifetime attempts, all failed (502/502/503/503).
  The MCP tool's LVS fallback has therefore never succeeded.
- **`LVS_ENABLE_MCP=false` is residue.** Deferred at Phases 5 and 7 for "no GPU yet", then
  superseded by the custom MCP server (`mcp/vss_sherlock_mcp.py`, commit 13d3d6a — it
  bypasses vss-agent's 31 s overhead that was causing MCP session drops) and never
  revisited. **DESIGN.md still describes video as an agent-in-agent over VSS MCP; that is
  no longer accurate** — see the note in DESIGN.md §3.
- **Analysis is on demand by design.** Evidence upload only registers the video with VIOS
  and writes a marker file; no VLM inference happens at upload.
- **GB10 / DGX Spark (aarch64) not yet deployed.** PATH A branch is ready but unrun; after
  it, `patch_vss_rtvi_vlm.sh` still applies.

## Phase 5 gate status

**PATH A / RTX Pro 6000 — ✅ PASS (2026-07-28)**
- `vss-agent` healthy at :8000; UI at :7777
- `rtvi-vlm` serving Cosmos Reason1-7B locally; `vss-lvs` up
- Shared ES + Redis ownership transferred to VSS; RAG-BP reconnected
- Video E2E verified through Sherlock on two cases (table above)

**PATH C / CPU-only — ✅ PASS (2026-06-28)**, infra only, no video analysis. See appendix.

**GB10 / aarch64 — ⬜ not started.**

---
---

# Appendix — 2026-06-28 CPU-only baseline (historical)

> Preserved as the PATH C record. The "Deferred work" and remote-GPU parts below describe
> the abandoned two-machine topology and are **historical only** — see the PATH B note above.

## Deployment environment

- Profile: `lvs` | Blueprint: `bp_developer_lvs` | Mode: `2d`
- Brev instance: no local GPU → remote-all mode
- LLM: `nvidia/nvidia-nemotron-nano-9b-v2` via integrate.api.nvidia.com (remote)
- VLM: `nvidia/cosmos-reason2-8b` via integrate.api.nvidia.com (remote)

## Files created

| File | Purpose |
|---|---|
| `external/video-search-and-summarization/` | VSS blueprint (gitignored) |
| `deploy/docker/developer-profiles/dev-profile-lvs/generated.env` | VSS env overrides |
| `deploy/docker/resolved.yml` | Resolved compose (after dry-run + normalize) |
| `deploy/docker/no-gpu-override.yml` | Compose override stripping GPU requirements |

## Commands run

```bash
# 1. Clone VSS blueprint
git clone --branch v3.2.0 \
  https://github.com/NVIDIA-AI-Blueprints/video-search-and-summarization \
  external/video-search-and-summarization

# 2. Generate resolved.yml (stdout only — no 2>&1)
cd external/video-search-and-summarization/deploy/docker
ENV_GEN="developer-profiles/dev-profile-lvs/generated.env"
docker compose --env-file "$ENV_GEN" config > resolved.yml

# 3. Normalize (strip 49 dangling optional depends_on)
uv run normalize_resolved_yml.py resolved.yml

# 4. Patch resolved.yml — remove nvidia runtime + GPU devices (remote-all, no local GPU)
python3 patch_remove_gpu.py  # strips runtime:nvidia and deploy.resources.reservations.devices
                              # from: rtvi-vlm, sensor-ms, streamprocessing-ms

# 5. Create data directories
mkdir -p ~/vss-data/data_log/{analytics_cache,calibration_toolkit,elastic/{data,logs},kafka,redis/{data,log}}
mkdir -p ~/vss-data/agent_eval/{dataset,results}
chmod -R 777 ~/vss-data/data_log ~/vss-data/agent_eval

# 6. Stop conflicting containers (VSS owns ES + Redis)
docker stop elasticsearch compose-redis-1
docker rm elasticsearch compose-redis-1

# 7. Deploy
docker compose -f resolved.yml --env-file "$ENV_GEN" -p mdx up -d
```

**Confirmed healthy (2026-06-28):** elasticsearch, kafka, kibana, redis, **vss-agent**,
vss-vios-ingress, vss-vios-postgres, vss-vios-sensor, vss-vios-streamprocessing (healthy);
logstash, sdr-controller, vss-haproxy-ingress, vss-agent-ui, phoenix,
vss-vios-nvstreamer-lvs (running).

**Deferred at the time:** `vss-rtvi-vlm` (needs GPU — NVDEC hardware video decoder),
`vss-lvs` (waits on rtvi-vlm). Both **since delivered on PATH A** — see the top of this file.

### Historical gotcha: rtvi-vlm needs a GPU even in remote-all mode
In remote VLM mode the language model runs remotely, but NVDEC is always local.
Error: `Failed to load Decoder on GPU 0` / `libcuda.so.1: not found`.
The fix attempted at the time — running rtvi-vlm on a separate GPU instance with
`RTVI_VLM_URL=http://<GPU_IP>:8018` — **was abandoned**; VSS LVS is single-machine.
