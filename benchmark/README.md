# Phase 9e — Sherlock inference benchmark

Plan and gates: **[`../deploy/PHASE9E_INFERENCE_BENCHMARK.md`](../deploy/PHASE9E_INFERENCE_BENCHMARK.md)**

**Phase 9 measures; it never launches.** Phases 1–8 deploy every service here. If one is
down, `bench check` names the phase script that brings it up and stops — starting it here
would mean benchmarking a configuration nobody deployed.

Targets: **VLM** (Cosmos on vLLM inside rtvi-vlm) · **MERaLiON** (behind the Phase 4 HTTP
service) · **RAG** (via the `rag-perf` skill). Everything else Sherlock uses is a remote
hosted NIM, baselined end-to-end only.

## Usage

```bash
python3 benchmark/cli.py workloads                       # anywhere — no GPU, no network
python3 benchmark/cli.py check                           # GPU box: is the stack measurable?
python3 benchmark/cli.py coloc --all --dry-run           # show the plan
python3 benchmark/cli.py coloc --colocation vlm-meralion --resume
python3 benchmark/cli.py summary
```

Every command takes `--json` and then prints exactly one status line to stdout, so an agent
can branch on it. Exit codes: `0` ok · `1` generic · `3` runtime · `4` missing dependency.

Requires `pip install 'aiperf>=0.10'` on the GPU box.

## Layout

| File | What |
|---|---|
| `cli.py` | `bench` entry point — check / workloads / coloc / summary |
| `config/rtx_pro6000.yaml` | targets, workloads, colocations, thresholds. Nothing is hardcoded elsewhere |
| `lib.py` | contracts: open-loop aiperf builder, `solo_key`, `TenantResult`, overlap check |
| `coloc.py` | contention orchestrator — shared `t0`, solo baselines, manifests |
| `summary.py` | `results/<gpu>/summary.md` — degradation table + validity flags |
| `probes/gpu_sampler.py` | VRAM / SM% / power → J/req |
| `build_workloads.py` | generates inputs from the 21-case corpus |
| `knowledge.yaml` | `(gpu, target, symptom) → why / how_to_improve`; no match keeps `[TBD]` |
| `results/<gpu>/` | manifests, ndjson traces, summary.md (gitignored) |

The MERaLiON HTTP service lives at `data/audio/meralion_server.py` — it is Phase 4
infrastructure, not part of this directory.

## Four rules that make the numbers mean anything

Borrowed from `inference-pipeline-benchmark`; everything else was dropped as unnecessary
for three HTTP targets on one card.

1. **One shared `t0`**, with a post-hoc overlap check. A window where tenants did not
   actually run concurrently measured sequential execution — it is flagged, not reported.
2. **Open-loop load only** (`--request-rate` + arrival pattern). Closed-loop `--concurrency`
   throttles itself when the server slows, concealing the degradation being measured.
3. **`solo_key` includes the offered rate.** Dividing a 4 rps result by a 1 rps baseline
   invents degradation that is not there.
4. **`degradation = contention / solo`, computed at analysis time** from the manifests, so
   a re-analysis can never disagree with the raw traces.

## Two traps that silently produce wrong numbers

- **rtvi-vlm in `openai-compat` mode** holds no weights and proxies to a remote endpoint —
  you would measure the internet. `check` and `coloc` both refuse (`require_env` in the YAML).
- **The VLM model id must come from `/v1/models`**, never a config file: `phase5_vss.sh` and
  `vss_sherlock_mcp.py` disagree about which Cosmos model is loaded.

Also: a MERaLiON request is **not fixed work** — the encoder caps at 30 s per pass, so the
99 s sample costs 4 passes. Normalise by `meralion.windows` before comparing.
