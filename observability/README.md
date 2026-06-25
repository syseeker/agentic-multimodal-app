# observability/ — tracing, token accounting, evaluation (P1)

The Phase-1 non-agentic deliverable: see exactly what the agent and the models do.

## What you get
- **Tracing → Phoenix (on-prem):** every tool call, LLM call, token in/out and
  TTFT, via OpenInference instrumentation. Impl: [`app/tracing.py`](../app/tracing.py).
- **NeMo Agent Toolkit (`nat`):** framework-agnostic eval (LLM-as-judge + RAGAS),
  profiling, and OTLP export. Config: [`nat-config.yml`](nat-config.yml).

## Run

```bash
# 1. start Phoenix alongside the stack
docker compose -f docker-compose.yml -f observability/compose.phoenix.yml up -d
# 2. enable tracing
echo "ENABLE_TRACING=true" >> .env && docker compose restart app
# 3. drive a case, then open Phoenix
open http://localhost:6006
```

## Evaluation
```bash
pip install nvidia-nat[all]
nat eval --config observability/nat-config.yml
```
Metrics: RAG accuracy (RAGAS), entity F1 vs the sample-case ground truth, and
citation coverage. See also [`../eval/`](../eval/) for the standalone scorer.
