#!/usr/bin/env python3
# /// script
# dependencies = ["nvidia-riva-client", "soundfile", "numpy", "scipy", "requests"]
# ///
"""
Phase 4 — Audio Processing Pipeline

For each case in data/cases/<case_id>/audio/, this script:
  1. Normalizes audio to mono WAV 16kHz 16-bit PCM (ffmpeg if available, else soundfile+scipy)
  2. Transcribes via a developer-chosen Parakeet model (cloud, grpc.nvcf.nvidia.com)
  3. Writes <filename>_transcript.txt alongside the audio file
  4. Writes audio_analysis.txt to the case root (aggregated, for RAG BP ingestion)
  5. Ingests audio_analysis.txt into RAG Blueprint as {case_id}_audio_analysis.txt

MODEL SELECTION — developer decides, not the tool:
  Set ASR_MODEL env var or --model flag. Available cloud models (from NVCF):

  ai-parakeet-1_1b-rnnt-multilingual-asr   [DEFAULT] Multilingual streaming+offline.
                                             Best for Singapore forensic context: covers
                                             English, Mandarin, Malay, Vietnamese, Filipino.
  ai-parakeet-ctc-1_1b-asr                  Best English accuracy + word timestamps.
                                             Use if all audio is English only.
  ai-whisper-large-v3                        Broadest language coverage (99 langs).
                                             Offline only. Use for unknown/rare languages.
  ai-nemotron-asr-streaming                  English streaming + speaker diarization
                                             (who said what). Use for interrogation recordings.
  ai-canary-1b-asr                           Offline batch + bidirectional translation.
                                             Use if you need transcript + translation.

  Note: In Phase 7, AI-Q (Sherlock) will route to the right model automatically based
  on case context (suspect nationality, detected language, audio type).

MERaLiON paralinguistics (Singlish sentiment/emotion/speaker-state) is stubbed here.
It requires a GPU + HuggingFace transformers. Wire it up in Phase 7 as a forensic
processing tool alongside NER, sentiment, and image captioning.

Usage:
  export NVIDIA_API_KEY=<key>
  python3 data/audio/process_audio.py [--case-id SC-2024-XXXXXXXX] [--dry-run]
    [--model ai-parakeet-1_1b-rnnt-multilingual-asr]

  Or set env var (consistent with INGESTOR_URL, COLLECTION, NVIDIA_API_KEY):
  export ASR_MODEL=ai-whisper-large-v3
  python3 data/audio/process_audio.py

Audio format support (on-the-wire):
  - WAV: mono, 16-bit PCM, any sample rate (resampled to model rate)
  - Opus/OGG: mono
  - Other formats (MP3, M4A, AAC, FLAC): requires ffmpeg for conversion

NVIDIA skill followed: nemotron-speech v1.0.0
  references/model-selection.md  → model family taxonomy + decision framework
  references/asr.md               → cloud Option A, gRPC, inline Quick path
"""
import argparse
import json
import os
import struct
import subprocess
import sys
import wave
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
CASES_DIR = REPO_ROOT / "data/cases"
INGESTOR_URL = os.environ.get("INGESTOR_URL", "http://localhost:8082")
COLLECTION = os.environ.get("COLLECTION", "multimodal_data")

CLOUD_SERVER = "grpc.nvcf.nvidia.com:443"
# Default model — developer can override via --model or ASR_MODEL env var.
# See module docstring for the full model menu and when to use each.
DEFAULT_ASR_MODEL = "ai-parakeet-1_1b-rnnt-multilingual-asr"
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".mp4"}
TARGET_SR = 16000


# ── Audio normalization ────────────────────────────────────────────────────────

