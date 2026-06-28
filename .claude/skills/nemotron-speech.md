# SME Summary: nemotron-speech skill

Source: `~/skills/skills/nemotron-speech/`
Skill version: 1.0.0
Always re-read the full skill files before implementing; this summary is a quick reference.

Note: "Nemotron Speech" is the public-facing name. Internally it uses Riva NIM.
All commands, images, APIs, and docs still use "Riva".

---

## What This Skill Covers

Single entry point for all Nemotron Speech (Riva) NIM workflows:
- **ASR** — speech-to-text (Parakeet, Canary, Whisper)
- **TTS** — text-to-speech (Magpie)
- **NMT** — neural machine translation (Riva Translate)

**For this project:** ASR only (Parakeet primary, Canary optional).
Goal: audio statements → transcript for ingestion into RAG corpus.

---

## Task Routing

| Task | Reference file |
|---|---|
| Setup drivers, Docker, NGC | `references/setup.md` |
| GPU compatibility + readiness | `references/deployment-readiness-checks.md` |
| Model selection (Parakeet vs Canary) | `references/model-selection.md` |
| ASR deployment | `references/asr.md` |
| Custom NeMo ASR model | `references/asr-custom.md` |
| ASR pipeline config (VAD, diarization) | `references/pipelines.md` |
| TTS deployment | `references/tts.md` |
| NMT deployment | `references/nmt.md` |

**Read in this order for Phase 4:**
1. `references/deployment-readiness-checks.md`
2. `references/model-selection.md`
3. `references/asr.md`
4. `references/pipelines.md` (for VAD / diarization if needed)

---

## Deployment Options

| Option | Prerequisites | For this project? |
|---|---|---|
| Cloud-hosted (build.nvidia.com) | `NVIDIA_API_KEY`, internet | Yes (dev mode) |
| Self-hosted Docker | NGC key, NVIDIA AI Enterprise, drivers | Yes (prod/air-gapped) |

For dev: cloud-hosted is simplest. For production (air-gapped): self-hosted is required.

---

## Cloud-Hosted ASR (Dev Mode)

```bash
pip install -U nvidia-riva-client

# Python client example
import riva.client
auth = riva.client.Auth(uri='grpc.nvcf.nvidia.com:443',
                        use_ssl=True,
                        metadata_args=[["function-id", "<FUNCTION_ID>"],
                                       ["authorization", f"Bearer {NVIDIA_API_KEY}"]])
asr_client = riva.client.ASRService(auth)
```

Function IDs and model details: check `references/model-selection.md`.

---

## Self-Hosted ASR (Production / Air-Gapped)

```bash
# Prerequisites
# 1. NVIDIA AI Enterprise license
# 2. NGC API key
# 3. NVIDIA drivers + Docker + Container Toolkit

# Pull and run Riva NIM (Parakeet)
docker login nvcr.io -u '$oauthtoken' -p $NGC_API_KEY

docker run --rm -it --gpus all \
  -e NGC_CLI_API_KEY=$NGC_API_KEY \
  -v /opt/nim/.cache:/opt/nim/.cache \
  -p 50051:50051 -p 8000:8000 \
  nvcr.io/nim/nvidia/parakeet-ctc-1.1b-asr:latest
```

**IMPORTANT:** Host directory `/opt/nim/.cache` must be owned by container user (nvs:1000):
```bash
mkdir -p /opt/nim/.cache
sudo chown -R 1000:1000 /opt/nim/.cache
```

---

## Key ASR Models

| Model | Use case | Language |
|---|---|---|
| Parakeet CTC 1.1B | Fast, accurate English ASR | English |
| Parakeet RNNT 1.1B | Streaming ASR | English |
| Canary 1B | Multilingual + translation | Multiple |

For forensic audio statements (Singlish/SEA accents): evaluate Parakeet first;
Canary if multilingual support is needed. MERaLiON handles paralinguistics separately.

---

## MERaLiON (Paralinguistics) — Custom Proposal

MERaLiON-3 is NOT covered by the nemotron-speech skill.
It is a self-hosted paralinguistic analysis model (Singlish/SEA specialization).
This is a **custom proposal** (flagged in DESIGN.md §5).

Deployment approach (to be determined in Phase 4):
- Self-hosted via HuggingFace: `MERaLiON/MERaLiON-3-8B`
- Requires `HF_TOKEN` for gated model access
- Expose as a tool callable from AI-Q
- Returns: paralinguistic cues (tone, stress, emotion markers)

Read HuggingFace model card and any available deployment docs before implementing.
Do not improvise the deployment — research the official deployment method first.

---

## Integration with Ingestion Pipeline (Phase 4 Goal)

The flow for an audio evidence file:
1. Audio file arrives → stored in object store (blob)
2. Parakeet ASR transcribes → transcript text
3. Transcript ingested into RAG Blueprint corpus (same as text documents)
4. MERaLiON analysis → paralinguistic metadata stored (as graph properties in Neo4j)
5. AI-Q can query transcript via FRAG + retrieve paralinguistic cues via graph tool

---

## Limitations

- x86_64 architecture only (WSL2 on Windows requires Podman — not relevant for our server)
- Self-hosted requires NVIDIA AI Enterprise license
- Cloud-hosted requires active `NVIDIA_API_KEY` and internet access (dev only)

---

## Phase 4 Checkpoint

```bash
# Test: audio file → transcript in corpus
# 1. Transcribe a test audio file with Parakeet
# 2. Ingest transcript into RAG (via ingestor-server)
# 3. Query AI-Q: should retrieve content from the transcript
# 4. MERaLiON: analyze audio → paralinguistic output available
```
