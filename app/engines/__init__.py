"""Swappable agent engines. Selected by AGENT_ENGINE (deepagents | hermes)."""
from __future__ import annotations

from ..settings import get_settings
from .base import Engine


def get_engine(name: str | None = None) -> Engine:
    name = name or get_settings().agent_engine
    if name == "deepagents":
        from .deepagents_engine import DeepAgentsEngine

        return DeepAgentsEngine()
    if name == "hermes":
        from .hermes_engine import HermesEngine

        return HermesEngine()
    raise ValueError(f"unknown engine: {name}")
