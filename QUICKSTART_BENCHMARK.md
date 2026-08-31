# Quickstart — Benchmarking Sherlock (Phase 9e)

You'll measure what Sherlock's GPU work actually costs — the Cosmos VLM, MERaLiON, and
how much they slow each other down sharing one card — by running eight steps, with the
agent prompt shown alongside every command.

**First real number in about 15 minutes. The full suite is ~60.**

> **Phase 9 measures. It never launches a model.** Phases 1-8 deploy the stack. If a
> service is down, `bench check` names the phase script that starts it and stops. Starting
> something from the benchmark would mean measuring a configuration nobody deployed.

> **This has been run.** 2026-08-31, RTX PRO 6000 Blackwell, three suite attempts, five
> defects found. If something here fails it is more likely a setup difference than an
> untested path — the run record and every root cause are in
> [deploy/PHASE9E_INFERENCE_BENCHMARK.md](deploy/PHASE9E_INFERENCE_BENCHMARK.md) §10.

---

## Prerequisites

- Sherlock Phases 1-8 deployed **on this machine** and healthy (`bash deploy/start_all.sh`).
- 1x NVIDIA GPU. Written against RTX PRO 6000 Blackwell (96 GB). **GB10 needs its own
  `gb10.yaml`** — 128 GB unified memory, so headroom maths does not carry over.
- `python>=3.10`, `uv`, `curl`, and a `.env` with `NVIDIA_API_KEY` and `HF_TOKEN`.
- **HuggingFace access to two gated repos** (Step 1 checks). A valid token is not enough:
  the account must be *granted* access.
- One of: Claude Code / Codex / Cursor, if you want to drive this by prompt.

---

## Step 1 — Prerequisites and gated model access

> **Prompt:** *"Install aiperf, then check whether my HF token can read
> nvidia/Cosmos-Reason2-8B and MERaLiON/MERaLiON-3-10B."*

```bash
pip install --user 'aiperf>=0.10'

# Both repos are GATED. 403 means "not in the authorized list" -- an ACCESS problem, not a
# credentials problem, and no amount of re-issuing tokens fixes it.
TOK=$(grep -m1 '^HF_TOKEN=' .env | cut -d= -f2- | tr -d '[:space:]')
for m in nvidia/Cosmos-Reason2-8B MERaLiON/MERaLiON-3-10B; do
  printf '%-32s %s\n' "$m" \
    "$(curl -sL -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $TOK" \
       https://huggingface.co/$m/resolve/main/tokenizer_config.json)"
done   # want 200 200
```

If either is 403, open the model page as that account and request access. It was **instant**
for an @nvidia account. aiperf needs these for token counting; without them a run reports
`n_requests=0` and looks like a broken endpoint.

## Step 2 — Start MERaLiON (a Phase 4 deliverable)

> **Prompt:** *"Start the MERaLiON HTTP shim on 8500 and wait for it to be ready."*

```bash
HF_TOKEN=... uv run data/audio/meralion_server.py --port 8500 &
curl -sf localhost:8500/v1/health/ready     # ~45 s to load, ~23 GB VRAM
```

`bench` will not start this for you. It exists for production reasons (MERaLiON otherwise
loads in-process and cannot be shared); the benchmark just happens to need it reachable.

## Step 3 — Confirm the stack is measurable

> **Prompt:** *"Run bench check and fix whatever it names."*

```bash
python3 benchmark/cli.py check      # want: 3 target(s) measurable
```

It refuses on anything that would invalidate a run — a missing dependency, a target that is
down, or a VLM in proxy mode. **Verify the VLM is serving local weights**, because a proxy
would have you benchmarking NVIDIA's cloud over the internet:

```bash
curl -s localhost:8018/v1/models | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"][0]["id"])'
# want the LOCAL NIM id: nim_nvidia_cosmos-reason2-8b_hf-1208   (not nvidia/cosmos-reason2-8b)
nvidia-smi --query-gpu=memory.used --format=csv,noheader   # ~69 GB resident = weights are here
```

Never trust a config file for this: `phase5_vss.sh` deploys `cosmos-reason1-7b` while
`vss_sherlock_mcp.py` asks for the reason2-8b NIM name. Ask the server.

## Step 4 — Build the workloads

> **Prompt:** *"Regenerate the benchmark workloads from the case corpus."*

```bash
python3 benchmark/cli.py workloads
# cases: 21 | rag_queries: 105 | vlm_video: 6 over 2 videos | audio_statements: 8 over 4 wavs
```

No GPU, no network — safe anywhere. Everything is generated from `data/cases/`, so the
questions are the ones investigators actually ask.

