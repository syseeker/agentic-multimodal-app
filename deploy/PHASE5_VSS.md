# Phase 5 — VSS LVS Profile Deployment

Skill: `vss-deploy-profile` (lvs profile). Blueprint: video-search-and-summarization v3.2.0.

## What Phase 5 deploys

VSS LVS (Live Video Summarization) profile — the video specialist sub-agent for Sherlock.

- **VSS Agent** (`vss-agent`) — REST API for video search, summarization, analytics
- **Elasticsearch** — vector + metadata store for video ER (shared with RAG-BP)
- **Redis** — VSS message queue (shared infrastructure)
- **Kafka + Logstash** — event streaming pipeline
- **Kibana** — analytics dashboard
- **Phoenix** — observability / tracing
- **VST (VIOS) stack** — video ingestion, storage, streaming
- **RT-VLM** (`vss-rtvi-vlm`) — video frame processing + VLM inference [DEFERRED — needs GPU]

## Deployment environment

- Profile: `lvs` | Blueprint: `bp_developer_lvs` | Mode: `2d`
- Brev instance: no local GPU → remote-all mode
- LLM: `nvidia/nvidia-nemotron-nano-9b-v2` via integrate.api.nvidia.com (remote)
- VLM: `nvidia/cosmos-reason2-8b` via integrate.api.nvidia.com (remote)
- Brev UI: `https://7777-blg8vsges.brevlab.com`

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

## Verification

```bash
# vss-agent health
curl -sf http://localhost:8000/health
# Expected: {"value":{"isAlive":true}}

# All containers
docker ps --filter "label=com.docker.compose.project=mdx" \
  --format "{{.Names}}\t{{.Status}}" | sort
```

**Confirmed healthy (2026-06-28):**
- elasticsearch ✅ healthy
- kafka ✅ healthy
- kibana ✅ healthy
- redis ✅ healthy
- vss-agent ✅ **healthy** (core API — the deliverable)
- vss-vios-ingress ✅ healthy
- vss-vios-postgres ✅ healthy
- vss-vios-sensor ✅ healthy
- vss-vios-streamprocessing ✅ healthy
- logstash ✅ running
- sdr-controller ✅ running
- vss-haproxy-ingress ✅ running
- vss-agent-ui ✅ running
- phoenix ✅ running
- vss-vios-nvstreamer-lvs ✅ running

**Deferred:**
- vss-rtvi-vlm — needs GPU (NVDEC hardware video decoder)
- vss-lvs — waits for rtvi-vlm; will start once GPU instance provides rtvi-vlm

## Key gotchas

### 1. VSS uses network_mode=host — port conflicts with other stacks
Almost all VSS services use `network_mode: host`. They bind directly to the host.
Elasticsearch (9200) and Redis (6379) conflicted with existing RAG-BP + NV-Ingest containers.
**Fix:** stop + rm conflicting containers before deploy. VSS becomes owner of ES + Redis.

### 2. Elasticsearch service uses a custom Dockerfile (build:)
The compose has `build: context: .../services/infra, dockerfile: Dockerfiles/elasticsearch.Dockerfile`.
`docker compose config` preserves this build context in resolved.yml.
First pull attempt fails (tries docker.io/library/elasticsearch:latest), then falls back to building.
Build pulls `docker.elastic.co/elasticsearch/elasticsearch:9.3.3` (692 MB).

### 3. nvidia runtime in resolved.yml blocks startup on no-GPU hosts
Services `rtvi-vlm`, `sensor-ms`, `streamprocessing-ms` have `runtime: nvidia`.
`rtvi-vlm` also has `deploy.resources.reservations.devices: [{capabilities: [gpu]}]`.
`docker compose override with devices: []` does NOT remove the existing devices list (list merge).
**Fix:** patch resolved.yml directly with Python to delete these keys.

### 4. rtvi-vlm needs GPU even in remote-all mode
In remote VLM mode, the language model runs remotely, but NVDEC (hardware video decoder)
is always local. Error: `Failed to load Decoder on GPU 0` / `libcuda.so.1: not found`.
**Fix:** deploy rtvi-vlm on a separate GPU instance (RTX PRO 6000 Blackwell).
Config: set `RTVI_VLM_URL=http://<GPU_IP>:8018` in generated.env (lvs-server env var).

### 5. Shared infrastructure ownership
VSS owns Elasticsearch (9200) and Redis (6379) for the whole stack.
RAG Blueprint reconnects to ES at `http://HOST_IP:9200` (not service name) after VSS deploys.
AI-Q uses Postgres (not Redis) — no reconnection needed.
Production note: no re-ingestion needed — users ingest case data at Phase 10 (post-deployment).

### 6. VLM_NAME for LVS remote mode
Remote endpoint: `VLM_NAME=nvidia/cosmos-reason2-8b` (what the catalog advertises).
Integrated/local NIM: `VLM_NAME=nim_nvidia_cosmos-reason2-8b_hf-1208` (rule: `nim_<org>_<model>_<tag>`).
Mismatch → `400 BadParameters: No such model`.

### 7. RTVI_VLM_ENDPOINT has /v1; LLM_BASE_URL and VLM_BASE_URL do NOT
```
LLM_BASE_URL=https://integrate.api.nvidia.com     # no /v1
VLM_BASE_URL=https://integrate.api.nvidia.com     # no /v1
RTVI_VLM_ENDPOINT=https://integrate.api.nvidia.com/v1  # WITH /v1 (RT-VLM quirk)
```

### 8. normalize_resolved_yml.py requires uv; add ~/.local/bin to PATH
```bash
export PATH="$HOME/.local/bin:$PATH"
uv run normalize_resolved_yml.py resolved.yml
```

## Deferred work (Phase 5 follow-up, when GPU instance is ready)

```bash
# On GPU instance (RTX PRO 6000 / H100):
docker login nvcr.io -u '$oauthtoken' -p <NGC_API_KEY>
docker run -d --name vss-rtvi-vlm \
  --runtime nvidia --gpus '"device=0"' \
  -p 8018:8000 \
  -e RTVI_VLM_ENDPOINT=https://integrate.api.nvidia.com/v1 \
  -e RTVI_VLM_MODEL_TO_USE=openai-compat \
  -e RTVI_VLM_MODEL_PATH=none \
  -e NVIDIA_API_KEY=<key> \
  nvcr.io/nvidia/vss-core/vss-rt-vlm:3.2.0

# Then on this instance, update generated.env:
# RTVI_VLM_URL=http://<GPU_IP>:8018
# HARDWARE_PROFILE=RTXPRO6000BW
# And restart lvs-server:
# docker compose -f resolved.yml -p mdx restart lvs-server
```

## Phase 5 gate status: PARTIAL ✅

**In scope and complete:**
- vss-agent API healthy at :8000
- All infrastructure (ES, Redis, Kafka, VST stack) running
- Shared ES + Redis ownership transferred to VSS

**Deferred to GPU phase:**
- rtvi-vlm (NVDEC video decoder)
- vss-lvs (video analysis server — waits for rtvi-vlm)
- MCP enable (`LVS_ENABLE_MCP`) — deferred to Phase 7 (MCP wiring step)
- RAG Blueprint reconnection to VSS ES — deferred (no case data yet; Phase 10 is user ingest)
