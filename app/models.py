"""Structured schemas shared by every tool.

Tools return these (not free text) so outputs are verifiable, citable, and
loadable into the graph. Every claim carries a `source` for accountability.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Modality(str, Enum):
    text = "text"
    image = "image"
    audio = "audio"


class EntityType(str, Enum):
    person = "person"
    organization = "organization"
    location = "location"
    phone = "phone"
    account = "account"          # bank / crypto / social
    money = "money"
    datetime = "datetime"
    item = "item"               #物品 / device / weapon / drug etc.
    event = "event"
    other = "other"


class Entity(BaseModel):
    id: str = Field(..., description="stable slug, e.g. person:john-tan")
    name: str
    type: EntityType
    aliases: list[str] = Field(default_factory=list)
    source: str = Field(..., description="asset id / locator the entity came from")
    confidence: float = Field(0.8, ge=0.0, le=1.0)


class Relationship(BaseModel):
    source_id: str = Field(..., description="entity id (subject)")
    target_id: str = Field(..., description="entity id (object)")
    relation: str = Field(..., description="verb phrase, e.g. 'transferred_money_to'")
    evidence: str = Field(..., description="quote/snippet supporting the relation")
    source: str = Field(..., description="asset id the evidence came from")
    confidence: float = Field(0.7, ge=0.0, le=1.0)


class ExtractionResult(BaseModel):
    """Output of any *-extract tool."""
    modality: Modality
    asset_id: str
    entities: list[Entity] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    summary: str = ""


class TranscriptSegment(BaseModel):
    start: float = 0.0
    end: float = 0.0
    speaker: str = "unknown"
    text: str = ""
    # Paralinguistics from MERaLiON
    emotion: str | None = None
    tone: str | None = None


class TranscriptResult(BaseModel):
    asset_id: str
    language: str = "en"
    segments: list[TranscriptSegment] = Field(default_factory=list)
    full_text: str = ""


class SentimentResult(BaseModel):
    asset_id: str
    modality: Modality
    label: Literal["positive", "neutral", "negative", "mixed"] = "neutral"
    score: float = Field(0.0, ge=-1.0, le=1.0)
    paralinguistic: dict[str, str] = Field(
        default_factory=dict,
        description="e.g. {'tone':'tense','rhythm':'rushed','emotion':'fearful'}",
    )
    rationale: str = ""
    source: str = ""


class GraphStats(BaseModel):
    nodes: int = 0
    edges: int = 0
    key_players: list[dict] = Field(
        default_factory=list, description="cuGraph centrality ranking"
    )
    communities: list[dict] = Field(
        default_factory=list, description="cuGraph community detection clusters"
    )


class Asset(BaseModel):
    asset_id: str
    modality: Modality
    path: str
    label: str = ""


class CaseReport(BaseModel):
    case_id: str
    summary: str
    entities: list[Entity] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    sentiments: list[SentimentResult] = Field(default_factory=list)
    graph: GraphStats = Field(default_factory=GraphStats)
    citations: list[str] = Field(default_factory=list)
