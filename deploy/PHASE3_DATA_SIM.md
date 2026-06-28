# Phase 3 — Data Simulation · Deployment Proof

**NVIDIA skills followed:**
- `data-designer` v0.7.0 — SKILL.md + ALL references/ + workflows/ read in full

**References used (in order):**
`SKILL.md` · `workflows/autopilot.md` · `workflows/interactive.md`
· `references/seed-datasets.md` · `references/person-sampling.md` · `references/preview-review.md`
+ `data-designer agent context` (schema inspection before writing any config)

**Goal (DESIGN.md Phase 3):** Generate synthetic forensic case data simulating evidence
handed to Sherlock by Singapore Police Force. Data serves dual purpose:
1. Developer test data — ingest into RAG BP and verify Sherlock end-to-end
2. Future system QA — users can run Sherlock against known cases and verify answers

---

## What Phase 3 is (and isn't)

**Phase 3 = Data Factory.** Generates raw synthetic evidence artifacts.
**Not ingestion** — ingestion to RAG BP is the *outcome* of Phase 3, not the goal.

Separation of concerns:
```
Phase 3: sim-case-text   → data/cases/<case_id>/*.txt  (this phase)
Phase 3: sim-case-audio  → data/cases/<case_id>/audio/ (optional, post-Phase 9)
Phase 3: sim-case-images → data/cases/<case_id>/images/ (optional, post-Phase 9)
Phase 3: sim-case-video  → data/cases/<case_id>/video/  (optional, post-Phase 9)
```

---

## Steps Executed — Skill Reference → Command → Actual Result

| # | Skill ref | Action | Actual result |
|---|---|---|---|
| 1 | `workflows/autopilot.md` step 1 | Resolve CLI: `command -v data-designer` | CLI_NOT_FOUND → installed via `get-pip.py` + `pip install data-designer` → v0.7.0 ✓ |
| 2 | `workflows/autopilot.md` step 2 | `data-designer agent context` | No model aliases initially (NVIDIA_API_KEY not exported). Re-ran with key set → `nvidia-text`, `nvidia-reasoning`, `nvidia-vision`, `nvidia-embedding` all usable ✓ |
| 3 | `workflows/autopilot.md` step 2 | Read `base.py`, `column_configs.py`, `sampler_params.py` from config root | Confirmed: `person_from_faker` produces `first_name`/`last_name` (NOT `.name`). `EvidenceList.items` collides with dict `.items()` method in Jinja2 — renamed field to `.records` ✓ |
| 4 | `workflows/autopilot.md` step 3–4 | Infer + Plan forensic case schema | 16 columns: UUID case_id, datetime, 4 category samplers, 2 name samplers (SG-context), 5 LLM text, 1 LLM structured (evidence list), 1 expression (officer) ✓ |
| 5 | `workflows/autopilot.md` step 5 | Write `data/sim/forensic_cases.py` | Script with `load_config_builder()` created ✓ |
| 6 | `workflows/autopilot.md` step 6 | `data-designer validate forensic_cases.py` | ✅ Validation passed ✓ |
| 7 | `workflows/autopilot.md` step 7 | `data-designer preview forensic_cases.py --save-results` | 10/10 records, 0 failed. Results: `/home/ubuntu/skills/artifacts/preview_results_20260628_091007` ✓ |
| 8 | `references/preview-review.md` | Review sample record quality | Excellent: Singapore Police Force formal English, SPF district references, SGD amounts, Singlish in witness statements, incriminating WhatsApp chats with local context (HDB blocks, hawker centres, MRT) ✓ |
| 9 | `workflows/autopilot.md` step 8 | `data-designer create --num-records 20 --dataset-name forensic_cases_sg` | 120/120 tasks ok, 0 failed. 20 cases × 6 LLM columns. Artifact: `data/sim/artifacts/forensic_cases_sg/` ✓ |
| 10 | `parquet_to_cases.py` | Explode parquet into per-case folders | 20 case folders created under `data/cases/<case_id>/` each with `case_report.txt`, `witness_statement.txt`, `lab_report.txt`, `whatsapp_chat.txt`, `metadata.json`, + empty `audio/`, `images/`, `video/` dirs ✓ |
| 11 | RAG BP `POST /v1/documents` | Ingest 80 files (20 cases × 4 txt) with `{case_id}_{filename}` unique names | 80/80 ingested, 0 failed. Collection: `multimodal_data` ✓ |
| 12 | AI-Q `/generate` end-to-end | Query: "What evidence in the human trafficking case in Geylang?" | Sherlock returned **SC-2024-873A3944**, suspect Nguyen Van Thanh, 3 evidence items by type, verbatim WhatsApp chat quotes. References: ingested files ✓ |

**Gate: PASSED** — Sherlock produces cited answers from synthetic forensic case data.

---

## Dataset Schema

