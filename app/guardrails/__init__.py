"""NeMo Guardrails wiring (P1).

apply_rails() wraps any LangChain runnable (e.g. the deepagents engine's model)
with the input/dialog/output rails defined in config.yml + policy.co. No-op-safe:
returns the runnable unchanged if nemoguardrails isn't installed, so the app runs
without the optional dependency.
"""
from __future__ import annotations

from pathlib import Path

_CONFIG_DIR = Path(__file__).parent


def apply_rails(runnable):
    try:
        from nemoguardrails import RailsConfig
        from nemoguardrails.integrations.langchain.runnable_rails import RunnableRails
    except ImportError:
        return runnable
    config = RailsConfig.from_path(str(_CONFIG_DIR))
    return RunnableRails(config) | runnable


def check_citation_present(text: str) -> bool:
    """Custom action used by the 'check citations' rail (heuristic).

    A claim is considered cited if it references an asset id pattern like
    'wa-1' or 'asset:'. Replace with a stricter check as needed.
    """
    import re

    return bool(re.search(r"\b[a-z]+-[a-z0-9]+\b|asset:", text, re.IGNORECASE))
