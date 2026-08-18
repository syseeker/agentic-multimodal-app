# Quickstart — Benchmarking Sherlock (Phase 9e)

For the engineer measuring an already-deployed Sherlock on a GPU box.
To *build* Sherlock, see [QUICKSTART_DEVELOPER.md](QUICKSTART_DEVELOPER.md).
Plan, gates and rationale: [deploy/PHASE9E_INFERENCE_BENCHMARK.md](deploy/PHASE9E_INFERENCE_BENCHMARK.md).

> **Phase 9 measures. It never launches a model.** Phases 1–8 deploy the stack. If a
> service is down, `bench check` names the phase script that starts it and stops. Starting
> something from the benchmark would mean measuring a configuration nobody deployed.

---

## What gets measured

Three things run on our GPU, so three things are measured:

| Target | What it is | Driven by |
|---|---|---|
| **VLM** | Cosmos, served by **vLLM inside `vss-rtvi-vlm`** (:8018, OpenAI-compatible) | aiperf |
| **MERaLiON** | MERaLiON-3-10B behind the Phase 4 HTTP service (:8500) | aiperf |
| **RAG** | RAG Blueprint end-to-end (:8081) | `rag-perf` skill + RAGAS |

Everything else Sherlock uses — the agent LLM, embeddings, reranker, Parakeet ASR, Magpie
TTS — is a **remote hosted NIM**. Those are recorded as a wall-clock baseline only. They
include internet RTT, so they *bound* what local hosting must beat; they are not a
like-for-like comparison. Say so wherever you quote them.

## Prerequisites

- Sherlock Phases 1–8 deployed **on this machine** and healthy.
- `pip install 'aiperf>=0.10'`
- `nsys` (only for B7). `nvidia-smi` must work, or there are no GPU numbers at all.

---

## Run it

```bash
# 1. Generate workloads from the 21-case corpus. No GPU, no network — safe anywhere.
python3 benchmark/cli.py workloads

# 2. Is the stack measurable? Refuses to continue on anything that would invalidate a run.
python3 benchmark/cli.py check

# 3. See the plan without running it.
python3 benchmark/cli.py coloc --all --dry-run

# 4. Solo baselines + contention windows. --resume reuses matching baselines.
python3 benchmark/cli.py coloc --all --resume

# 5. Regenerate the report.
python3 benchmark/cli.py summary
```

Read `benchmark/results/rtx_pro6000/summary.md` — **section 4 first**. It lists what
weakens or invalidates the numbers above it.

Add `--json` to any command for a single-line machine-readable status.
Exit codes: `0` ok · `1` generic · `3` runtime · `4` missing dependency.

## The eight steps

`B1`–`B8`, defined in [deploy/PHASE9E_INFERENCE_BENCHMARK.md](deploy/PHASE9E_INFERENCE_BENCHMARK.md) §6.
(The `B` prefix is deliberate — the guardrails policy already uses `S0`–`S22` for safety
severity, and two meanings for "S3" in one repo is a trap.)

| Step | What | GPU? |
|---|---|---|
| **B1** | Pre-work: fix defects, settle which VLM is loaded | no |
| **B2** | Workload corpus from `data/cases/` | no |
| **B3** | MERaLiON HTTP service up (**a Phase 4 deliverable**) | yes |
| **B4** | Solo baselines — aiperf against VLM and MERaLiON alone | yes |
| **B5** | RAG layer — `rag-perf` stage breakdown, RAGAS quality | yes |
| **B6** | **Contention** — what co-resides on one card | yes |
| **B7** | Nsight — only on what B4–B6 flagged | yes |
| **B8** | Report + seed `knowledge.yaml` | no |

B6 is the one that matters most right now: it gates whether the remote NIMs can come local.

---

## Three ways to get wrong numbers

**1. Benchmarking a proxy.** `rtvi-vlm` has two modes. `openai-compat` loads no weights and
forwards to a remote endpoint — you would be measuring `integrate.api.nvidia.com` over the
internet, not the GPU. `check` and `coloc` both refuse, but you can confirm by hand:

```bash
docker exec vss-rtvi-vlm printenv RTVI_VLM_MODEL_TO_USE   # must NOT be openai-compat
```

**2. Trusting a config file for the model id.** `phase5_vss.sh` deploys `cosmos-reason1-7b`
while `vss_sherlock_mcp.py` asks for the `cosmos-reason2-8b` NIM name. Ask the server:

```bash
curl -s http://localhost:8018/v1/models | jq -r '.data[0].id'
```

**3. Comparing MERaLiON requests as if equal.** Its encoder caps at 30 s per forward pass,
so a 99 s recording costs 4 passes. A request is not fixed work — normalise by
`meralion.windows` in the response before comparing latencies.

## Why the results are trustworthy (or aren't)

Four rules are enforced in code. They are the difference between a contention number and a
plausible-looking number:

1. **One shared `t0`** per window, with a post-hoc overlap check. If tenants did not
   actually run concurrently, the window measured sequential execution and is **flagged**,
   not reported.
2. **Open-loop load only** (`--request-rate` + arrival pattern). Closed-loop `--concurrency`
   throttles itself when the server slows, hiding the degradation being measured.
3. **Baselines keyed on offered rate.** A 4 rps result is never divided by a 1 rps baseline.
4. **`degradation = contention / solo` computed at report time** from the manifests, so
   re-analysis can never disagree with the raw traces.

And two honesty rules:

- **p99 needs ≥ 50 successful requests.** Below that the report labels it unreliable.
- **`knowledge.yaml` fills in a cause only when it has one.** Otherwise the finding keeps
  its `[TBD]`. The harness does not invent explanations, and its seeded entries are marked
  `HYPOTHESIS` until a run replaces them.

## Housekeeping

- **Re-run `deploy/patch_vss_rtvi_vlm.sh`** after anything recreates the VSS containers —
  the rtvi-vlm patches live in the writable layer and vanish, changing behaviour mid-suite.
- **Stop nv-ingest** (`deploy/ingest_stop.sh`) before capacity runs. Idle co-running with
  VSS contends for memory and turns capacity numbers into noise.
- `benchmark/results/` is gitignored. Commit `summary.md` deliberately if you want it kept.

## Adding a target or a colocation

Everything lives in `benchmark/config/<gpu>.yaml` — nothing is hardcoded in the scripts.
Add a `targets:` entry (`serving: openai_chat` to make it aiperf-drivable) and reference it
from a `colocations:` tenant. For GB10, start a **new** `gb10.yaml`: its 128 GB is unified
memory, so VRAM headroom maths does not carry over from a discrete card.
