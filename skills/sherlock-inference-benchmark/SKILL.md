---
name: sherlock-inference-benchmark
description: |
  Measure Sherlock's GPU inference on one card — the Cosmos VLM behind
  vss-rtvi-vlm, MERaLiON-3-10B behind its HTTP shim, and the RAG Blueprint —
  and find what they cost each other when co-resident. Use when asked how fast
  Sherlock is, whether the VLM and MERaLiON fit on one GPU, what the safe
  request rate is, where a request's time goes, or to profile a flagged
  hotspot. Phase 9e. Covers the open-loop measurement discipline, the five
  defects that made runs report silent zeros, and the two-profiler B7 recipe.
---

# sherlock-inference-benchmark

## When to invoke

- "How fast is Sherlock's video analysis / paralinguistics?"
- "Can the VLM and MERaLiON share one GPU? What does it cost?"
- "What request rate can we actually sustain?"
- "Where does MERaLiON's time go?"
- Capacity planning before moving a remote NIM on-prem.

**Do not** invoke to *deploy* anything. Phase 9 measures only; Phases 1-8 deploy.
`bench check` names the phase script for anything that is down and stops.

## Build status

**First hardware contact 2026-08-31, RTX PRO 6000 Blackwell (96 GB, x86_64).**
Three full suite attempts. The first two produced no usable contention numbers;
the third did. Five defects found, four fixed.

| # | Defect | Effect | State |
|---|---|---|---|
| 1 | aiperf resolves its tokenizer from `--model`, but the VLM's served id is an NGC NIM artifact name (`nim_<org>_<model>_<tag>`), not a HF repo | 401 -> aiperf exits before one request; `n_requests=0` | fixed: per-target `tokenizer:` |
| 2 | `parse_aiperf_records` only understood aiperf <=0.10's flat export; 0.11 writes `{metadata,metrics}` | 233 real requests parsed as 0 | fixed: both schemas |
| 3 | `coloc` calls `resolve_model()` for every tenant regardless of `serving` | the `rag_perf` tenant aborts the whole run | **open** — needs a rag_perf driver (B5). Work around with `--continue-on-error` |
| 4 | `audio_manifest.json` is a JSON array; aiperf's `single_turn` loader reads JSONL | `Invalid JSON in dataset file`; MERaLiON never driven in any window | fixed: `audio_statements.jsonl` |
| 5 | `warmup` is counted in REQUESTS, so a fixed 10 costs 441 s on a slow tenant | slow tenant still warming while the fast tenant's whole window opened and closed -> `TENANTS DID NOT OVERLAP` | fixed: `warmup_requests` per target |

Every one of these produced a run that **completed** while measuring nothing or
the wrong thing. The validity rules caught 4 and 5 rather than publishing them —
without the overlap check, `1.47x` would have been reported as a contention
result. It was not one.

## Results worth quoting (2026-08-31)

**The B6 answer.** `vlm-meralion-sustained` is the only window that passed the
overlap check, and it is the one to cite:

| Tenant | rate | throughput kept | e2e p50 | e2e p95 |
|---|---|---|---|---|
| VLM | 2 rps | ~1.00x | 0.84x | **1.12x** |
| MERaLiON | 0.045 rps | ~1.00x | ~1.00x | **1.05x** |

Co-residency is cheap when neither tenant is saturated: ~12% on VLM tail
latency, ~5% on MERaLiON, no throughput loss. **VRAM peaks at 93.2 of 96 GB**
(VLM 69.6 + MERaLiON 23.2) — they fit, with under 3 GB spare.

**Solo capacity.** VLM: 2.0-3.5 s e2e p50, 1.93 rps achieved of 2 offered, 0%
errors, 88-97% SM, ~175-190 J/req. MERaLiON: 3.8 s warm per short clip, 5.5 s
p50 / 20.6 s p95 across the workload, ~0.18 rps ceiling, 19-25% SM, 963-3271
J/req.

**MERaLiON saturates at 1 rps** — ~20x its ceiling. Achieved 0.108-0.158 rps,
driver timed out, most requests cancelled. Those windows are correctly voided.
Do not read 58-95 s p50 as service time; that is queueing.

**B7: MERaLiON is decode-bound, not preprocessing-bound.** py-spy:
`generate` 46.6% of samples, `_sample` 41.8%, gemma2 `forward` 41.7%. Top GPU
kernel is `gemvx` (matrix-VECTOR = batch-1 decode) plus tens of thousands of
tiny elementwise kernels; 6.7 s of GPU kernel time across ~19 s of driving.
The GPU sits at ~25% because HF `transformers` generates one token at a time at
batch 1 — no continuous batching, no paged attention. That, not audio decode,
is the ceiling. It also explains the collapse at 1 rps: nothing batches, so
concurrent requests queue.

## Two rules that are non-negotiable

**1. Open-loop load, always.** Drive every tenant at a fixed *request rate*,
never a fixed *concurrency* — a closed-loop client throttles itself in
proportion to the slowdown it is meant to measure. Record `offered_rps` and
`achieved_rps`; where they diverge is the safe-operating-envelope boundary.

**2. Measure the same phase.** Warmup is per-REQUEST, so a slow tenant's warmup
can outlast a fast tenant's entire measurement window. Set `warmup_requests`
per target for anything slower than a couple of seconds per request, and trust
the overlap check when it says a window is void.