def normalize_to_wav(input_path: Path, output_path: Path) -> bool:
    """Convert any audio file to mono WAV 16kHz 16-bit PCM.
    Tries ffmpeg first; falls back to soundfile+scipy for WAV inputs.
    Returns True on success."""
    # ffmpeg path (preferred — handles all formats)
    if _ffmpeg_available():
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(input_path), "-ac", "1",
             "-ar", str(TARGET_SR), "-acodec", "pcm_s16le", str(output_path)],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            return True
        print(f"  WARNING: ffmpeg failed: {result.stderr.strip()[:200]}", file=sys.stderr)

    # Python fallback (WAV only; other formats need ffmpeg)
    ext = input_path.suffix.lower()
    if ext not in (".wav",):
        print(f"  ERROR: {ext} requires ffmpeg for conversion. Install ffmpeg.", file=sys.stderr)
        return False

    try:
        import numpy as np
        import soundfile as sf
        from scipy.signal import resample_poly
        from math import gcd

        data, sr = sf.read(str(input_path), dtype="int16", always_2d=True)
        # Downmix to mono
        mono = data.mean(axis=1).astype("int16") if data.shape[1] > 1 else data[:, 0]
        # Resample if needed
        if sr != TARGET_SR:
            g = gcd(TARGET_SR, sr)
            up, down = TARGET_SR // g, sr // g
            mono_f = mono.astype("float32")
            mono = resample_poly(mono_f, up, down).clip(-32768, 32767).astype("int16")
        # Write WAV
        with wave.open(str(output_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(TARGET_SR)
            wf.writeframes(struct.pack(f"<{len(mono)}h", *mono))
        return True
    except Exception as e:
        print(f"  ERROR in Python normalization: {e}", file=sys.stderr)
        return False


def _ffmpeg_available() -> bool:
    return subprocess.run(["which", "ffmpeg"], capture_output=True).returncode == 0


# ── NVCF function-id discovery ─────────────────────────────────────────────────

def discover_function_id(api_key: str, model_name: str) -> str | None:
    """Resolve the current NVCF function-id for a model by name. Never hardcode FIDs."""
    import urllib.request
    url = "https://api.nvcf.nvidia.com/v2/nvcf/functions?visibility=public,authorized"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        for fn in data.get("functions", []):
            if fn.get("status") == "ACTIVE" and fn.get("name", "") == model_name:
                return fn["id"]
    except Exception as e:
        print(f"  WARNING: NVCF function discovery failed: {e}", file=sys.stderr)
    return None


# ── Parakeet transcription ─────────────────────────────────────────────────────

def transcribe_wav(wav_path: Path, api_key: str, fid: str) -> str:
    """Transcribe a mono 16kHz WAV using Parakeet via cloud gRPC.
    Returns the transcript text (empty string if nothing recognized)."""
    import riva.client

    with wave.open(str(wav_path), "rb") as wf:
        sr = wf.getframerate()
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
        pcm = wf.readframes(wf.getnframes())

    if ch != 1:
        raise ValueError(f"WAV must be mono (got {ch} channels). Run normalization first.")
    if sw != 2:
        raise ValueError("WAV must be 16-bit PCM.")

    md = [["function-id", fid], ["authorization", f"Bearer {api_key}"]]
    auth = riva.client.Auth(uri=CLOUD_SERVER, use_ssl=True, metadata_args=md)
    asr = riva.client.ASRService(auth)

    cfg = riva.client.RecognitionConfig(
        language_code="en-US",
        sample_rate_hertz=sr,
        audio_channel_count=1,
        encoding=riva.client.AudioEncoding.LINEAR_PCM,
        enable_automatic_punctuation=True,
        max_alternatives=1,
    )
    scfg = riva.client.StreamingRecognitionConfig(config=cfg, interim_results=False)
    chunk_size = sr * 2  # 1-second chunks
    chunks = (pcm[i:i+chunk_size] for i in range(0, len(pcm), chunk_size))

    parts = []
    for resp in asr.streaming_response_generator(audio_chunks=chunks, streaming_config=scfg):
        for r in resp.results:
            if r.is_final and r.alternatives:
                parts.append(r.alternatives[0].transcript)
    return " ".join(parts).strip()


# ── MERaLiON paralinguistics stub ─────────────────────────────────────────────

def meralion_paralinguistics(wav_path: Path) -> dict:
    """
    MERaLiON-3 paralinguistics — STUB (Phase 7).

    MERaLiON (NTU/A*STAR) provides:
      - Singlish/Singapore English speech understanding
      - Sentiment analysis from speech prosody
      - Language identification (en, zh, ms, ta and code-switching)
      - Speaker emotion state

    Requires: GPU + `pip install transformers torch` + HuggingFace token
    Model: MERaLiON/MERaLiON-AudioLLM-Whisper-SEA-LION

    Wire up in Phase 7 alongside NER, graph enrichment, and image captioning
    as part of the forensic pre-processing pipeline.
    """
    return {
        "status": "stub",
        "note": "MERaLiON paralinguistics deferred to Phase 7 (requires GPU + HF token)",
        "model": "MERaLiON/MERaLiON-AudioLLM-Whisper-SEA-LION",
    }


# ── RAG ingest ─────────────────────────────────────────────────────────────────

def ingest_text(case_id: str, filename: str, text_path: Path) -> bool:
    """Ingest a text file into RAG Blueprint with {case_id}_ prefix.
    Uses curl via subprocess — same approach proven in Phase 3."""
    unique_name = f"{case_id}_{filename}"
    tmp = Path(f"/tmp/{unique_name}")
    tmp.write_text(text_path.read_text(encoding="utf-8"), encoding="utf-8")
    try:
        data_val = f'data={json.dumps({"collection_name": COLLECTION, "blocking": True})}'
        result = subprocess.run(
            [
                "curl", "-sf", "-X", "POST", f"{INGESTOR_URL}/documents",
                "-F", f"documents=@{tmp};type=text/plain",
                "-F", data_val,
            ],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            err = result.stderr.strip()
            if "already exists" in err.lower():
                return True
            print(f"  ERROR ingesting {unique_name}: curl exit {result.returncode}: {err[:200]}", file=sys.stderr)
            return False
        out = result.stdout
        if "successfully completed" in out.lower() or "already exists" in out.lower():
            return True
        resp = json.loads(out) if out.strip() else {}
        status = resp.get("status", resp.get("task_status", "unknown"))
        if "success" in str(status).lower() or "complet" in str(status).lower():
            return True
        print(f"  WARNING: ingest resp={out[:300]}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"  ERROR ingesting {unique_name}: {e}", file=sys.stderr)
        return False
    finally:
        tmp.unlink(missing_ok=True)


# ── Main pipeline ──────────────────────────────────────────────────────────────

def process_case(case_dir: Path, api_key: str, fid: str, dry_run: bool, asr_model: str = DEFAULT_ASR_MODEL) -> dict:
    case_id = case_dir.name
    audio_dir = case_dir / "audio"
    transcripts = []
    failed = []

    audio_files = [f for f in audio_dir.iterdir()
                   if f.suffix.lower() in AUDIO_EXTENSIONS and not f.name.startswith(".")]
    if not audio_files:
        return {"case_id": case_id, "status": "no_audio", "transcripts": 0}

    print(f"\nCase {case_id} ({len(audio_files)} audio file(s)):")
    for audio_file in sorted(audio_files):
        print(f"  Processing: {audio_file.name}")
        norm_wav = audio_dir / f"_norm_{audio_file.stem}.wav"

        if not dry_run:
            if not normalize_to_wav(audio_file, norm_wav):
                failed.append(audio_file.name)
                continue

            try:
                transcript = transcribe_wav(norm_wav, api_key, fid)
                norm_wav.unlink(missing_ok=True)
            except Exception as e:
                print(f"    ERROR transcribing: {e}", file=sys.stderr)
                norm_wav.unlink(missing_ok=True)
                failed.append(audio_file.name)
                continue

            # MERaLiON stub
            paralinguistics = meralion_paralinguistics(audio_file)

            # Write per-file transcript
            transcript_file = audio_dir / f"{audio_file.stem}_transcript.txt"
            transcript_file.write_text(
                f"AUDIO TRANSCRIPT\n"
                f"Source: {audio_file.name}\n"
                f"Case: {case_id}\n"
                f"Model: {asr_model} (cloud)\n"
                f"{'='*60}\n"
                f"{transcript if transcript else '[No speech detected]'}\n"
                f"{'='*60}\n"
                f"Paralinguistics: {json.dumps(paralinguistics, indent=2)}\n",
                encoding="utf-8",
            )
            transcripts.append({
                "file": audio_file.name,
                "transcript": transcript,
                "paralinguistics": paralinguistics,
            })
            print(f"    ✓ Transcript: {len(transcript.split())} words")
        else:
            print(f"    [DRY RUN] would normalize + transcribe")

    if transcripts and not dry_run:
        # Write aggregated audio_analysis.txt for RAG BP ingestion
        analysis_file = case_dir / "audio_analysis.txt"
        lines = [
            f"AUDIO EVIDENCE ANALYSIS\n"
            f"Case Reference: {case_id}\n"
            f"{'='*60}\n"
        ]
        for t in transcripts:
            lines.append(
                f"\nSOURCE: {t['file']}\n"
                f"{'-'*40}\n"
                f"{t['transcript'] if t['transcript'] else '[No speech detected]'}\n"
            )
        analysis_file.write_text("".join(lines), encoding="utf-8")

        # Ingest into RAG BP
        ok = ingest_text(case_id, "audio_analysis.txt", analysis_file)
        print(f"  {'✓' if ok else 'FAILED'} Ingested audio_analysis.txt into RAG BP")

    return {
        "case_id": case_id,
        "status": "ok" if not failed else "partial",
        "transcripts": len(transcripts),
        "failed": failed,
    }


def main():
    parser = argparse.ArgumentParser(description="Phase 4 audio processing pipeline")
    parser.add_argument("--case-id", help="Process only this case (e.g. SC-2024-XXXXXXXX)")
    parser.add_argument("--dry-run", action="store_true", help="Scan only, no API calls")
    args = parser.parse_args()

    # All configuration via env vars (consistent with INGESTOR_URL, COLLECTION, NVIDIA_API_KEY)
    asr_model = os.environ.get("ASR_MODEL", DEFAULT_ASR_MODEL)

    # Load API key from .env if not already exported
    api_key = os.environ.get("NVIDIA_API_KEY", "")
    if not api_key:
        env_file = REPO_ROOT / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("NVIDIA_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().split("#")[0].strip()
                    break
    if not api_key and not args.dry_run:
        print("ERROR: NVIDIA_API_KEY not set. Export it or add to .env", file=sys.stderr)
        sys.exit(1)

    # Discover function-id (never hardcode)
    fid = None
    if not args.dry_run:
        print(f"ASR_MODEL: {asr_model}")
        print(f"Discovering NVCF function-id...")
        fid = discover_function_id(api_key, asr_model)
        if not fid:
            print(f"ERROR: Could not resolve function-id for {asr_model}. Check NVIDIA_API_KEY or ASR_MODEL.", file=sys.stderr)
            sys.exit(1)
        print(f"✓ FID resolved (not printed — treat as credential)")

    # Find case dirs to process
    if args.case_id:
        case_dirs = [CASES_DIR / args.case_id]
    else:
        case_dirs = sorted(CASES_DIR.glob("SC-*/"))

    results = []
    for case_dir in case_dirs:
        if not case_dir.is_dir():
            print(f"WARNING: {case_dir} not found", file=sys.stderr)
            continue
        result = process_case(case_dir, api_key, fid, args.dry_run, asr_model)
        results.append(result)

    # Summary
    total_cases = len(results)
    total_transcripts = sum(r["transcripts"] for r in results)
    total_no_audio = sum(1 for r in results if r["status"] == "no_audio")
    total_failed = sum(len(r.get("failed", [])) for r in results)

    print(f"\n{'='*60}")
    print(f"Phase 4 Audio Pipeline — Summary")
    print(f"Cases processed: {total_cases} | No audio: {total_no_audio}")
    print(f"Transcripts:     {total_transcripts} | Failed: {total_failed}")
    if total_failed:
        print("WARNING: Some files failed. Re-run to retry.")
    if total_no_audio == total_cases:
        print("\nNOTE: No audio files found in any case dir.")
        print("Drop audio files into data/cases/<case_id>/audio/ and re-run.")
        print("Supported: .wav, .mp3, .m4a, .aac, .flac, .ogg, .opus, .mp4")


if __name__ == "__main__":
    main()
