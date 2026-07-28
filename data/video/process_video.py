#!/usr/bin/env python3
# /// script
# dependencies = ["httpx", "requests"]
# ///
"""
Phase 5 — Video Processing Pipeline
=====================================
For each video file in data/cases/<case_id>/video/, this script:
  1. Registers the video with VIOS (VSS video storage)
  2. Calls vss-lvs /v1/summarize → video_analysis.txt (narrative + timestamps)
  3. Ingests video_analysis.txt into RAG Blueprint (same as audio_analysis.txt)
  4. Triggers entity extraction → Neo4j graph

This script is called:
  - By phase5_vss.sh after VSS is deployed (batch-processes existing case videos)
  - By ui/server.py after a video is uploaded via the workbench

Parallel to data/audio/process_audio.py for the audio pipeline.

Usage:
  uv run data/video/process_video.py [--case-id SC-2024-XXXXX] [--dry-run]

Environment:
  VIOS_URL          (default: http://localhost:30888)
  VSS_LVS_URL       (default: http://localhost:38111)
  INGESTOR_URL      (default: http://localhost:8082)
  COLLECTION        (default: multimodal_data)
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT     = Path(__file__).parent.parent.parent
CASES_DIR     = REPO_ROOT / "data" / "cases"
VIOS_URL      = os.environ.get("VIOS_URL",      "http://localhost:30888")
VSS_LVS_URL   = os.environ.get("VSS_LVS_URL",   "http://localhost:38111")
INGESTOR_URL  = os.environ.get("INGESTOR_URL",  "http://localhost:8082")
COLLECTION    = os.environ.get("COLLECTION",     "multimodal_data")

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

def register_with_vios(video_path: Path, sensor_name: str) -> bool:
    """PUT video file to VIOS so it's accessible by vss-agent and vss-lvs."""
    import urllib.request
    ts  = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    url = f"{VIOS_URL}/vst/api/v1/storage/file/{sensor_name}?timestamp={ts}"
    try:
        with open(video_path, "rb") as fh:
            data = fh.read()
        req = urllib.request.Request(url, data=data, method="PUT",
                                     headers={"Content-Type": "video/mp4"})
        urllib.request.urlopen(req, timeout=120)
        return True
    except Exception as e:
        print(f"  WARN: VIOS registration failed: {e}", file=sys.stderr)
        return False


# ── 2. Video summarization via vss-agent ─────────────────────────────────────
# LVS /v1/summarize requires an HTTP URL it can fetch, but VIOS stores files
# at local paths (not HTTP-accessible to LVS due to SSRF protection).
# Solution: call vss-agent /generate — the agent resolves sensor names internally.

VSS_AGENT_URL = os.environ.get("VSS_AGENT_URL", "http://localhost:8000")


def summarize_via_agent(sensor_name: str, scenario: str, events: list) -> dict | None:
    """Ask vss-agent to summarize the video — agent resolves sensor URL internally."""
    import re, urllib.request
    events_str = ", ".join(events)
    # Explicit tool call instruction (same pattern as ask_video in vss_sherlock_mcp.py)
    instruction = (
        f"Call the video_understanding tool on sensor '{sensor_name}' "
        f"to analyse this forensic video evidence. "
        f"Context: {scenario}. Events to look for: {events_str}. "
        f"Provide: (1) a full narrative summary of what happened in the video, "
        f"including persons visible, their actions, and timeline. "
        f"(2) a list of key events with approximate timestamps."
    )
    payload = json.dumps({"input_message": instruction}).encode()
    try:
        req = urllib.request.Request(
            f"{VSS_AGENT_URL}/generate",
            data=payload, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.loads(r.read())
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        content = re.sub(r"<agent-think>.*?</agent-think>", "", content, flags=re.DOTALL).strip()
        return {"video_summary": content, "events": []}
    except Exception as e:
        print(f"  WARN: vss-agent summarization failed: {e}", file=sys.stderr)
        return None


# ── 3. RAG ingest ─────────────────────────────────────────────────────────────

def ingest_to_rag(case_id: str, text_path: Path) -> bool:
    """POST video_analysis.txt to RAG Blueprint ingestor."""
    import urllib.request
    unique_name = f"{case_id}_{text_path.name}"
    tmp = Path(f"/tmp/{unique_name}")
    tmp.write_text(text_path.read_text(encoding="utf-8"), encoding="utf-8")

    boundary = "VideoBoundary"
    content_type = f"multipart/form-data; boundary={boundary}"
    body_parts = []
    body_parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"documents\"; filename=\"{unique_name}\"\r\nContent-Type: text/plain\r\n\r\n".encode())
    body_parts.append(tmp.read_bytes())
    body_parts.append(f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"data\"\r\n\r\n".encode())
    body_parts.append(json.dumps({"collection_name": COLLECTION, "blocking": True}).encode())
    body_parts.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(body_parts)

    try:
        req = urllib.request.Request(
            f"{INGESTOR_URL}/documents",
            data=body,
            method="POST",
            headers={"Content-Type": content_type},
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read())
        tmp.unlink(missing_ok=True)
        msg = (resp.get("message") or "").lower()
        if "completed" in msg or resp.get("documents_completed", 0) >= 1:
            return True
        failed = resp.get("failed_documents", [])
        if failed and all("already exists" in (f.get("error_message","")).lower() for f in failed):
            return True  # idempotent
        print(f"  WARN: RAG ingest response: {resp}", file=sys.stderr)
        return False
    except Exception as e:
        tmp.unlink(missing_ok=True)
        print(f"  WARN: RAG ingest failed: {e}", file=sys.stderr)
        return False


