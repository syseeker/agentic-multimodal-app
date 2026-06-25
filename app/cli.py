"""CLI runner — drive a full case end-to-end without the UI.

    ama run --case data/generated/sample_case
    ama serve
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .models import Asset, Modality
from .orchestrator import CaseSession


def _load_case(case_dir: str) -> tuple[str, str, list[Asset]]:
    manifest = json.loads((Path(case_dir) / "manifest.json").read_text())
    assets = [
        Asset(
            asset_id=a["asset_id"],
            modality=Modality(a["modality"]),
            path=str(Path(case_dir) / a["path"]),
            label=a.get("label", ""),
        )
        for a in manifest["assets"]
    ]
    return manifest.get("case_id", Path(case_dir).name), manifest.get("objective", ""), assets


def run(args: argparse.Namespace) -> None:
    case_id, objective, assets = _load_case(args.case)
    print(f"▶ case={case_id} objective={objective!r} assets={len(assets)}")
    session = CaseSession(case_id, assets, objective)

    plan = session.make_plan()
    print(f"\n— PLAN —\n{plan.objective}")
    for s in plan.steps:
        print(f"  • {s.asset_id} [{s.modality}] {s.action}")

    if not args.yes:
        if input("\nApprove and investigate? [y/N] ").strip().lower() != "y":
            print("aborted.")
            return

    result = session.investigate()
    print(f"\n— INVESTIGATION — extractions={result['extractions']} "
          f"sentiments={result['sentiments']}")
    if session.graph:
        print(f"  graph: nodes={session.graph.nodes} edges={session.graph.edges}")
        for kp in session.graph.key_players[:3]:
            print(f"  key player: {kp}")

    report = session.finalize()
    print("\n— REPORT —")
    print(report.summary)
    print(f"citations: {report.citations}")


def serve(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run("app.server:app", host="0.0.0.0", port=args.port, reload=args.reload)


def main() -> None:
    ap = argparse.ArgumentParser(prog="ama", description="Agentic Multimodal App")
    sub = ap.add_subparsers(required=True)

    r = sub.add_parser("run", help="run a case end-to-end")
    r.add_argument("--case", required=True, help="case dir with manifest.json")
    r.add_argument("--yes", action="store_true", help="skip approval prompt")
    r.set_defaults(func=run)

    s = sub.add_parser("serve", help="start the API server")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--reload", action="store_true")
    s.set_defaults(func=serve)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
