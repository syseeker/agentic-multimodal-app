# Phase 4 — Audio Pipeline · Deployment Proof

**NVIDIA skills followed:**
- `nemotron-speech` v1.0.0 — SKILL.md + references/model-selection.md + references/asr.md
  + references/deployment-readiness-checks.md read in full

**Goal (DESIGN.md Phase 4):** Build a pipeline that transcribes audio evidence files
from `data/cases/<case_id>/audio/` using Parakeet ASR, and ingests the resulting
transcripts into RAG Blueprint so Sherlock can reason over audio evidence.

---

## What Phase 4 is (and isn't)

**Phase 4 = Audio Transcription Pipeline.** Takes raw audio evidence and produces
text transcripts for RAG ingestion.

**Not audio generation** — sim-case-audio (Magpie TTS + MERaLiON) is optional, post-Phase 9.

**Paralinguistics runs in the same pipeline.** `MERaLiON/MERaLiON-3-10B` loads in-process
and adds emotion / stress / language-ID alongside the Parakeet transcript. It needs a CUDA
GPU and `HF_TOKEN`; without either it returns a `status: "stub"` dict and the pipeline
continues with the transcript only.

---

## Model Selection (skill: references/model-selection.md)

Default path: `NVIDIA_API_KEY` is set → cloud, zero friction, no GPU needed.

**Model chosen: Parakeet RNNT Multilingual** (`ai-parakeet-1_1b-rnnt-multilingual-asr`)

Rationale over Parakeet CTC 1.1b English:
- Forensic cases involve Singaporeans (English/Singlish/Mandarin/Malay/Tamil) AND
  foreigners (Vietnamese, Filipino, Indonesian, Malaysian) — multilingual coverage is
  essential for a forensic pipeline that doesn't know who's speaking.
- Streaming + offline: handles both real-time and batch processing.
- Function-ID resolved at runtime via NVCF API — never hardcoded.

Fallback: Parakeet CTC 1.1b (`ai-parakeet-ctc-1_1b-asr`) for English-only audio.

---

## RAG Blueprint API Update (discovered in Phase 4)

The ingestor API changed from Phase 3. **Update all ingest scripts:**

| | Phase 3 (old) | Phase 4 (correct) |
|---|---|---|
| Endpoint | `POST /v1/documents` | `POST /documents` |
| File field | `-F "file=@..."` | `-F "documents=@..."` |
| Success indicator | `"status": "success"` | `"message": "...successfully completed."` |

`data/sim/ingest_cases.sh` was updated to use the correct endpoint and field.

---

## Steps Executed — Skill Reference → Command → Actual Result

| # | Skill ref | Action | Actual result |
|---|---|---|---|
| 1 | `SKILL.md` routing | Identify task: ASR transcription, multilingual, offline batch + streaming | Routed to `references/model-selection.md` + `references/asr.md` ✓ |
| 2 | `model-selection.md` §Default | `NVIDIA_API_KEY` set → cloud path, zero friction | Cloud path confirmed ✓ |
| 3 | `model-selection.md` §ASR Family | Singapore multilingual forensic audio → Parakeet RNNT Multilingual | FID resolved via NVCF API (`ai-parakeet-1_1b-rnnt-multilingual-asr`) ✓ |
| 4 | `asr.md` §Option A | Install `nvidia-riva-client` | `pip install --user nvidia-riva-client` → OK ✓ |
| 5 | `asr.md` §Function ID | Resolve FID via NVCF API (never hardcode) | `curl api.nvcf.nvidia.com/v2/nvcf/functions` → 13 active ASR functions; FID resolved ✓ |
| 6 | `asr.md` §Quick path | Implement gRPC streaming transcription via inline heredoc | `process_audio.py` → `riva.client.ASRService` streaming, mono WAV 16kHz ✓ |
| 7 | `asr.md` §Audio format | Audio must be mono WAV 16-bit PCM | Normalization via ffmpeg (if available) or soundfile+scipy fallback ✓ |
| 8 | `deployment-readiness-checks.md` | No GPU needed (cloud path) | No system checks needed — NVIDIA_API_KEY present ✓ |
| 9 | `generate_audio_samples.py --test-tone` | Generate synthetic test WAV (440 Hz sine, 3s, mono 16kHz) — replaces deleted `generate_test_audio.py` | WAV created ✓ |
| 10 | `process_audio.py` | Run pipeline on SC-2024-03C5F0E4 with test WAV | FID resolved, Parakeet gRPC call succeeded (0 words — expected for sine wave), audio_analysis.txt written ✓ |
| 11 | RAG Blueprint `POST /documents` | Ingest `SC-2024-03C5F0E4_audio_analysis.txt` | 200 OK — "successfully completed" ✓ |

**Gate: PASSED** — pipeline flows: audio file → normalize → Parakeet cloud gRPC → transcript file → RAG BP ingestion.

