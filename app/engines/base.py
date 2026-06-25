"""Engine protocol — what every agent engine must provide.

Keeping this minimal lets deepagents (primary) and Hermes (alt) be swapped via
config without the server/UI caring which is active.
"""
from __future__ import annotations

from typing import Protocol

from ..models import CaseReport


class Engine(Protocol):
    name: str

    def chat(self, case_id: str, message: str, history: list[dict] | None = None) -> str:
        """Free-form Q&A grounded in a (already-processed) case."""
        ...

    def reason_report(self, case_id: str, context: dict) -> CaseReport:
        """Critic phase: synthesize a cited CaseReport from collected findings."""
        ...
