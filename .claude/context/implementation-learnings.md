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