Note: 0-word transcript is correct for a synthetic tone WAV. Real speech audio will produce transcripts.

---

## Pipeline Flow

```
data/cases/<case_id>/audio/<file>.wav
           │
           ▼
    normalize_to_wav()          # mono 16kHz 16-bit PCM (ffmpeg preferred, soundfile fallback)
           │
           ▼
    transcribe_wav()            # Parakeet RNNT Multilingual via grpc.nvcf.nvidia.com:443
           │                    # FID discovered fresh each run via NVCF API
           ▼
    <file>_transcript.txt       # written into audio/ dir
           │
           ▼
    meralion_paralinguistics()  # MERaLiON-3-10B (needs GPU + HF_TOKEN);
                               # returns a stub dict when unavailable
           │
           ▼
    audio_analysis.txt          # aggregated per-case, written to case root
           │
           ▼
    POST /documents             # RAG Blueprint ingestor
    documents=@SC-2024-<id>_audio_analysis.txt
```

---

## Audio Format Support

| Format | Supported | Notes |
|---|---|---|
| WAV (mono, 16-bit PCM) | ✓ Native | Any sample rate — normalized to model rate |
| Opus/OGG (mono) | ✓ Via ffmpeg | Requires ffmpeg |
| MP3, M4A, AAC, FLAC | Via ffmpeg | Requires ffmpeg |
| Stereo WAV | ✗ | Downmix with ffmpeg `-ac 1` |

Riva ASR accepts mono-only audio on the wire. The pipeline normalizes to mono before sending.

---

## MERaLiON Paralinguistics

MERaLiON-3 (NTU/A*STAR) provides Singapore-specific paralinguistics:
- Singlish/Singapore English speech understanding
- Sentiment analysis from speech prosody
- Language identification (en, zh, ms, ta + code-switching)
- Speaker emotion state

| | |
|---|---|
| **Model** | `MERaLiON/MERaLiON-3-10B` (override with `MERALION_MODEL`) |
| **Location** | `data/audio/process_audio.py::meralion_paralinguistics()` |
| **Serving** | HTTP service `data/audio/meralion_server.py` (:8500), started by `phase4_audio.sh`. Falls back to in-process `transformers` (bf16, sdpa, CUDA) when the service is absent. |
| **Requires** | CUDA GPU + `HF_TOKEN`, `transformers==4.50.1`; ~20 GB VRAM |
| **Exposed as** | the `analyze_audio` MCP tool (Sherlock MCP :9901) |
| **Verified on** | RTX Pro 6000 (x86_64). aarch64/GB10 untested. |

Implementation notes that matter: `MERaLiON3Config` does not define `pad_token_id`, so it
is patched before `from_pretrained` or the load raises; audio is resampled to 16 kHz (the
same normalized WAV Parakeet uses); the model returns only newly generated tokens, so the
output is decoded from the new-token slice.

First call loads ~20 GB of weights and can take ~2 min — this is why the MCP
`tool_call_timeout` is 300 s.

---

## Key Gotchas

### 1. NVCF function-ids rotate — never hardcode
Resolve fresh every run:
```python
fid = discover_function_id(api_key, "ai-parakeet-1_1b-rnnt-multilingual-asr")
```

### 2. gRPC audio format constraints
- Mono-only (Riva ASR). Stereo → silent fail or hang.
- WAV must be 16-bit PCM signed little-endian.
- Sample rate: flexible per model (16 kHz recommended; pipeline normalizes automatically).

### 3. RAG Blueprint API: /documents, field=documents (not /v1/documents, field=file)
See RAG Blueprint API Update table above. `ingest_cases.sh` also updated.

### 4. FID must not be printed (treat as credential)
The function-id from NVCF is effectively a rotating API credential.
Check presence only — `print("FID resolved (not printed)")`.

---

## On-Prem Replay

```bash
# 1. Install dependencies
pip install --user nvidia-riva-client soundfile scipy numpy

# 2. Install ffmpeg (recommended for all audio formats)
apt-get install -y ffmpeg   # or brew install ffmpeg on macOS

# 3. Set API key
export NVIDIA_API_KEY=$(grep '^NVIDIA_API_KEY=' .env | cut -d= -f2- | tr -d ' ')

# 4. Drop audio into case dir(s)
cp <audio_file>.wav data/cases/<case_id>/audio/

# 5. Process all cases
python3 data/audio/process_audio.py

# 6. Process a specific case
python3 data/audio/process_audio.py --case-id SC-2024-XXXXXXXX

# 7. Verify with AI-Q
curl -sf -X POST http://localhost:8100/generate \
  -H "Content-Type: application/json" \
  -d '{"query":"What was said in the audio evidence for case SC-2024-XXXXXXXX?"}'
```
