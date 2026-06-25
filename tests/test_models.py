"""Schema invariants the tools rely on."""
from app.models import (
    CaseReport,
    Entity,
    EntityType,
    ExtractionResult,
    Modality,
    Relationship,
    SentimentResult,
)


def test_extraction_roundtrip():
    ex = ExtractionResult(
        modality=Modality.text,
        asset_id="wa-1",
        entities=[Entity(id="person:john", name="John", type=EntityType.person, source="wa-1")],
        relationships=[
            Relationship(
                source_id="person:john", target_id="person:mei",
                relation="transferred_money_to", evidence="send 25k", source="wa-1",
            )
        ],
        summary="ok",
    )
    blob = ex.model_dump_json()
    back = ExtractionResult.model_validate_json(blob)
    assert back.entities[0].id == "person:john"
    assert back.relationships[0].relation == "transferred_money_to"


def test_sentiment_bounds():
    s = SentimentResult(asset_id="a", modality=Modality.audio, label="negative", score=-0.8)
    assert -1.0 <= s.score <= 1.0


def test_case_report_defaults():
    r = CaseReport(case_id="c1", summary="s")
    assert r.graph.nodes == 0
    assert r.citations == []
