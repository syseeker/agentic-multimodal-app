"""Observability entrypoint — see app/tracing.py for the implementation.

The tracing setup ships inside the `app` package (app/tracing.py) so it is
available in the app container. This module re-exports it for discoverability.

    from app.tracing import setup_tracing
    setup_tracing()
"""
from app.tracing import setup_tracing  # noqa: F401
