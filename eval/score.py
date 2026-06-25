"""Standalone evaluation: entity F1, key-player accuracy, citation coverage.

Two modes:
  --report report.json   score a previously produced CaseReport JSON (offline)
  --run    data/sample_case   run the case live, then score (needs servers up)

Complements NeMo Agent Toolkit's RAGAS/LLM-as-judge (observability/nat-config.yml);
this scorer is dependency-light and checks structured-extraction accuracy.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _norm(s: str) -> str:
    return s.strip().lower().replace(" ", "-")


def entity_f1(pred_ids: list[str], gold_ids: list[str]) -> dict:
    pred = {_norm(x) for x in pred_ids}
    gold = {_norm(x) for x in gold_ids}
    tp = len(pred & gold)
    precision = tp / len(pred) if pred else 0.0
    recall = tp / len(gold) if gold else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3)}


def citation_coverage(report: dict) -> float:
    rels = report.get("relationships", [])
    if not rels:
        return 0.0
    cited = sum(1 for r in rels if r.get("source"))
    return round(cited / len(rels), 3)


def score(report: dict, gold: dict) -> dict:
    pred_entities = [e["id"] for e in report.get("entities", [])]
    kp = report.get("graph", {}).get("key_players", [])
    pred_kp = _norm(kp[0]["id"]) if kp else ""
    return {
        "entity": entity_f1(pred_entities, gold["entities"]),
        "key_player_correct": pred_kp == _norm(gold["key_player"]),
        "citation_coverage": citation_coverage(report),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", help="CaseReport JSON to score")
    ap.add_argument("--run", help="case dir to run live, then score")
    ap.add_argument("--gold", default="eval/ground_truth.json")
    args = ap.parse_args()

    gold = json.loads(Path(args.gold).read_text())

    if args.run:
        from app.cli import _load_case
        from app.orchestrator import CaseSession

        cid, obj, assets = _load_case(args.run)
        session = CaseSession(cid, assets, obj)
        session.investigate()
        report = session.finalize().model_dump()
    elif args.report:
        report = json.loads(Path(args.report).read_text())
    else:
        raise SystemExit("provide --report or --run")

    print(json.dumps(score(report, gold), indent=2))


if __name__ == "__main__":
    main()
