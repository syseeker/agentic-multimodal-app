#!/usr/bin/env python3
"""
Convert forensic_cases parquet to per-case folder structure.

Output layout:
  data/cases/<case_id>/
    case_report.txt        — incident summary + officer notes (official SPF document)
    witness_statement.txt  — witness statement (raw testimony)
    lab_report.txt         — forensic lab analysis
    whatsapp_chat.txt      — extracted WhatsApp chat (raw artifact from device)
    audio/                 — placeholder (sim-case-audio, post-Phase 9)
    images/                — placeholder (sim-case-images, post-Phase 9)
    video/                 — placeholder (sim-case-video, post-Phase 9)
    metadata.json          — structured case metadata (for ingest tagging)
"""
import json
import sys
from pathlib import Path

import pandas as pd


def evidence_to_text(ev) -> str:
    records = ev.get("records", []) if isinstance(ev, dict) else []
    lines = []
    for r in records:
        lines.append(
            f"  [{r.get('evidence_id', '?')}] {r.get('evidence_type', '').upper()}\n"
            f"    Description: {r.get('description', '')}\n"
            f"    Collected from: {r.get('collection_location', '')}\n"
            f"    Chain of custody: {r.get('chain_of_custody', '')}"
        )
    return "\n\n".join(lines)


def write_case(row: pd.Series, cases_dir: Path) -> Path:
    case_id = row["case_id"]
    case_dir = cases_dir / case_id
    case_dir.mkdir(parents=True, exist_ok=True)

    # ── Placeholder directories for future modalities ─────────────────────
    for subdir in ("audio", "images", "video"):
        (case_dir / subdir).mkdir(exist_ok=True)
        (case_dir / subdir / ".gitkeep").touch()

    # ── metadata.json ──────────────────────────────────────────────────────
    ev = row.get("evidence", {})
    if hasattr(ev, "records"):  # Pydantic object
        ev = ev.model_dump()
    meta = {
        "case_id": case_id,
        "incident_date": str(row["incident_date"]),
        "case_type": row["case_type"],
        "severity": row["severity"],
        "district": row["district"],
        "case_status": row["case_status"],
        "suspect_name": row["suspect_name"],
        "suspect_age": int(row["suspect_age"]),
        "suspect_nationality": row["suspect_nationality"],
        "assigned_officer": row["assigned_officer"],
        "evidence_ids": [r.get("evidence_id") for r in ev.get("records", [])],
    }
    (case_dir / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))

    # ── case_report.txt ────────────────────────────────────────────────────
    case_report = f"""SINGAPORE POLICE FORCE
OFFICIAL CASE REPORT
{'='*60}
Case Reference: {case_id}
Incident Date:  {row['incident_date']}
Case Type:      {row['case_type'].replace('_', ' ').title()}
Severity:       {row['severity'].upper()}
District:       {row['district']}
Status:         {row['case_status'].replace('_', ' ').title()}

SUSPECT PARTICULARS
{'-'*40}
Name:           {row['suspect_name']}
Age:            {row['suspect_age']}
Nationality:    {row['suspect_nationality']}

ASSIGNED OFFICER
{'-'*40}
{row['assigned_officer']}

INCIDENT SUMMARY
{'-'*40}
{row['incident_summary']}

EVIDENCE COLLECTED
{'-'*40}
{evidence_to_text(ev)}

INVESTIGATING OFFICER NOTES
{'-'*40}
{row['investigating_officer_notes']}
{'='*60}
[END OF REPORT]
"""
    (case_dir / "case_report.txt").write_text(case_report, encoding="utf-8")

    # ── witness_statement.txt ──────────────────────────────────────────────
    witness = f"""SINGAPORE POLICE FORCE
WITNESS STATEMENT
{'='*60}
Case Reference: {case_id}
Date Recorded:  {row['incident_date']}

STATEMENT
{'-'*40}
{row['witness_statement']}
{'='*60}
[END OF STATEMENT]
"""
    (case_dir / "witness_statement.txt").write_text(witness, encoding="utf-8")

    # ── lab_report.txt ─────────────────────────────────────────────────────
    lab = f"""SINGAPORE POLICE FORCE
FORENSIC LABORATORY REPORT
{'='*60}
Case Reference: {case_id}
Incident Date:  {row['incident_date']}
Case Type:      {row['case_type'].replace('_', ' ').title()}

ANALYSIS
{'-'*40}
{row['lab_report']}
{'='*60}
[END OF LAB REPORT]
"""
    (case_dir / "lab_report.txt").write_text(lab, encoding="utf-8")

    # ── whatsapp_chat.txt ──────────────────────────────────────────────────
    chat = f"""EXTRACTED WHATSAPP CHAT
Source: Confiscated device of {row['suspect_name']}
Case Reference: {case_id}
Extraction Date: {row['incident_date']}
{'='*60}
{row['whatsapp_chat']}
{'='*60}
[END OF EXTRACTION]
"""
    (case_dir / "whatsapp_chat.txt").write_text(chat, encoding="utf-8")

    return case_dir


def main():
    repo_root = Path(__file__).parent.parent.parent
    parquet_path = repo_root / "data/sim/artifacts/forensic_cases_sg/parquet-files/batch_00000.parquet"
    cases_dir = repo_root / "data/cases"

    if not parquet_path.exists():
        print(f"ERROR: {parquet_path} not found. Run data-designer create first.")
        sys.exit(1)

    df = pd.read_parquet(parquet_path)
    cases_dir.mkdir(parents=True, exist_ok=True)

    print(f"Packaging {len(df)} cases into {cases_dir}/")
    for _, row in df.iterrows():
        case_dir = write_case(row, cases_dir)
        print(f"  ✓ {case_dir.name}")

    print(f"\nDone. {len(df)} case folders created under data/cases/")
    print("Each folder contains: case_report.txt, witness_statement.txt,")
    print("  lab_report.txt, whatsapp_chat.txt, metadata.json")
    print("  + empty audio/, images/, video/ dirs for future modalities")


if __name__ == "__main__":
    main()
