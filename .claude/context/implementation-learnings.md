# Implementation Learnings

Lessons from past implementation attempts. Update this file after each phase.
Future Claude instances and developers must read this before starting a phase.

---

## Meta: Collaboration Rules (Learned During This Session)

### Recommend before deciding — always

Claude auto-decided the following without asking the developer first, and was corrected:
- ASR model (Parakeet RNNT Multilingual) — should have surfaced the model options with tradeoffs
- Singapore name list composition and nationality weights — shapes the dataset quality
- WhatsApp format (8-15 messages, Singlish system prompt) — shapes what Sherlock learns
- Ingest endpoint fix — was trivial (bug), but the root cause discovery should be noted

**The correct pattern:**
> "I recommend [X] because [reason]. Tradeoff vs [Y]: [tradeoff]. Proceed?"

Wait for confirmation before implementing. If the user is in flow ("yes proceed"), take the
last confirmed direction and apply it. If genuinely unsure, surface the question.

**Decisions that MUST be surfaced first (non-exhaustive):**
- Which NVIDIA model to use for any modality (ASR, LLM, embedding, VLM)
- Data generation schema, categories, weights, counts, formats
- Architectural patterns (e.g. Pattern A vs B, stub vs implement, defer vs now)
- Collection names, field names, API design choices

Trivial bug fixes and obvious correctness fixes can be done silently — but note them in the
commit message.

### Record all learnings and decisions to `.claude/` — always

After every phase and every non-trivial decision, update:
- `.claude/context/implementation-learnings.md` — what was learned, what failed, gotchas
- `.claude/context/phase-status.md` — current status, what's ✅ and what's pending
- `.claude/CLAUDE.md` — if a new operating rule emerges

Commit these with every phase commit. A future Claude instance must be able to resume
without losing context. This is the institutional memory of the project.

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

## Phase 3 Learnings (Data Simulation — sim-case-text)

**Completed on this instance.** See `deploy/PHASE3_DATA_SIM.md` for the full proof table.

### What Phase 3 is (clarified mid-session)

Phase 3 = **Data Factory**, not ingestion. The job is to produce raw evidence artifacts that
simulate what the police force hands to Sherlock. Ingestion to RAG BP is the *outcome* of
Phase 3 (so Sherlock can be verified), not the goal.

Separation matters: sim-case-audio, sim-case-images, sim-case-video are OPTIONAL (post-Phase 9).
Only sim-case-text is required for Phase 3.

### data-designer Installation (no sudo, no venv)

System may not have pip. Bootstrap:
```bash
curl -fsSL https://bootstrap.pypa.io/get-pip.py | python3 - --user
python3 -m pip install --user data-designer
export PATH="$HOME/.local/bin:$PATH"   # add to shell profile
```
`python3-venv` was not available and `sudo apt` was denied — `--user` install is the fallback.

### data-designer CLI Usage

Always export NVIDIA_API_KEY before any command. Check presence only — never print value:
```bash
export NVIDIA_API_KEY=$(grep '^NVIDIA_API_KEY=' .env | cut -d= -f2- | sed 's/[[:space:]]*#.*//' | tr -d '[:space:]')
export PATH="$HOME/.local/bin:$PATH"
```

Workflow:
```bash
data-designer validate data/sim/forensic_cases.py        # schema check
data-designer preview  data/sim/forensic_cases.py --save-results  # 10-row sanity check
data-designer create   data/sim/forensic_cases.py \
  --num-records 20 --dataset-name forensic_cases_sg \
  --artifact-path data/sim/artifacts
```

Parquet lands at: `data/sim/artifacts/forensic_cases_sg/parquet-files/batch_00000.parquet`
(not `forensic_cases_sg/forensic_cases_sg.parquet` — verify path before writing downstream scripts)

### DataDesignerConfigBuilder API (v0.7.0)

```python
import data_designer.config as dd
config_builder = dd.DataDesignerConfigBuilder()   # no arguments — uses global model aliases
```

**WRONG:** `dd.DataDesignerConfigBuilder(model_aliases=["nvidia-text"])` → raises
`unexpected keyword argument 'model_aliases'`. Model aliases come from globally configured
provider (set via `data-designer config`), not from the builder constructor.

