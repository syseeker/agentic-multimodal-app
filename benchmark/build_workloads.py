#!/usr/bin/env python3
"""Phase 9e — build aiperf workloads from the real Phase 3 case corpus.

Deterministic and regenerable: same corpus in, same files out. No network, no GPU, so this
runs on any box before moving to the GPU instance.

    python3 benchmark/build_workloads.py [--out benchmark/workloads]

Emits, into --out:
  rag_queries.jsonl   forensic questions over the case corpus  (rag-perf input.file)
  vlm_video.jsonl     video prompts for the sample MP4s        (aiperf --input-file)
  audio_manifest.json the sample WAVs with measured durations  (MERaLiON shim driver)
  corpus_stats.json   token/length profile of the corpus       (sizing evidence)

Why real case data and not synthetic prompts: the whole point is to size Sherlock's actual
workload. A generic prompt set would give numbers that describe nothing we ship.
"""
from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = REPO_ROOT / "data" / "cases"
AUDIO_SAMPLE = REPO_ROOT / "data" / "audio" / "sample"
VIDEO_SAMPLE = REPO_ROOT / "data" / "video" / "sample"

# ~4 chars/token. Rough on purpose: this sizes context windows, it is not a billing figure.
CHARS_PER_TOKEN = 4

CASE_FILES = ("case_report.txt", "witness_statement.txt", "lab_report.txt", "whatsapp_chat.txt")

# Questions mirroring what an investigator actually asks the workbench. Kept stable so runs
# stay comparable; extend by appending, never by reordering.
QUESTION_TEMPLATES = (
    "What happened in case {case_id}? Summarise the incident with citations.",
    "Who are the suspects in case {case_id} and what links them to the evidence?",
    "What physical evidence was recovered in case {case_id}, and what did the lab find?",
    "Summarise the WhatsApp communications in case {case_id}. Who talked to whom?",
    "What inconsistencies exist between the witness statement and the case report in {case_id}?",
)

VIDEO_PROMPTS = (
    "Describe what happens in this video. Note any weapon, assault, or exchange of items.",
    "Identify each person visible, what they are wearing, and what they do.",
    "Summarise this footage as a forensic narrative suitable for a case report.",
)

# Paralinguistic questions -- what an investigator actually asks of a statement recording.
AUDIO_PROMPTS = (
    "Describe the speaker's emotion, stress level and language.",
    "Does the speaker sound truthful or evasive? Cite what in the audio supports that.",
)


def case_ids() -> list[str]:
    if not CASES_DIR.is_dir():
        return []
    return sorted(p.name for p in CASES_DIR.iterdir() if p.is_dir())


def corpus_stats(ids: list[str]) -> dict:
    """Per-file-type length profile — the evidence behind ISL sizing."""
    per_type: dict[str, list[int]] = {name: [] for name in CASE_FILES}
    per_case_total: list[int] = []
    for cid in ids:
        total = 0
        for name in CASE_FILES:
            f = CASES_DIR / cid / name
            if f.is_file():
                n = len(f.read_text(encoding="utf-8", errors="replace"))
                per_type[name].append(n)
                total += n
        if total:
            per_case_total.append(total)

    def summarize(vals: list[int]) -> dict:
        if not vals:
            return {"n": 0}
        return {
            "n": len(vals),
            "mean_chars": round(sum(vals) / len(vals)),
            "min_chars": min(vals),
            "max_chars": max(vals),
            "mean_tokens_est": round(sum(vals) / len(vals) / CHARS_PER_TOKEN),
        }

    return {
        "cases": len(ids),
        "per_file": {k: summarize(v) for k, v in per_type.items()},
        "per_case_total": summarize(per_case_total),
        "chars_per_token_assumed": CHARS_PER_TOKEN,
    }


