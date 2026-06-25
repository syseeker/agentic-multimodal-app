# eval/ — accuracy evaluation (P1)

Dependency-light scorer for structured-extraction quality, complementing the
RAGAS / LLM-as-judge metrics in [`../observability/nat-config.yml`](../observability/nat-config.yml).

```bash
# score a produced report
python eval/score.py --report report.json

# run the sample case live, then score (servers must be up)
python eval/score.py --run data/sample_case
```

Metrics: entity precision/recall/F1, key-player accuracy (cuGraph centrality vs
ground truth), and citation coverage. Ground truth: [`ground_truth.json`](ground_truth.json).
