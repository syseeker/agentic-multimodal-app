# Phase 9e — Inference Benchmark

Plan, rationale and gates: **[`../deploy/PHASE9E_INFERENCE_BENCHMARK.md`](../deploy/PHASE9E_INFERENCE_BENCHMARK.md)**.
This directory holds the runnable pieces.

Scope: **VLM · MERaLiON · RAG**. Everything else Sherlock uses is a remote hosted NIM and is
recorded as an end-to-end baseline only.

| File | Runs where | What |
|---|---|---|
| `preflight.sh` | GPU box | Refuses to proceed on anything that would invalidate a run: proxy-mode VLM, wrong collection, missing tooling, nv-ingest resident |
| `build_workloads.py` | anywhere | Generates aiperf inputs from the 21-case corpus. No GPU, no network |
| `run_vlm.sh` | GPU box | Open-loop aiperf rate sweep against rtvi-vlm |
| `shim/meralion_server.py` | GPU box | OpenAI-compatible wrapper so aiperf can reach MERaLiON |
| `workloads/` | — | Generated inputs (committed: deterministic) |
| `results/<gpu>/` | — | Run artifacts (gitignored) |

## Order

```bash
python3 benchmark/build_workloads.py      # anywhere
bash benchmark/preflight.sh               # GPU box — must pass first
bash benchmark/run_vlm.sh
```

## Three things that silently produce wrong numbers

1. **rtvi-vlm in `openai-compat` mode** holds no weights and proxies to a remote endpoint —
   you would measure the internet, not the GPU. `preflight.sh` and `run_vlm.sh` both refuse.
2. **The VLM model id must come from `/v1/models`**, not from a config file. `phase5_vss.sh`
   and `vss_sherlock_mcp.py` disagree about which Cosmos model is loaded.
3. **Closed-loop load hides degradation.** Use `--request-rate`, never `--concurrency`, for
   anything involving contention.

Also note: MERaLiON only ever analyses the **first 30 s** of a recording, and all four
sample WAVs are longer. Latency will look flat regardless of input length — that is
truncation, not efficiency.