## Step 5 — Free the box, then dry-run

> **Prompt:** *"Stop nv-ingest and dry-run the colocation plan."*

```bash
bash deploy/ingest_stop.sh                       # ~10 GB RAM back; idle nv-ingest is noise
python3 benchmark/cli.py coloc --all --dry-run   # resolves the plan, launches nothing
```

## Step 6 — One window end-to-end

> **Prompt:** *"Run just vlm-solo and show me n_ok and the p50."*

```bash
python3 benchmark/cli.py coloc --colocation vlm-solo
```

**Check `n_ok` before believing anything.** A window can report "completed" having sent zero
requests — that was defect 1 and defect 4. Expect ~230 requests, 0% errors, e2e p50 ~2.5 s.

## Step 7 — The full suite

> **Prompt:** *"Run the whole colocation suite and tell me which windows are valid."*

```bash
python3 benchmark/cli.py coloc --all --continue-on-error
```

~60 minutes. `--continue-on-error` is required today: the `vlm-meralion-rag` window names a
`rag_perf` tenant that `coloc` cannot drive yet (defect 3, B5 work), and without the flag
that one failure aborts everything. Add `--resume` to reuse solo baselines — they are about
half the runtime.

## Step 8 — Read the report, then profile what it flags

> **Prompt:** *"Read section 4 of summary.md first, then tell me which numbers survive."*

```bash
$EDITOR benchmark/results/rtx_pro6000/summary.md    # SECTION 4 FIRST
bash benchmark/nsight/profile_meralion.sh 5 both    # B7: nsys + py-spy
```

Section 4 lists everything that weakens or voids a number above it. A window flagged
`TENANTS DID NOT OVERLAP` measured sequential execution — its ratios are not results.

B7 **replaces** the running shim rather than running beside it: the card sits at ~95 of
96 GB and the host has no swap, so a second 23 GB instance would OOM the box. The script
guards against that, and against profiling while a suite is running.

---

## Three ways to get wrong numbers

1. **Benchmarking a proxy.** See Step 3. In `openai-compat` mode rtvi-vlm loads no weights.
2. **Trusting a config file for the model id.** Ask `/v1/models`.
3. **Comparing MERaLiON requests as if equal.** Its encoder caps at 30 s per forward pass,
   so a 99 s clip costs 4 passes. Normalise by `meralion_windows` in `audio_manifest.json`.

## Why the results are trustworthy (or aren't)

Enforced in code:

1. **One shared `t0`** per window with a post-hoc overlap check. Tenants that did not
   actually run concurrently are **flagged, not reported**.
2. **Open-loop only** (`--request-rate`). Closed-loop concurrency throttles itself when the
   server slows, hiding the degradation being measured.
3. **Baselines keyed on offered rate** — a 4 rps result is never divided by a 1 rps baseline.
4. **Ratios computed at report time** from the manifests, so re-analysis cannot disagree
   with the raw traces.

And two honesty rules: **p99 needs >=50 successful requests** or it is labelled unreliable,
and **`knowledge.yaml` supplies a cause only when it has one** — otherwise the finding keeps
its `[TBD]` rather than inventing an explanation.

## Cheat sheet — when something looks wrong

| Symptom | Look at |
|---|---|
| `n_requests=0`, window "completed" | `<run>/<tenant>.driver.log` — aiperf's real error |
| Records exist but manifest says 0 | export-schema mismatch in `parse_aiperf_records` |
| `TENANTS DID NOT OVERLAP` | warmup asymmetry — lower `warmup_requests` on the slow tenant |
| `driver timed out and was killed` | offered rate far above capacity |
| `achieved << offered` | that IS the finding: you found the ceiling |
| B7 refuses to start | a suite is running, or <24 GB VRAM free |

## What this does not cover

- **B5, the RAG layer** (`rag-perf` speed + RAGAS quality) — blocked on a `rag_perf` driver.
- **Remote NIMs** (agent LLM, embeddings, reranker, Parakeet, Magpie) — wall-clock baseline
  only. They include internet RTT, so they *bound* what local hosting must beat rather than
  comparing like for like. Label them that way wherever you quote them.
- **GB10.** Write a new `gb10.yaml`; do not copy the discrete-memory one.

## Adding a target or a colocation

Everything lives in `benchmark/config/<gpu>.yaml` — nothing is hardcoded in the scripts. Add
a `targets:` entry (`serving: openai_chat` to make it aiperf-drivable, plus `tokenizer:` if
the served model id is not a HF repo, and `warmup_requests:` if it is slow) and reference it
from a `colocations:` tenant.