## Pre-flight (do not skip)

1. **Is the VLM a proxy?** `RTVI_VLM_MODEL_TO_USE=openai-compat` loads no
   weights and forwards to a remote endpoint — you would be benchmarking
   `integrate.api.nvidia.com` over the internet. On this host the env var is not
   in the container env at all, so check the two signals that do work:
   `curl -s localhost:8018/v1/models` must return the **local NIM id**
   (`nim_...`), not the friendly remote name, and the GPU must show ~69 GB
   resident.
2. **Never trust a config file for the model id** — `phase5_vss.sh` deploys
   `cosmos-reason1-7b` while `vss_sherlock_mcp.py` asks for the reason2-8b NIM
   name. Ask the server.
3. **Gated HF repos.** `nvidia/Cosmos-Reason2-8B` and `MERaLiON/MERaLiON-3-10B`
   are both gated. A valid token is not enough — the *account* must be granted
   access, and a 403 says "not in the authorized list", not "bad credentials".
   Request access on each model page; approval was instant for an @nvidia
   account.
4. **MERaLiON must be up** (`:8500`) — a Phase 4 deliverable, not benchmark
   scaffolding. `bench` will not start it.
5. **Stop nv-ingest** (`deploy/ingest_stop.sh`) before capacity runs; idle
   co-running with VSS turns capacity numbers into noise.
6. **Re-apply `patch_vss_rtvi_vlm.sh`** after anything recreates the VSS
   containers — the patches live in the writable layer and change behaviour
   mid-suite if lost.
7. **A request is not fixed work.** MERaLiON's encoder caps at 30 s per forward
   pass, so a 99 s clip costs 4 passes. Normalise by `meralion_windows` from
   `audio_manifest.json` before comparing latencies.

## Failure recovery

| Symptom | Cause | Action |
|---|---|---|
| `n_requests=0` but the window "completed" | aiperf died at configure time | Read `<run>/<tenant>.driver.log` — it quotes the real error. Usually tokenizer (defect 1) or dataset format (defect 4) |
| A tenant has records but the manifest says 0 | export-schema mismatch (defect 2) | Check `profile_export.jsonl`'s shape against `parse_aiperf_records` |
| `TENANTS DID NOT OVERLAP` | phases did not coincide — usually warmup asymmetry (defect 5) | Lower `warmup_requests` on the slow tenant; do not report the ratios |
| `driver timed out and was killed` | offered rate far above capacity; `coloc` waits `max(120, duration*3)` | Lower the rate to the measured ceiling, or accept it as an overload result |
| `achieved << offered` | past the safe envelope | That IS the finding. Report the ceiling |
| `p99 unreliable (<50 requests)` | inherent at low rates | Cite p50/p95, or lengthen `duration_s` |
| Guard refuses to profile | a coloc run is live, or <24 GB VRAM free | Wait, or stop the `:8500` shim. Never run both — the card has ~2.5 GB spare and the host has no swap |

## B7 — profiling

`bash benchmark/nsight/profile_meralion.sh [n_requests] [both|nsys|pyspy]`

**Why MERaLiON and not the VLM.** B7 profiles only what B4-B6 flagged; the VLM
at 2.5 s / 90% SM is not the bottleneck. There is also a hard constraint:
**Nsight profiles what it launches and cannot attach to a running process**, so
profiling the VLM would mean restarting `vss-rtvi-vlm`, which discards its
writable-layer patches. py-spy launches too, because `ptrace_scope=1` permits
tracing descendants only — `py-spy dump --pid <server>` fails with "Permission
Denied" while `py-spy record -- <cmd>` needs no privilege at all.

**nsys without a download or sudo** — the VSS container ships it:
```bash
docker cp vss-rtvi-vlm:/usr/local/cuda-13.0/NsightSystems-cli-2025.5.1 ~/.local/opt/
ln -sf ~/.local/opt/NsightSystems-cli-2025.5.1/target-linux-x64/nsys ~/.local/bin/nsys
```
**CPU sampling needs `kernel.perf_event_paranoid <= 2`** (Ubuntu ships 4). The
script reads the live value and adapts rather than hardcoding either way:
`sudo sysctl -w kernel.perf_event_paranoid=2`.

## Verification

- **Null test** — a single-tenant "colocation" must give ratio ~1.0.
- **Load fidelity** — `achieved_rps ~= offered_rps` at low load.
- **Overlap** — a contention window with no overlap is void, not a result.
- **Read section 4 of `summary.md` first.** Everything above it is only as good
  as the flags below it.

## Pinned references

- [deploy/PHASE9E_INFERENCE_BENCHMARK.md](../../deploy/PHASE9E_INFERENCE_BENCHMARK.md) — the plan, the B1-B8 gates, and §10 the run record
- [QUICKSTART_BENCHMARK.md](../../QUICKSTART_BENCHMARK.md) — step-by-step walkthrough
- `benchmark/README.md` — harness internals
- `benchmark/config/rtx_pro6000.yaml` — targets, workloads, colocations. Nothing is hardcoded in the scripts. For GB10 start a **new** `gb10.yaml`: 128 GB unified memory, so VRAM headroom maths does not carry over
