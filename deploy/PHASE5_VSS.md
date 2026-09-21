# Phase 5 — VSS LVS Profile Deployment

Skill: `vss-deploy-profile` (lvs profile). Blueprint: video-search-and-summarization v3.2.0
(rtvi-vlm / LVS images pinned to **3.2.1** on x86_64).

**Status:** ✅ Complete on RTX Pro 6000 Blackwell (x86_64), 2026-07-28 — full stack
including `rtvi-vlm`, video E2E verified through Sherlock.
⬜ Not yet deployed on GB10 / DGX Spark (aarch64) — the PATH A branch is written but unrun.


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

> ### ⚠️ Which VLM is loaded is unresolved — check the box, do not guess
>
> `deploy/phase5_vss.sh` deploys `--vlm nvidia/cosmos-reason1-7b`, but
> `mcp/vss_sherlock_mcp.py` requests `nim_nvidia_cosmos-reason2-8b_hf-1208`, and
> `QUICKSTART_DEVELOPER.md` treats the Reason2 name patch as mandatory. Changing the model
> and patching the container were two competing fixes for the same naming bug; both landed
> in the same commit and neither was backed out.
>
> **Resolve it empirically on the running box:**
> ```bash
> curl -s http://localhost:8018/v1/models | jq -r '.data[0].id'
> ```
> That string is what the server actually advertises — use it verbatim wherever a model
> name is required. Recorded VRAM figures also disagree (~46 GB vs ~62 GB); Phase 9e
> measures it.

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
  replaced by the custom MCP server (`mcp/vss_sherlock_mcp.py`), which bypasses vss-agent's
  ~31 s overhead and the MCP session drops it caused. **DESIGN.md still describes video as an agent-in-agent over VSS MCP; that is
  no longer accurate** — see the note in DESIGN.md §3.
- **Analysis is on demand by design.** Evidence upload only registers the video with VIOS
  and writes a marker file; no VLM inference happens at upload.
- **GB10 / DGX Spark (aarch64) not yet deployed.** PATH A branch is ready but unrun; after
  it, `patch_vss_rtvi_vlm.sh` still applies.

## Phase 5 gate status

**PATH A / RTX Pro 6000 — ✅ PASS (2026-07-28)**
- `vss-agent` healthy at :8000; UI at :7777
- `rtvi-vlm` serving the Cosmos VLM locally on vLLM; `vss-lvs` up
  (which VLM exactly — see the ⚠️ note above; confirm with `/v1/models`)
- Shared ES + Redis ownership transferred to VSS; RAG-BP reconnected
- Video E2E verified through Sherlock on two cases (table above)

**PATH C / CPU-only — ✅ PASS**, infra only, no video analysis.

**GB10 / aarch64 — ⬜ not started.**
