"""OpenTelemetry tracing setup (exports to on-prem Phoenix). P1.

No-op unless ENABLE_TRACING=true. Instruments LangChain/LangGraph (deepagents)
so tool calls, LLM calls, token counts and TTFT land in Phoenix. NeMo Agent
Toolkit (`nat`) can consume the same OTLP stream. See observability/.
"""
from __future__ import annotations

from .settings import get_settings


def setup_tracing(service_name: str = "agentic-multimodal-app") -> bool:
    if not get_settings().enable_tracing:
        return False
    try:
        from openinference.instrumentation.langchain import LangChainInstrumentor
        from phoenix.otel import register
    except ImportError:
        print("[obs] tracing deps missing; install .[obs]. Skipping.")
        return False

    provider = register(
        project_name=service_name,
        endpoint=get_settings().otel_exporter_otlp_endpoint,
    )
    LangChainInstrumentor().instrument(tracer_provider=provider)
    print("[obs] tracing enabled")
    return True
