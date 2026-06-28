# SME Summary: data-designer skill

Source: `~/skills/skills/data-designer/`
Always re-read the full skill files before implementing; this summary is a quick reference.

---

## What This Skill Does

Creates synthetic datasets or builds data generation pipelines using the NeMo Data Designer library.

**For this project (Phase 3):** Generate synthetic forensic case data for demo purposes.
Cases should include realistic (but fake) entities: persons, locations, chat excerpts,
evidence descriptions — enough to demo the full Sherlock pipeline.

---

## Workflow Modes

| Mode | When to use |
|---|---|
| Interactive (default) | Answer questions about dataset structure |
| Autopilot | Skill decides everything ("be opinionated", "you decide") |

For Phase 3: Use interactive mode to specify forensic case structure.

---

## What to Describe to the Skill

When invoking data-designer for forensic cases, describe:
- Entities needed: persons (suspects, witnesses), locations, organizations
- Evidence types: chat/WhatsApp messages, audio statement transcripts, image descriptions
- Relationships: who contacted whom, who was at which location, group membership
- Case metadata: case_id, severity, date range, jurisdiction
- Volume: number of cases, messages per case, persons per case

---

## Output Format

The skill produces a Python file with:
- `load_config_builder()` function returning `DataDesignerConfigBuilder`
- PEP 723 inline dependencies (self-contained script)
- Optional Pydantic models for structured output
- Optional custom generators for special logic

Run the generated script to produce the synthetic dataset.

---

## Key Rules (from skill)

- Keep all columns by default — only drop on explicit user request
- Do not use seed datasets unless user provides or requests one
- Column types require both `sampler_type` and `params`
- `SamplerColumnConfig` takes `params` (not `sampler_params`)
- Jinja2 templates use `{{ column_name }}` and nested `{{ column_name.field }}`

---

## Forensic Case Schema (Target for Phase 3)

Design the synthetic data to match what Sherlock will ingest:

```
Case:
  case_id: str (unique, e.g., "SHK-2025-001")
  case_name: str
  jurisdiction: str
  date_opened: date

Persons:
  person_id: str
  name: str
  role: "suspect" | "witness" | "victim"
  nationality: str
  phone_numbers: list[str]

Entities:
  type: "person" | "location" | "organization" | "phone"
  value: str
  case_id: str

Chat messages (WhatsApp-style):
  message_id: str
  case_id: str
  sender_id: str (→ person_id)
  recipient_id: str (→ person_id or group)
  timestamp: datetime
  content: str
  is_encrypted: bool

Audio statements:
  statement_id: str
  case_id: str
  speaker_id: str (→ person_id)
  duration_seconds: int
  transcript: str  ← this is what gets ingested into RAG
  paralinguistic_notes: str

Images:
  image_id: str
  case_id: str
  description: str  ← what gets captioned / ingested
  source: "phone" | "laptop" | "cctv"
```

---

## Integration with Phase 3

After generating synthetic data:
1. **Ingest transcripts + chat text** into RAG Blueprint corpus (via ingestor-server)
   - Collection name: `sherlock_{case_id}`
2. **Store entity/relationship data** as seed for Neo4j (Phase 6)
3. **Use audio transcripts** to test Phase 4 ingestion pipeline

---

## Common Issues

- `data-designer` CLI not found — not installed; use the Python library directly
- Network errors during preview — sandbox blocking outbound; use offline mode
- Large datasets slow to generate — start with small volume (5-10 cases) for Phase 3 demo
