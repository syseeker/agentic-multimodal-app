"""Alt engine — Hermes / NemoClaw harness (P1).

Swappable drop-in for DeepAgentsEngine, selected by AGENT_ENGINE=hermes. The
harness runs as a separate service; this adapter speaks to it. Kept as a thin
stub until P1 so the engine interface is exercised early.
"""
from __future__ import annotations

from ..models import CaseReport


class HermesEngine:
    name = "hermes"

    def __init__(self):
        raise NotImplementedError(
            "Hermes engine lands in P1. Set AGENT_ENGINE=deepagents for now. "
            "The adapter will call the Hermes/NemoClaw harness service and map "
            "its output to the same Engine protocol."
        )

    def chat(self, case_id: str, message: str, history=None) -> str:  # pragma: no cover
        ...

    def reason_report(self, case_id: str, context: dict) -> CaseReport:  # pragma: no cover
        ...
