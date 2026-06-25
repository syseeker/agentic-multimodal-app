"""Investigation orchestrator — Planner → Investigator → Critic.

This is the AI-Q deep-research pattern applied to forensics. It is deliberately
phase-explicit (not a single autonomous loop) so the UI can insert a human
approval gate between phases — the legal-accountability "middle ground".

Phases:
  1. plan()        Planner decides which assets to process and why.
  2. investigate() Investigator runs extraction + sentiment per approved asset,
                   then builds the graph and indexes for RAG.
  3. finalize()    Critic (engine.reason_report) synthesizes a cited CaseReport.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from .engines import get_engine
from .llm import structured_complete, text_client
from .models import Asset, CaseReport, ExtractionResult, SentimentResult
from .tools import asset_sentiment, build_graph, index_documents, ingest_asset


class PlanStep(BaseModel):
    asset_id: str
    modality: str
    action: str = Field(..., description="e.g. 'extract entities + sentiment'")
    rationale: str = ""


class Plan(BaseModel):
    case_id: str
    objective: str
    steps: list[PlanStep] = Field(default_factory=list)
    requires_approval: bool = True


_PLANNER_SYSTEM = (
    "You are the Planner of a forensic investigation agent. Given a case objective "
    "and a list of available assets (with modality), produce a plan of which assets "
    "to process and why. Prefer assets most likely to surface entities and "
    "relationships relevant to the objective. One PlanStep per asset you choose."
)


class CaseSession:
    """In-memory state for one case run (held by the server keyed by case_id)."""

    def __init__(self, case_id: str, assets: list[Asset], objective: str):
        self.case_id = case_id
        self.assets = {a.asset_id: a for a in assets}
        self.objective = objective
        self.plan: Plan | None = None
        self.extractions: list[ExtractionResult] = []
        self.sentiments: list[SentimentResult] = []
        self.graph = None
        self.report: CaseReport | None = None
        self.log: list[dict] = []

    # ── Phase 1 ────────────────────────────────────────────────────────────
    def make_plan(self) -> Plan:
        client, model = text_client()
        catalog = [
            {"asset_id": a.asset_id, "modality": a.modality.value, "label": a.label}
            for a in self.assets.values()
        ]
        messages = [
            {"role": "system", "content": _PLANNER_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"case_id: {self.case_id}\nobjective: {self.objective}\n"
                    f"assets: {catalog}\n\nReturn a Plan."
                ),
            },
        ]
        plan = structured_complete(client, model, messages, Plan, max_tokens=1536)
        plan.case_id = self.case_id
        self.plan = plan
        self._record("plan", "Plan produced", {"steps": len(plan.steps)})
        return plan

    # ── Phase 2 ────────────────────────────────────────────────────────────
    def investigate(self, approved_asset_ids: list[str] | None = None) -> dict:
        """Process approved assets. If None, process every planned asset."""
        if self.plan is None:
            self.make_plan()
        targets = approved_asset_ids or [s.asset_id for s in self.plan.steps]
        for aid in targets:
            asset = self.assets.get(aid)
            if not asset:
                continue
            ex = ingest_asset(asset)
            self.extractions.append(ex)
            self._record("extract", f"Extracted {aid}",
                         {"entities": len(ex.entities), "relationships": len(ex.relationships)})
            sent = asset_sentiment(asset)
            self.sentiments.append(sent)
            self._record("sentiment", f"Sentiment {aid}",
                         {"label": sent.label, "score": sent.score})

        self.graph = build_graph(self.case_id, self.extractions)
        index_documents(self.case_id, self.extractions)
        self._record("graph", "Graph built + indexed",
                     {"nodes": self.graph.nodes, "edges": self.graph.edges,
                      "engine": "see analytics"})
        return {
            "extractions": len(self.extractions),
            "sentiments": len(self.sentiments),
            "graph": self.graph.model_dump() if self.graph else None,
        }

    # ── Phase 3 ────────────────────────────────────────────────────────────
    def finalize(self) -> CaseReport:
        context = {
            "objective": self.objective,
            "entities": [e.model_dump() for ex in self.extractions for e in ex.entities],
            "relationships": [
                r.model_dump() for ex in self.extractions for r in ex.relationships
            ],
            "sentiments": [s.model_dump() for s in self.sentiments],
            "graph": self.graph.model_dump() if self.graph else {},
        }
        report = get_engine().reason_report(self.case_id, context)
        # Ground the report's graph in what we actually computed.
        if self.graph:
            report.graph = self.graph
        self.report = report
        self._record("report", "Critic synthesized report",
                     {"citations": len(report.citations)})
        return report

    def _record(self, phase: str, message: str, detail: dict) -> None:
        self.log.append({"phase": phase, "message": message, "detail": detail})