| Column | Type | Description |
|---|---|---|
| `case_id` | UUID (SC-2024-XXXXXXXX) | Unique case reference |
| `incident_date` | datetime (2022–2024) | Date of incident |
| `case_type` | category | drug_trafficking, cybercrime, financial_fraud, robbery, homicide, assault, human_trafficking, money_laundering |
| `severity` | category (weighted) | low / medium / high / critical |
| `district` | category | 12 Singapore districts (Bedok, Tampines, Jurong East, etc.) |
| `case_status` | category (weighted) | open / under_investigation / pending_trial / closed |
| `suspect_nationality` | category (weighted) | Singaporean (4×), Malaysian (3×), Chinese national (2×), others |
| `suspect_name` | category | Singapore-context names: Chinese, Malay, Indian, foreign |
| `suspect_age` | uniform int (18–65) | Suspect age |
| `assigned_officer` | category | Singapore Police Force officer names with rank |
| `incident_summary` | LLM text | 3–5 sentence formal SPF incident summary with SG-specific locations |
| `evidence` | LLM structured | `EvidenceList.records`: 2–4 `ForensicEvidence` items (id, type, description, location, chain of custody) |
| `lab_report` | LLM text | Forensic laboratory analysis report citing evidence IDs |
| `witness_statement` | LLM text | First-person witness statement with natural Singlish |
| `whatsapp_chat` | LLM text | Extracted WhatsApp chat with incriminating Singlish content |
| `investigating_officer_notes` | LLM text | Internal notes with ICA/MOM checks for foreign suspects |

**Model used:** `nvidia/nemotron-3-nano-30b-a3b` via NVIDIA API Catalog (cloud-hosted, no GPU)

---

## Case Folder Structure

```
data/cases/
└── SC-2024-<XXXXXXXX>/
    ├── metadata.json           ← structured metadata (case_id, type, suspect, evidence_ids)
    ├── case_report.txt         ← official SPF incident report + officer notes
    ├── witness_statement.txt   ← raw witness testimony
    ├── lab_report.txt          ← forensic lab analysis
    ├── whatsapp_chat.txt       ← extracted device chat (raw artifact)
    ├── audio/                  ← future: sim-case-audio (Magpie TTS + MERaLiON)
    ├── images/                 ← future: sim-case-images (static fixtures)
    └── video/                  ← future: sim-case-video (static MP4 fixtures)
```

Each `data/cases/` folder simulates evidence handed to Sherlock by the police force.
It is also the canonical QA dataset for testing Sherlock's forensic reasoning.

---

## Ingest Gotcha — Filename Uniqueness

The RAG Blueprint ingestor (`POST /v1/documents`) uses the uploaded filename as the
document key within a collection. Since all cases have `case_report.txt`,
`lab_report.txt`, etc., they would collide.

**Fix:** Upload each file with a `{case_id}_{filename}` prefix via a temp copy.
`phase3_data_sim.sh` handles this automatically.

---

## Key Gotchas (data-designer)

### 1. NVIDIA_API_KEY must be exported before running data-designer
`data-designer agent context` reports "No usable model aliases" if the key is not
in the shell environment. Export before every command:
```bash
export NVIDIA_API_KEY=$(grep '^NVIDIA_API_KEY=' .env | cut -d= -f2- | sed 's/[[:space:]]*#.*//' | tr -d '[:space:]')
```

### 2. person_from_faker fields: first_name / last_name (not .name)
`PersonFromFakerSamplerParams` produces `first_name` and `last_name` separately.
`{{ person.name }}` returns empty — use `{{ person.first_name }} {{ person.last_name }}`.

### 3. Pydantic field named `items` collides with dict.items() in Jinja2
In `LLMStructuredColumnConfig`, if your Pydantic model has a field named `items`,
Jinja2 `{{ evidence.items }}` resolves to the dict method, not the field value.
**Fix:** rename the field (e.g. `records`) or use `{{ evidence['items'] }}`.

### 4. DataDesignerConfigBuilder takes model_configs, not model_aliases
Pass nothing (uses globally configured aliases) or a `list[ModelConfig]`.
`model_aliases=[...]` raises `unexpected keyword argument`.

### 5. en_SG persona locale requires 0.30GB download
`PersonSamplerParams(locale="en_SG")` requires `data-designer agent state persona-datasets`
to show `en_SG` as installed. Use `person_from_faker` as fallback, or install:
```bash
data-designer install persona-datasets --locale en_SG
```

---

## On-Prem Replay

```bash
# 1. Install data-designer (Python >= 3.10)
pip install data-designer

# 2. Configure NVIDIA provider (already set up by default with NVIDIA_API_KEY)
data-designer agent state model-aliases   # verify nvidia-text is usable

# 3. Generate cases
export NVIDIA_API_KEY=<your-key>
export PATH="$HOME/.local/bin:$PATH"
data-designer create data/sim/forensic_cases.py \
  --num-records 20 \
  --dataset-name forensic_cases_sg \
  --artifact-path data/sim/artifacts

# 4. Package into case folders
python3 data/sim/parquet_to_cases.py

# 5. Ingest into RAG BP
bash deploy/phase3_data_sim.sh

# 6. Verify with AI-Q
curl -X POST http://localhost:8100/generate \
  -H "Content-Type: application/json" \
  -d '{"query":"Summarise all drug trafficking cases and their evidence"}'
```