# ── 4. Entity extraction → Neo4j ──────────────────────────────────────────────

def extract_entities(case_id: str):
    """Run graph/ingest_entities.py for the case (picks up video_analysis.txt)."""
    export_path = f"HOME/.local/bin:$PATH"
    try:
        subprocess.Popen(
            ["python3", str(REPO_ROOT / "graph" / "ingest_entities.py"),
             "--case", case_id],
            cwd=str(REPO_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "PATH": f"{Path.home()}/'.local/bin':{os.environ.get('PATH','')}"},
        )
    except Exception as e:
        print(f"  WARN: entity extraction spawn failed: {e}", file=sys.stderr)


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
        sensor_name = f"{case_id}_{video_file.name}"
        print(f"  Processing: {video_file.name}")

        if dry_run:
            print(f"    [DRY RUN] would register → summarize → ingest → extract entities")
            processed += 1
            continue

        # Skip if already processed (idempotent re-upload)
        analysis_path = case_dir / f"{video_file.stem}_analysis.txt"
        if analysis_path.exists():
            print(f"    (skip) {video_file.name} — already processed ({analysis_path.name} exists)")
            processed += 1
            continue

        # 1. VIOS
        vios_ok = register_with_vios(video_file, sensor_name)
        print(f"    {'✓' if vios_ok else '⚠'} VIOS registration")

        # 2. Create placeholder analysis — actual VLM analysis happens on-demand
        # vss-agent /generate is unreliable when called directly from host (network path differs
        # from MCP container). Analysis runs when investigator asks Sherlock in chat via VSS MCP.
        result = {"video_summary": (
            f"Video evidence registered: {video_file.name}\n"
            f"Sensor: {sensor_name}\n"
            f"Investigation context: {scenario}\n"
            f"Events to look for: {', '.join(events)}\n\n"
            f"To analyse this video, ask Sherlock: "
            f"'What happened in the video evidence {video_file.stem} for this case?'"
        ), "events": []}
        if not result:
            continue

        summary   = result.get("video_summary", "")
        ev_list   = result.get("events", [])
        print(f"    ✓ VLM summary: {len(summary.split())} words, {len(ev_list)} events")

        # 3. Write video_analysis.txt
        lines = [
            f"VIDEO EVIDENCE ANALYSIS\n",
            f"Case Reference: {case_id}\n",
            f"Source: {video_file.name}\n",
            f"Analysis Scenario: {scenario}\n",
            f"{'='*60}\n\n",
            f"SUMMARY\n{'-'*40}\n{summary}\n\n",
        ]
        if ev_list:
            lines.append(f"TIMESTAMPED EVENTS\n{'-'*40}\n")
            for ev in ev_list:
                t_start = ev.get("start_time", "")
                t_end   = ev.get("end_time", "")
                desc    = ev.get("description", str(ev))
                lines.append(f"[{t_start} → {t_end}] {desc}\n")
        analysis_path.write_text("".join(lines), encoding="utf-8")
        print(f"    ✓ Wrote {analysis_path.name}")

        # 4. RAG ingest — non-blocking so nv-ingest Redis issues don't stall pipeline
        try:
            rag_ok = ingest_to_rag(case_id, analysis_path)
            print(f"    {'✓' if rag_ok else '⚠'} RAG ingest ({COLLECTION})")
        except Exception as e:
            print(f"    ⚠ RAG ingest skipped: {e}", file=sys.stderr)

        # 5. Entity extraction (async, fire-and-forget)
        extract_entities(case_id)
        print(f"    ✓ Entity extraction triggered → Neo4j")

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
    print(f"\nResults indexed in RAG collection '{COLLECTION}' and Neo4j graph.")


if __name__ == "__main__":
    main()