Available model aliases (check with `data-designer agent state model-aliases`):
- `nvidia-text` → nemotron-3-nano-30b-a3b (fast, cheap, good for structured gen)
- `nvidia-reasoning` → nemotron-super-49b-v1 (for complex reasoning)
- `nvidia-vision` → llama-3.2-90b-vision-instruct (multimodal)
- `nvidia-embedding` → llama-3.2-nv-embedqa-1b-v2

### Column Config Types

```python
dd.SamplerColumnConfig(name, sampler_type, params, convert_to=None)
dd.LLMTextColumnConfig(name, model_alias, system_prompt, prompt)
dd.LLMStructuredColumnConfig(name, model_alias, output_format, system_prompt, prompt)
dd.ExpressionColumnConfig(name, expr)   # Jinja2 expression
```

Sampler types and params:
```python
dd.UUIDSamplerParams(prefix="SC-2024-", short_form=True, uppercase=True)
dd.DatetimeSamplerParams(start="2022-01-01", end="2024-12-31", unit="D")
dd.CategorySamplerParams(values=[...], weights=[...])  # weights optional
dd.UniformSamplerParams(low=18, high=65)               # convert_to="int"
dd.PersonFromFakerSamplerParams(locale="en_US")        # en_SG needs 0.30GB download
```

### CRITICAL: person_from_faker produces first_name / last_name (NOT .name)

`PersonFromFakerSamplerParams` creates an internal `_<column_name>` sampler column.
Jinja template reference:
```
CORRECT:   {{ _suspect.first_name }} {{ _suspect.last_name }}
WRONG:     {{ _suspect.name }}    ← always empty / error
```

`en_SG` locale requires running `data-designer install persona-datasets --locale en_SG`
(0.30GB download, not installed by default). Workaround: use explicit category sampler
with Singapore-context names instead of persona faker — gives better control and no download.

### CRITICAL: Pydantic field named `items` breaks Jinja2

In `LLMStructuredColumnConfig`, the generated object is accessed in Jinja templates.
If your Pydantic model has a field named `items`, Jinja2 resolves `{{ evidence.items }}`
as the Python dict `.items()` built-in method — **not** your field. Error:
```
'builtin_function_or_method' object is not iterable
```

