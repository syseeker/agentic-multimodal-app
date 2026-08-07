#!/usr/bin/env python3
# /// script
# dependencies = ["httpx", "requests"]
# ///
"""
Phase 5 — Video Processing Pipeline
=====================================
For each video file in data/cases/<case_id>/video/, this script:
  1. Registers the video with VIOS (VSS video storage) — under a content-hashed
     sensor name, so a changed video is stored rather than silently rejected
  2. Writes a registration marker (<stem>_analysis.txt) for the workbench UI

It deliberately does NOT analyse the video. Analysis is ON DEMAND: when the
investigator asks Sherlock about the footage, AI-Q calls the VSS MCP tool
(mcp/vss_sherlock_mcp.py::summarize_video), which hits rtvi-vlm directly and
returns a forensic summary in ~4s. Running the VLM at upload time was tried and
abandoned; what remained was a hardcoded placeholder masquerading as a summary,
which then polluted RAG and Neo4j with boilerplate. Nothing here writes to RAG
or the entity graph — ui/server.py triggers entity extraction separately.

Unlike the audio pipeline (process_audio.py), which DOES transcribe at upload
time because ASR output is the evidence, video evidence stays in VIOS and is
interpreted per question.

This script is called:
  - By phase5_vss.sh after VSS is deployed (batch-registers existing case videos)
  - By ui/server.py after a video is uploaded via the workbench

Usage:
  uv run data/video/process_video.py [--case-id SC-2024-XXXXX] [--dry-run]

Environment:
  VIOS_URL          (default: http://localhost:30888)
  VSS_LVS_URL       (default: http://localhost:38111)
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT     = Path(__file__).parent.parent.parent
CASES_DIR     = REPO_ROOT / "data" / "cases"
VIOS_URL      = os.environ.get("VIOS_URL",      "http://localhost:30888")
VSS_LVS_URL   = os.environ.get("VSS_LVS_URL",   "http://localhost:38111")

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".mts"}

# Case type → (scenario, events) for LVS summarization context
_CASE_SCENARIOS = {
    "drug_trafficking":  ("forensic drug trafficking investigation",
                          ["exchange of package", "cash transaction", "suspicious vehicle",
                           "lookout behavior", "disposal of evidence"]),
    "homicide":          ("forensic homicide investigation",
                          ["altercation", "physical assault", "victim on ground",
                           "suspect fleeing", "weapon visible"]),
    "robbery":           ("forensic robbery investigation",
                          ["approach victim", "threat display", "property taken",
                           "suspect fleeing", "bystander reaction"]),
    "assault":           ("forensic assault investigation",
                          ["confrontation", "physical contact", "victim injured",
                           "suspect fleeing", "bystander present"]),
    "financial_fraud":   ("forensic financial fraud investigation",
                          ["document exchange", "cash handover", "identity concealment"]),
    "cybercrime":        ("forensic cybercrime scene investigation",
                          ["suspect at computer", "USB device inserted", "suspicious behavior"]),
    "human_trafficking": ("forensic human trafficking investigation",
                          ["vehicle pickup", "group movement", "coercion visible"]),
    "money_laundering":  ("forensic money laundering investigation",
                          ["large cash movement", "bag exchange", "multiple couriers"]),
}
_DEFAULT_SCENARIO = ("forensic investigation",
                     ["suspicious activity", "person movement", "object exchange"])


def _case_meta(case_dir: Path) -> dict:
    meta_file = case_dir / "metadata.json"
    return json.loads(meta_file.read_text()) if meta_file.exists() else {}


def _auto_scenario(case_dir: Path):
    meta = _case_meta(case_dir)
    ct   = meta.get("case_type", "")
    return _CASE_SCENARIOS.get(ct, _DEFAULT_SCENARIO)


# ── 1. VIOS registration ──────────────────────────────────────────────────────

def content_sensor_name(case_id: str, video_path: Path) -> str:
    """Sensor name that changes when the video's CONTENT changes.

    VIOS rejects a PUT to an existing sensor name with 409 and offers no working
    delete (DELETE by name AND by UUID both return 400 on VSS 3.2.1). So a fixed
    name like "<case>_<file>.mp4" means a re-uploaded/corrected video is silently
    NOT stored -- VIOS keeps serving the original footage under that name, and every
    later VLM analysis examines the superseded video. For forensic evidence that is
    a correctness bug, not an inconvenience.

    Including a short content hash makes identical content collide harmlessly (409 =
    "already registered", genuinely idempotent) while changed content registers as a
    new sensor. The case id and file stem stay in the name so downstream lookups that
    match on those keep working.
    """
    digest = hashlib.sha256(video_path.read_bytes()).hexdigest()[:10]
    return f"{case_id}_{video_path.stem}_{digest}{video_path.suffix}"


def register_with_vios(video_path: Path, sensor_name: str) -> tuple[bool, str]:
    """PUT video file to VIOS so it's accessible by vss-agent and vss-lvs.

    Returns (ok, detail). A 409 means this exact content is already registered under
    this sensor name, which is success for our purposes -- reported distinctly so it
    is never confused with a fresh upload.
    """
    import urllib.error, urllib.request
    ts  = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    url = f"{VIOS_URL}/vst/api/v1/storage/file/{sensor_name}?timestamp={ts}"
    try:
        req = urllib.request.Request(url, data=video_path.read_bytes(), method="PUT",
                                     headers={"Content-Type": "video/mp4"})
        urllib.request.urlopen(req, timeout=120)
        return True, "registered"
    except urllib.error.HTTPError as e:
        if e.code == 409:
            return True, "already registered (same content)"
        print(f"  ERROR: VIOS registration failed: HTTP {e.code} {e.reason}", file=sys.stderr)
        return False, f"HTTP {e.code}"
    except Exception as e:
        print(f"  ERROR: VIOS registration failed: {e}", file=sys.stderr)
        return False, str(e)


# ── Main pipeline ─────────────────────────────────────────────────────────────

def process_case(case_dir: Path, dry_run: bool = False) -> dict:
    case_id   = case_dir.name
    video_dir = case_dir / "video"
    if not video_dir.exists():
        return {"case_id": case_id, "status": "no_video_dir", "processed": 0}

    video_files = [f for f in video_dir.iterdir()
                   if f.suffix.lower() in VIDEO_EXTENSIONS and not f.name.startswith(".")]
    if not video_files:
        return {"case_id": case_id, "status": "no_videos", "processed": 0}

    scenario, events = _auto_scenario(case_dir)
    print(f"\nCase {case_id} ({len(video_files)} video file(s)):")
    print(f"  Scenario: {scenario}")

    processed = 0
    for video_file in sorted(video_files):
        sensor_name = content_sensor_name(case_id, video_file)
        print(f"  Processing: {video_file.name}")

        if dry_run:
            print(f"    [DRY RUN] would register with VIOS as {sensor_name}")
            processed += 1
            continue

        # NOTE: no skip-if-analysis-exists guard here. It used to key off the marker
        # file below, which meant a stale marker (e.g. one committed to git) silently
        # skipped VIOS registration entirely and the video was never stored. VIOS
        # itself is the idempotency check now: identical content -> 409 -> no-op.
        analysis_path = case_dir / f"{video_file.stem}_analysis.txt"

        # 1. VIOS registration -- this is the ONLY thing upload does with the video.
        vios_ok, vios_detail = register_with_vios(video_file, sensor_name)
        print(f"    {'✓' if vios_ok else '✗'} VIOS: {vios_detail}")
        if not vios_ok:
            print(f"    ✗ SKIPPING {video_file.name} — not stored in VIOS, "
                  f"Sherlock will not be able to analyse it", file=sys.stderr)
            continue

        # 2. Write the registration MARKER.
        # By design, upload does NOT run the VLM -- analysis is on demand, when the
        # investigator asks Sherlock in chat (mcp/vss_sherlock_mcp.py::summarize_video
        # calls rtvi-vlm directly, ~4s). This file exists for exactly one consumer:
        # ui/src/lib/EvidenceViewer.svelte treats "video present but no *_analysis.txt"
        # as "still processing" and polls every 15s until it appears.
        #
        # It is deliberately NOT ingested into RAG and NOT fed to entity extraction.
        # It previously carried a fake "SUMMARY" section of placeholder prose, which
        # landed in RAG as evidence text and in Neo4j as junk entities -- so a search
        # for video evidence returned "To analyse this video, ask Sherlock" instead of
        # anything about the footage. Real video content reaches the investigator
        # through the on-demand VLM call, not through this file.
        analysis_path.write_text(
            f"VIDEO EVIDENCE REGISTRATION\n"
            f"Case Reference: {case_id}\n"
            f"Source: {video_file.name}\n"
            f"VIOS Sensor: {sensor_name}\n"
            f"Registered: {datetime.now(tz=timezone.utc).isoformat()}\n"
            f"Investigation context: {scenario}\n"
            f"{'='*60}\n\n"
            f"This file is a registration receipt, not an analysis. The video is stored\n"
            f"in VIOS and analysed on demand by the VLM when Sherlock is asked about it.\n",
            encoding="utf-8",
        )
        print(f"    ✓ Wrote {analysis_path.name} (registration marker)")

        processed += 1

    return {"case_id": case_id, "status": "ok", "processed": processed}


def main():
    parser = argparse.ArgumentParser(description="Video processing pipeline")
    parser.add_argument("--case-id", help="Process one case (e.g. SC-2024-XXXXX)")
    parser.add_argument("--all",     action="store_true", help="Process all cases")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without executing")
    args = parser.parse_args()

    if not args.case_id and not args.all:
        parser.print_help(); sys.exit(1)

    case_dirs = ([CASES_DIR / args.case_id] if args.case_id
                 else sorted(CASES_DIR.glob("SC-*/")))

    total_processed = total_skipped = 0
    for case_dir in case_dirs:
        if not case_dir.is_dir():
            print(f"WARNING: {case_dir} not found", file=sys.stderr)
            continue
        r = process_case(case_dir, args.dry_run)
        total_processed += r.get("processed", 0)
        if r.get("status") in ("no_video_dir", "no_videos"):
            total_skipped += 1

    print(f"\n{'='*60}")
    print(f"Video pipeline — Summary")
    print(f"Cases processed: {len(case_dirs) - total_skipped} | Videos: {total_processed} | Skipped (no video): {total_skipped}")
    print(f"\nVideos are stored in VIOS. Analysis happens on demand — ask Sherlock about")
    print(f"the footage and the VSS MCP tool will run the VLM against it (~4s).")


if __name__ == "__main__":
    main()
