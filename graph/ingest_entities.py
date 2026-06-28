#!/usr/bin/env python3
"""
Entity extraction ingest — runs at case-file ingest time.

For every case in data/cases/, reads all text content (case reports,
witness statements, lab reports, WhatsApp chats, audio transcripts)
and writes extracted entities + relations to Neo4j.

Called by ingest_cases.sh after RAG-BP ingest, or standalone:
  python3 graph/ingest_entities.py [--case SC-2024-XXXXXXXX]
"""
import argparse
import os
import sys
from pathlib import Path

# Add repo root to path
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Load .env from repo root if env vars not already set
def _load_env():
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        # Strip inline comments (handles: KEY=value  # comment — with unicode)
        val = val.split("#")[0].strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val

_load_env()

from graph.tools import extract_entities, init_schema

CASES_DIR = Path(__file__).parent.parent / "data" / "cases"

# Files to extract entities from, with their content type label
CONTENT_FILES = [
    ("case_report.txt",       "text"),
    ("witness_statement.txt", "text"),
    ("lab_report.txt",        "text"),
    ("whatsapp_chat.txt",     "chat"),
    ("audio_analysis.txt",    "transcript"),  # Parakeet output from Phase 4
]


def ingest_case(case_id: str, case_dir: Path, verbose: bool = True) -> dict:
    results = {"case_id": case_id, "files": [], "total_entities": 0, "total_relations": 0}

    for filename, content_type in CONTENT_FILES:
        fpath = case_dir / filename
        if not fpath.exists():
            continue
        content = fpath.read_text(encoding="utf-8").strip()
        if not content:
            continue

        if verbose:
            print(f"  [{content_type}] {filename} ...", end=" ", flush=True)

        try:
            result = extract_entities(
                case_id=case_id,
                content=content,
                content_type=content_type,
                source_file=filename,
            )
            results["files"].append({"file": filename, **result})
            results["total_entities"] += result["entities_written"]
            results["total_relations"] += result["relations_written"]
            if verbose:
                print(f"{result['entities_written']} entities, {result['relations_written']} relations")
        except Exception as e:
            if verbose:
                print(f"ERROR: {e}")
            results["files"].append({"file": filename, "error": str(e)})

    return results


def main():
    parser = argparse.ArgumentParser(description="Ingest case entities into Neo4j")
    parser.add_argument("--case", help="Single case ID to process (default: all cases)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    verbose = not args.quiet

    if verbose:
        print("Initialising Neo4j schema...")
    init_schema()

    case_dirs = []
    if args.case:
        d = CASES_DIR / args.case
        if not d.exists():
            print(f"Case directory not found: {d}", file=sys.stderr)
            sys.exit(1)
        case_dirs = [(args.case, d)]
    else:
        case_dirs = [(p.name, p) for p in sorted(CASES_DIR.iterdir()) if p.is_dir()]

    total = {"cases": 0, "entities": 0, "relations": 0}
    for case_id, case_dir in case_dirs:
        if verbose:
            print(f"\nCase {case_id}:")
        result = ingest_case(case_id, case_dir, verbose=verbose)
        total["cases"] += 1
        total["entities"] += result["total_entities"]
        total["relations"] += result["total_relations"]

    print(f"\n✅ Done: {total['cases']} cases, {total['entities']} entities, {total['relations']} relations written to Neo4j")


if __name__ == "__main__":
    main()
