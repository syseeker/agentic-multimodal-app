# Example run — RTX PRO 6000 Blackwell, 2026-08-31

A real Phase 9e run, committed so the artifact shapes are visible without a GPU.
**This directory is a snapshot and is never written to by the harness** — live runs go to
`benchmark/results/<gpu>/`, which is gitignored. Nothing here is overwritten by a re-run,
and nothing here is GB10-specific.

## Why only these files

The full run was **617 MB**. Excluded deliberately:

| Excluded | Size | Why |
|---|---|---|
| `meralion-5req.sqlite` | 180 MB | regenerated from the `.nsys-rep` on demand |
| `meralion-5req.nsys-rep` | 68 MB | binary trace; open locally with the Nsight GUI |
| `*/meralion.aiperf/inputs.json` | 47 MB **× 5** | aiperf base64-inlines the audio into every run's inputs |
| `*.ndjson`, aiperf logs | 37–187 KB each | per-request traces; the manifests carry the aggregates |

Kept: `summary.md` (the report), one `manifest.json` per run (every metric the report is
computed from), each tenant's `.cmd` (the exact aiperf invocation), and the py-spy
flamegraph (open the `.svg` in a browser).

## What this run shows

- **`vlm-meralion-sustained` is the only window that passed the overlap check.** Compare its
  manifest with `vlm-meralion`'s: same pair, MERaLiON at 0.045 rps instead of 1, and the
  difference between a valid envelope and a saturated neighbour.
- Co-residency cost at sustainable rates: VLM **1.12×** e2e p95, MERaLiON **1.05×**,
  throughput unchanged, VRAM peak **93.2 of 96 GB**.
- The `.cmd` files show the two settings that made runs work at all: `--tokenizer` (the
  served model id is an NGC NIM name, not a HF repo) and the per-target warmup.
- The flamegraph shows MERaLiON is decode-bound — `generate` 46.6% of samples, batch-1
  `gemvx` kernels — not preprocessing-bound.

**Read `summary.md` §4 first.** Two windows here are correctly voided; their ratios are not
results. Full narrative: `deploy/PHASE9E_INFERENCE_BENCHMARK.md` §10.