**Fix:** name the field `records` (or anything that isn't a dict/list method):
```python
class EvidenceList(BaseModel):
    records: list[ForensicEvidence]   # NOT 'items'
```

Then reference as `{{ evidence.records }}` in all Jinja templates.

### Forensic Case Config — Singapore Context

The config at `data/sim/forensic_cases.py` generates 16 columns of Singapore-specific
forensic data. Key design choices recorded here so they can be reproduced or extended:

**Identifiers:**
- `case_id`: UUID with `SC-2024-` prefix, short_form=True, uppercase=True → `SC-2024-A1B2C3D4`
- `incident_date`: datetime 2022-01-01 → 2024-12-31, unit=D, convert_to="%Y-%m-%d"

**Case classification (category samplers):**
```python
case_type = ["drug_trafficking","cybercrime","financial_fraud","robbery",
             "homicide","assault","human_trafficking","money_laundering"]
severity  = ["low","medium","high","critical"], weights=[1,3,3,1]
district  = ["Bedok","Tampines","Jurong East","Woodlands","Ang Mo Kio",
             "Clementi","Bukit Timah","Geylang","Toa Payoh","Yishun",
             "Hougang","Punggol"]
case_status = ["open","under_investigation","pending_trial","closed"], weights=[2,4,2,2]
```

**Suspect nationality (weighted Singapore demographic mix):**
```python
values  = ["Singaporean","Malaysian","Chinese national","Indian national",
           "Vietnamese national","Filipino","Indonesian","British national"]
weights = [4, 3, 2, 2, 1, 1, 1, 1]
```

**Suspect names (explicit list, not PersonFromFaker):**
Covers SG Chinese (with HDB-era naming), SG Malay (bin/binte suffixes), SG Indian
(s/o and d/o suffixes), Malaysian, Chinese national, Vietnamese, Filipino, Indonesian,
British. 30 names total. See `data/sim/forensic_cases.py` for the full list.

**LLM columns:**
- `incident_summary`: system_prompt = "SPF report writer, formal British English,
  Singapore-specific locations (MRT, HDB, coffeeshop)"; prompt references case_type,
  district, suspect_name, suspect_nationality, suspect_age, severity
- `evidence`: LLMStructured → `EvidenceList.records` (2-4 ForensicEvidence items);
  ForensicEvidence fields: evidence_id (EVD-YYYY-NNNN), evidence_type, description,
  collection_location, chain_of_custody
- `lab_report`: iterates `{% for item in evidence.records %}` — references EVD IDs
- `witness_statement`: system_prompt includes "Singlish: lah, leh, lor, aiyah, can, confirm"
- `whatsapp_chat`: system_prompt = "WhatsApp transcript from suspect's phone; format
  [HH:MM] Name: message; Singapore English with Singlish, Mandarin/Malay romanised;
  incriminating but written naturally (participants don't know they're watched); 8-15 messages"
- `investigating_officer_notes`: system_prompt references `{{ assigned_officer }}`;
  prompt includes ICA/MOM checks for foreign suspects

### Case Folder Structure (parquet_to_cases.py)

One folder per case under `data/cases/<case_id>/`:
```
case_report.txt        — SPF official incident report (formal header + all sections)
witness_statement.txt  — raw testimony with Singlish
lab_report.txt         — forensic lab analysis
whatsapp_chat.txt      — extracted chat with device/case header
metadata.json          — structured case metadata for tagging
audio/.gitkeep         — future sim-case-audio
images/.gitkeep        — future sim-case-images
video/.gitkeep         — future sim-case-video
```

**Dual purpose:** (1) developer test data — simulate police handing over evidence to Sherlock;
(2) system QA data — users/testers run Sherlock against known cases and verify answers.

### RAG Blueprint Ingestor — Filename Collision Fix

The ingestor (`POST /v1/documents`) uses the **uploaded filename** as the document key
within a collection. All 20 cases have files named `case_report.txt`, `lab_report.txt`, etc.
→ "Document case_report.txt already exists" error on case #2+.

**Fix:** upload a temp copy named `{case_id}_{filename}`:
```bash
cp "$txt_file" "/tmp/${case_id}_${filename}"
curl -X POST http://localhost:8082/v1/documents \
  -F "file=@/tmp/${case_id}_${filename};type=text/plain" \
  -F "data={\"collection_name\":\"multimodal_data\",\"blocking\":true}"
rm -f "/tmp/${case_id}_${filename}"
```

**Wrong endpoint** (tried first): `/v1/ingest/files` → 404. Correct: `POST /v1/documents`.
Use `blocking=true` in the data field for synchronous completion (no polling needed).

### End-to-end Verification

After ingestion:
```bash
curl -sf -X POST http://localhost:8100/generate \
  -H "Content-Type: application/json" \
  -d '{"query":"What evidence was collected in the human trafficking case in Geylang?"}'
```
Expected: Sherlock returns case ID, suspect name, evidence list, WhatsApp chat quotes,
with source citations to `SC-2024-XXXXXXXX_case_report.txt` etc.

Actual result on this instance: **SC-2024-873A3944**, Nguyen Van Thanh, 3 evidence items
(handcuffs, encrypted phone, travel-agency contract), WhatsApp chat quoted verbatim.
80/80 files ingested, 0 failed, 20 case folders.

### Git Strategy for data/ folder

The `data/` folder is checked into git with this strategy:
- `data/sim/*.py`, `data/sim/*.sh` — always check in (source code)
- `data/sim/artifacts/` — excluded via `.gitignore` (large parquet binary, can be regenerated)
- `data/cases/<case_id>/*.txt` — check in (small text, other tools add audio/images/video)
- `data/cases/<case_id>/metadata.json` — check in
- `data/cases/<case_id>/{audio,images,video}/.gitkeep` — check in (placeholder dirs)
- `data/cases/<case_id>/{audio,images,video}/` (actual media) — excluded (large binary)

This allows other tools (or the user) to drop generated media into the placeholder directories
and have them available without polluting git with large binaries.

## Phase 4 Learnings (Audio Pipeline — Parakeet ASR)

**Completed on this instance.** See `deploy/PHASE4_AUDIO.md` for the full proof table.

### Model choice for Singapore forensic audio

**Parakeet RNNT Multilingual** (`ai-parakeet-1_1b-rnnt-multilingual-asr`) over Parakeet CTC English.
Forensic cases involve Chinese, Malay, Indian Singaporeans PLUS Vietnamese, Filipino, Indonesian,
Malaysian foreign suspects. English-only ASR misses non-English speech. Multilingual is mandatory.
Streaming + offline — handles both real-time and batch use cases.

### NVCF Function-ID: always resolve at runtime

Function-IDs rotate per release. Never hardcode. Resolve fresh every run:
```python
def discover_function_id(api_key, model_name):
    url = "https://api.nvcf.nvidia.com/v2/nvcf/functions?visibility=public,authorized"
    # filter by name and status == "ACTIVE"
    # return fn["id"]
```
The FID is effectively a rotating credential — do not print or log it.

### Parakeet gRPC (cloud) — audio must be mono WAV 16-bit PCM

Riva ASR on-the-wire formats: **WAV (mono, 16-bit PCM)** or **Opus (mono)**.
Other formats (MP3, M4A, AAC, FLAC) must be transcoded with ffmpeg first.
Stereo → silent fail or hang. Always downmix to mono before sending.

Normalization chain:
1. ffmpeg preferred: `ffmpeg -y -i input -ac 1 -ar 16000 -acodec pcm_s16le output.wav`
2. Python fallback (WAV only): `soundfile.read()` + `scipy.signal.resample_poly()` + `wave.write()`

### nvidia-riva-client installation (no sudo, no venv)

```bash
python3 -m pip install --user nvidia-riva-client soundfile scipy numpy
export PATH="$HOME/.local/bin:$PATH"
```

### Cloud gRPC call pattern (inline, no python-clients clone needed)

```python
import riva.client
md = [["function-id", fid], ["authorization", f"Bearer {api_key}"]]
auth = riva.client.Auth(uri="grpc.nvcf.nvidia.com:443", use_ssl=True, metadata_args=md)
asr = riva.client.ASRService(auth)
cfg = riva.client.RecognitionConfig(
    language_code="en-US", sample_rate_hertz=16000, audio_channel_count=1,
    encoding=riva.client.AudioEncoding.LINEAR_PCM, enable_automatic_punctuation=True)
scfg = riva.client.StreamingRecognitionConfig(config=cfg, interim_results=False)
chunks = (pcm[i:i+32000] for i in range(0, len(pcm), 32000))
for resp in asr.streaming_response_generator(audio_chunks=chunks, streaming_config=scfg):
    for r in resp.results:
        if r.is_final and r.alternatives:
            print(r.alternatives[0].transcript)
```

### RAG Blueprint API changed — ingest_cases.sh updated

The ingestor API field name and path changed between when Phase 3 was deployed and Phase 4:

| | Old (Phase 3) | Correct |
|---|---|---|
| Endpoint | `POST /v1/documents` | `POST /documents` |
| File field | `-F "file=@..."` | `-F "documents=@..."` |
| Success check | `status == "success"` | `"successfully completed"` in response |

Both `data/sim/ingest_cases.sh` and `data/audio/process_audio.py` use the correct API.

**Also corrected in deploy/phase3_data_sim.sh** — check before re-running.

### MERaLiON is NOT a Riva NIM

MERaLiON-3-Whisper-SEA-LION (NTU/A*STAR) is a HuggingFace model, not on build.nvidia.com.
Requires GPU + `pip install transformers torch` + HF_TOKEN. Cannot run cloud.
Deferred to Phase 7 as a forensic processing tool. Stub in `process_audio.py`.
Model: `MERaLiON/MERaLiON-AudioLLM-Whisper-SEA-LION`

---

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

---

## Phase 5 Learnings (VSS LVS Profile — Video Search & Summarization)

### VSS uses network_mode=host — causes port conflicts with other stacks

Almost all VSS services use `network_mode: host`. They bind directly to host ports, not
Docker bridge ports. Consequence: any other container exposing the same port via host-port
mapping WILL conflict.

Confirmed conflicts on this host before VSS deploy:
- **Port 9200** (elasticsearch): was owned by RAG Blueprint's elasticsearch container
- **Port 6379** (redis): was owned by NV-Ingest/RAG's redis container

Fix: stop the conflicting containers before `docker compose up -d`, let VSS start its own.

### Shared infrastructure: VSS owns Elasticsearch and Redis (production rule)

DESIGN.md intent: one shared Elasticsearch and Redis for all stacks (RAG-BP + VSS).
**VSS is designated the owner** because:
- VSS's elasticsearch runs with logstash pipelines and specific indices (more opinionated)
- RAG Blueprint can connect to any ES via env var
- VSS must start first; other stacks connect to its ES/Redis

**To reconnect RAG Blueprint after VSS deploy:**
- Change `APP_VECTORSTORE_URL=http://elasticsearch:9200` → `http://10.148.0.33:9200`
- Change `REDIS_HOST=redis` → `10.148.0.33` (Redis port stays 6379)
- Re-ingest RAG documents (fresh ES index, old volume discarded)

**AI-Q (Phase 1):** does NOT use Redis directly — uses Postgres for job storage. No reconnection needed.

### Production data ingestion order: Phases 1–9 deploy, then Phase 10 = user ingest

In production, no re-ingestion is needed after a stack swap. The deployment sequence
(Phases 1–9) installs the system; users only ingest real case data at Phase 10 (operational).
Re-ingestion only arises in dev when sample data was loaded into a now-discarded ES volume.

### Brev-specific prerequisites (LVS profile)

From warehouse.md + brev.md — most are no-ops for remote-all on Brev:

| Prerequisite | Required? | Status |
|---|---|---|
| `sudo ufw allow 172.17.0.0/16` | No — UFW is ENABLED=no on this host | Skip |
| CDI spec regeneration | No — remote-all, no local GPU containers | Skip |
| `/etc/hosts` Brev domain entries | Yes — for vss-rtvi-vlm to resolve Brev URLs | Inject post-deploy |
| socat TLS proxy | Yes — for Brev HTTPS reverse proxy | Post-deploy step |

**After VSS is up**, inject /etc/hosts into the vss-rtvi-vlm container:
```bash
HOST_IP=$(hostname -I | awk '{print $1}')
BREV_ENV_ID=$(awk -F= '/^BREV_ENV_ID=/{gsub(/"/, "", $2); print $2; exit}' /etc/environment)
docker exec vss-rtvi-vlm sh -c "echo '${HOST_IP} 7777-${BREV_ENV_ID}.brevlab.com' >> /etc/hosts"
```

### COMPOSE_PROFILES for LVS remote-all

The compose profile for LVS with both LLM and VLM remote:
```
COMPOSE_PROFILES=bp_developer_lvs_2d,llm_remote_none
```
Note: no `vlm_*` segment — VLM runs inside rtvi-vlm container, not a standalone NIM profile.

### VLM_NAME for LVS remote mode

For remote mode, `VLM_NAME` must match what the remote endpoint's `/v1/models` advertises:
- Remote (integrate.api.nvidia.com): `VLM_NAME=nvidia/cosmos-reason2-8b`
- Integrated/local (NIM inside rtvi-vlm): `VLM_NAME=nim_nvidia_cosmos-reason2-8b_hf-1208`
  (rule: `ngc:nim/<org>/<model>:<tag>` → `nim_<org>_<model>_<tag>`)
Mismatch → `400 BadParameters: No such model`

### RT-VLM requires RTVI_VLM_MODEL_PATH=none for remote mode

If `RTVI_VLM_MODEL_PATH` is not set to `none`, the RT-VLM container hangs waiting for
a local model to load. Always set it explicitly:
```
RTVI_VLM_MODEL_PATH=none
RTVI_VLM_MODEL_TO_USE=openai-compat
RTVI_VLM_ENDPOINT=https://integrate.api.nvidia.com/v1   # WITH /v1 (RT-VLM quirk)
```

### LLM_BASE_URL and VLM_BASE_URL must NOT have trailing /v1

```
LLM_BASE_URL=https://integrate.api.nvidia.com   # correct
VLM_BASE_URL=https://integrate.api.nvidia.com   # correct
RTVI_VLM_ENDPOINT=https://integrate.api.nvidia.com/v1  # /v1 here (RT-VLM only)
```

### Data directory permissions — FORBIDDEN chown

`chown -R ubuntu:ubuntu $VSS_DATA_DIR` silently breaks the video pipeline even though
containers appear Up. Only these are allowed:
```bash
chmod -R 777 $VSS_DATA_DIR/data_log
chmod -R 777 $VSS_DATA_DIR/agent_eval
```

### GPU instance decision: RTX PRO 6000 Blackwell (96 GB) for dev/staging; GB10 for production

Production end-state: **GB10 (DGX Spark, 128 GB unified memory)**
Dev/staging target: **RTX PRO 6000 Blackwell (96 GB GDDR7)**

Why not H100: too expensive for this team. RTX PRO 6000 has 96 GB — more than sufficient.

VRAM budget for full Phase 9 self-hosted stack:
- rtvi-vlm NVDEC (hardware decoder): ~1 GB
- MERaLiON-3-AudioLLM-Whisper-SEA-LION: ~12 GB
- LLM NIM (Nemotron Nano 9B, FP8): ~9 GB
- VLM NIM (Cosmos Reason 2 8B, FP8): ~10 GB
- Parakeet ASR NIM: ~4 GB
- Total: ~36 GB — fits in 96 GB with 60 GB headroom

VSS skill docs explicitly support HARDWARE_PROFILE=RTXPRO6000BW.
Anything that fits in 96 GB fits in GB10 (128 GB), so dev staging = production tier.

Model hosting policy (developer-confirmed):
- **Prefer NVIDIA NIMs when available** — use hosted endpoints (integrate.api.nvidia.com)
- **Self-host only when no NIM exists** — currently: MERaLiON (HuggingFace only, no NIM)
- **rtvi-vlm NVDEC**: always needs physical GPU hardware (no remote option)

Two-instance topology for dev (current Brev + GPU Brev):
- CPU instance: AI-Q, RAG, elasticsearch, redis, kafka, vss-agent, lvs-server
- GPU instance (RTX PRO 6000): rtvi-vlm, MERaLiON, Phase 9 NIMs
- Key config: `RTVI_VLM_URL=http://<GPU_IP>:8018` in generated.env

### resolved.yml generation — stdout only, no 2>&1

```bash
docker compose --env-file "$ENV_GEN" config > resolved.yml   # CORRECT
docker compose --env-file "$ENV_GEN" config > resolved.yml 2>&1  # WRONG — stderr corrupts YAML
```
After generation, normalize with `uv run normalize_resolved_yml.py resolved.yml` (strips 49
dangling optional depends_on entries for LVS profile).

---

## Phase 8 Learnings (UI Workbench — Streaming, Markdown, Greeting, Docs)

### CRITICAL: Read aiq-* skills BEFORE any AI-Q config change or debugging

During Phase 7/8 AI-Q debugging, the `~/skills/skills/aiq-*/` skill files were NEVER consulted.
Fixes for `enable_plan_approval`, `use_async_deep_research`, workflow type selection, and timeout
tuning were found through SSE stream observation and trial-and-error.

**Before touching ANY of the following, read all files in `~/skills/skills/aiq-*/`:**
- `workflow._type` (e.g. `shallow_research_workflow` vs `chat_deepresearcher_agent`)
- `enable_plan_approval`, `use_async_deep_research`, `max_loops`, `max_tool_iterations`
- Any timeout or retry parameters on LLMs or agents
- `intermediate_data:` SSE event format and field names
- `enable_thinking: true` behavior and latency implications

Rule 1 in CLAUDE.md ("Skills first, always") applies here just as much as for deploy phases.

### AI-Q `enable_plan_approval: true` kills streaming

When `clarifier_agent.enable_plan_approval: true`, AI-Q's clarifier generates a plan JSON,
then **closes the SSE stream with an empty `data: {"choices":[{"delta":{"content":""}}]}`**,
waiting for the human to approve via the HITL API. The browser receives a complete (empty)
response — the chat bubble shows nothing.

Fix: `enable_plan_approval: false`. The Sherlock workbench handles HITL via `detectPlan()` +
Approve/Reject buttons in the UI — AI-Q's built-in HITL is not needed.

### `use_async_deep_research: true` returns "Deep research job submitted. Job ID: ..."

The deep_research_agent submits an async job and returns a job reference instead of streaming
content. The workbench streams from `/v1/chat/stream` synchronously — it has no job polling.

Fix: `use_async_deep_research: false`.

### `shallow_research_workflow` is the right workflow type for Sherlock

`chat_deepresearcher_agent` workflow:
- Runs intent_classifier → may route to deep_research_agent
- deep_research_agent uses 120B model by default, runs 10+ LLM calls, calls filesystem tools
  (write_todos, task, glob, ls, grep) — irrelevant for forensic queries
- Takes 3+ minutes per query

`shallow_research_workflow`:
- Bypasses intent_classifier entirely
- Routes all queries directly to shallow_research_agent
- shallow_research_agent calls graph + RAG tools, synthesizes cited answer
- 25–60s per query

For the Sherlock forensic investigator pattern (one-shot question → cited answer), always
use `shallow_research_workflow`.

### `enable_thinking: true` stacks latency across LLM calls

Nemotron-3-nano-30b-a3b with `enable_thinking: true` generates chain-of-thought tokens
before each response. This is fine for a single LLM call, but when the deep_research_agent
chains 10+ LLM calls (planner + orchestrator + each researcher), total latency compounds to
3+ minutes.

Fix: Create a separate `nemotron_fast_llm` config (no `enable_thinking`, lower `max_tokens`)
for orchestrator/planner roles. Keep `enable_thinking: true` on the researcher LLM.

### Proxy timeout must be ≥ 600s for deep research queries

The FastAPI SSE proxy (`ui/server.py`) had a 120s timeout. AI-Q deep research queries exceed
this. The proxy returned `ReadTimeout` as a JSON error in the SSE stream — but the original
client code silently ignored it, producing an empty bubble.

Fix: `httpx.AsyncClient(timeout=600.0)`. Also: always surface `parsed?.error` from SSE
`data:` events to the user (throw, don't swallow).

### Greeting must NOT call AI-Q

`shallow_research_workflow` runs research tools on EVERY message, including greetings like
"Hello". This either times out or returns empty content (no case context for tools to work on).

Fix: Generate the greeting instantly in the frontend from `caseMeta`:
```javascript
const greeting = `Hello${officer ? `, **${officer}**` : ''}. I'm ready to assist with case **${caseId}**. What would you like to investigate?`
```

### Greeting reactive statement — use greetedCase, not a boolean flag

Using `let initialized = false` as a guard means the greeting fires only on first mount.
On case switch, the component remounts with new props but `initialized` stays `true` if
held in a parent scope, or resets to `false` and re-fires even with existing chat history.

Fix: `let greetedCase = null` tracked per case, checked against `$chatHistory.length === 0`:
```javascript
$: if (caseId && caseId !== greetedCase && $chatHistory.length === 0) {
    greetedCase = caseId
    // fire greeting
}
```

### marked v18 GFM — remove `white-space: pre-wrap` from .msg-body

`marked.parse()` returns HTML. If the container has `white-space: pre-wrap`, the rendered
HTML is treated as preformatted text — tables, bullets, and headings appear as raw HTML tags.

Fix: Remove `white-space: pre-wrap` from `.msg-body`. Use `word-break: break-word` instead.

### SSE intermediate_data: events — step label mapping

AI-Q emits `intermediate_data:` events before the final `data:` event. Each has a `name`
field that identifies the current step. Map these to human-readable labels:

```javascript
function stepLabel(name) {
    if (!name) return ''
    if (name.includes('intent_classifier'))    return 'Classifying intent…'
    if (name.includes('shallow_researcher'))   return 'Searching knowledge base…'
    if (name.includes('report_writer'))        return 'Writing report…'
    if (name.includes('workflow'))             return 'Running investigation pipeline…'
    if (/nvidia\//i.test(name))                return 'Generating response…'
    return ''
}
```

Observed name patterns: `"Function Start: intent_classifier"`, `"Function Complete: mcp_sherlock_tools__graph_query_tool"`, `"nvidia/nemotron-3-nano-30b-a3b"`.

### streamingActive store — guard case switches mid-stream

If the user switches cases while AI-Q is streaming, the SSE reader continues in the
background and its `finally` block tries to update Svelte stores after the component
has already switched to a new case. Result: residual content appears in the new case.

Fix: `export const streamingActive = writable(false)` in stores.js; set true when
streaming starts, false in `finally`. In App.svelte, check `get(streamingActive)` before
allowing `selectedCase.set(meta)`, and show a confirmation dialog if active.