def audio_manifest() -> list[dict]:
    """Sample WAVs with real durations read from the headers, not guessed from file size."""
    out = []
    if not AUDIO_SAMPLE.is_dir():
        return out
    for f in sorted(AUDIO_SAMPLE.glob("*.wav")):
        try:
            with wave.open(str(f)) as w:
                rate, frames, ch = w.getframerate(), w.getnframes(), w.getnchannels()
            out.append({
                "path": str(f.relative_to(REPO_ROOT)),
                "sample_rate_hz": rate,
                "channels": ch,
                "duration_s": round(frames / rate, 1),
                # MERaLiON's encoder caps at 30 s per forward pass, so a longer clip
                # costs N passes. A request is therefore NOT fixed work -- record the
                # window count so per-request latency can be normalised.
                "meralion_windows": max(1, -(-int(frames / rate) // 30)),
            })
        except Exception as e:  # a malformed sample should be visible, not skipped silently
            out.append({"path": str(f.relative_to(REPO_ROOT)), "error": str(e)})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO_ROOT / "benchmark" / "workloads"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    ids = case_ids()
    if not ids:
        print(f"ERROR: no cases under {CASES_DIR}. Run Phase 3 first.")
        return 1

    # 1. RAG queries — one per (case, template).
    rag = out / "rag_queries.jsonl"
    with rag.open("w", encoding="utf-8") as fh:
        for cid in ids:
            for tpl in QUESTION_TEMPLATES:
                fh.write(json.dumps({"text": tpl.format(case_id=cid), "case_id": cid}) + "\n")
    n_rag = len(ids) * len(QUESTION_TEMPLATES)

    # 2. VLM video prompts. NOTE: aiperf sends plain OpenAI bodies, so Sherlock's
    #    num_frames_per_second_or_fixed_frames_chunk / use_fps_for_chunking extras must be
    #    supplied via --extra-inputs, or this measures a different workload than production.
    videos = sorted(VIDEO_SAMPLE.glob("*.mp4")) if VIDEO_SAMPLE.is_dir() else []
    vlm = out / "vlm_video.jsonl"
    with vlm.open("w", encoding="utf-8") as fh:
        for v in videos:
            for prompt in VIDEO_PROMPTS:
                fh.write(json.dumps({
                    "text": prompt,
                    "video": str(v.relative_to(REPO_ROOT)),
                }) + "\n")
    n_vlm = len(videos) * len(VIDEO_PROMPTS)

    # 3. Audio: a DRIVABLE workload + the manifest that explains it.
    #
    # audio_manifest.json is metadata (durations, window counts) and aiperf CANNOT drive it:
    # it is a JSON array, while --custom-dataset-type single_turn reads JSONL. aiperf died
    # with "Invalid JSON in dataset file" and every MERaLiON tenant recorded n_requests=0
    # while the window still reported "completed". Emit the payload file as well.
    #
    # `audio: <path>` is aiperf's single-turn field for a local clip: it reads the WAV and
    # renders {"type":"input_audio","input_audio":{"data":<b64>,...}}, exactly what
    # data/audio/meralion_server.py::_extract decodes. Keep the manifest for the
    # meralion_windows normalisation -- a 99 s clip is 4 forward passes, not one unit of work.
    manifest = audio_manifest()
    n_audio = 0
    with (out / "audio_statements.jsonl").open("w", encoding="utf-8") as fh:
        for entry in manifest:
            if entry.get("error"):
                continue
            for prompt in AUDIO_PROMPTS:
                fh.write(json.dumps({"text": prompt, "audio": entry["path"]}) + "\n")
                n_audio += 1

    (out / "audio_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    stats = corpus_stats(ids)
    (out / "corpus_stats.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")

    print(f"cases            : {len(ids)}")
    print(f"rag_queries.jsonl: {n_rag} queries")
    print(f"vlm_video.jsonl  : {n_vlm} prompts over {len(videos)} videos")
    print(f"audio_statements : {n_audio} prompts over {len(manifest)} wav(s)")
    print(f"mean tokens/case : ~{stats['per_case_total'].get('mean_tokens_est', 0)}")
    if n_rag < 50:
        print("NOTE: fewer than 50 queries — any p99 from this set must be labelled unreliable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
