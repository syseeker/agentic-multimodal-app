"""Eval scorer pure-function checks (offline)."""
import json
from pathlib import Path

from eval.score import citation_coverage, entity_f1, score


def test_entity_f1_perfect():
    r = entity_f1(["person:john", "account:dbs"], ["person:john", "account:dbs"])
    assert r["f1"] == 1.0


def test_entity_f1_partial():
    r = entity_f1(["person:john", "person:x"], ["person:john", "account:dbs"])
    assert 0.0 < r["f1"] < 1.0


def test_citation_coverage():
    report = {"relationships": [{"source": "wa-1"}, {"source": ""}]}
    assert citation_coverage(report) == 0.5


def test_score_against_ground_truth():
    gold = json.loads(Path("eval/ground_truth.json").read_text())
    report = {
        "entities": [{"id": e} for e in gold["entities"]],
        "relationships": [{"source": "wa-1"}],
        "graph": {"key_players": [{"id": gold["key_player"]}]},
    }
    out = score(report, gold)
    assert out["entity"]["f1"] == 1.0
    assert out["key_player_correct"] is True
