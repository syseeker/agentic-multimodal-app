# Phase 9e — Inference Benchmark (RAG · VLM · MERaLiON)

Part of Phase 9. Closes TODO.md Track 2c (Nsight + aiperf) and Track 3a (benchmarking).
Target hardware: **RTX Pro 6000 Blackwell (x86_64, 96 GB)** first; GB10 second.

Runbook: **[QUICKSTART_BENCHMARK.md](../QUICKSTART_BENCHMARK.md)**.
Companion harness: `benchmark/` (see its README). Results land in
`benchmark/results/<gpu>/` (gitignored).

> **Phase 9 measures only — it never launches a model.** Every service is deployed by
> Phases 1–8. `bench check` verifies the stack is measurable and names the phase script for
> anything that is down, then stops. Starting a service from the benchmark would mean
> measuring a configuration nobody deployed.

---

## 1. Why this phase exists

Sherlock has never been measured. Four questions need answers:

1. **Capacity** — what fits on one GPU; can the VLM and MERaLiON co-reside.
2. **Interactive latency** — is the workbench fast enough for an investigator.
3. **Bottleneck attribution** — AI-Q orchestration vs RAG retrieval/rerank vs the model.
4. **Energy / cost per request** — J/req, for GB10 fleet sizing.

## 2. Scope

**Measured this round: the VLM, MERaLiON, and the RAG layer.** Those are what run on our
GPU. Everything else is a remote hosted NIM.

Remote NIMs (agent LLM, embedding, reranker, Parakeet ASR, Magpie TTS) are recorded as a
**wall-clock end-to-end baseline only** — no local deployment this round. Several will move
on-prem later for data-sensitivity reasons; these numbers are the bar local hosting must
beat. **They include internet RTT, so they bound local hosting rather than compare
like-for-like. Label them that way in the report.**

| # | Target | Endpoint | Tool |
|---|---|---|---|
| T1 | **Cosmos VLM** | `:8018/v1/chat/completions` | aiperf, direct |
| T2 | **MERaLiON-3-10B** | new shim (§4) | aiperf, via shim |
| T3 | **RAG layer** | `:8081/v1` | `rag-perf` (speed) + `rag-eval`/RAGAS (quality) |
| — | Nsight | — | only where T1–T3 flag something |

> **RAGAS measures quality, not speed.** It answers "are the answers faithful and
> grounded"; `rag-perf` answers "how fast". Both are in scope for T3 — do not let a RAGAS
> score stand in for a latency number.

## 3. Serving backends — established, not assumed

This was the open question before planning. The answers:

| Component | Serving backend | Protocol |
|---|---|---|
| **Cosmos VLM** | **vLLM, in-process inside the `vss-rtvi-vlm` container**, behind RT-VLM's FastAPI app. Not a NIM container; **no TensorRT engine**. Only the *weights* come from an NGC NIM artifact, which is why the model id has the form `nim_<org>_<model>_<tag>`. | **OpenAI-compatible** `:8018/v1`. Use **`/v1/chat/completions`** — `/v1/completions` returns **400 by design**. Health: `/v1/health/ready`. |
| **vss-lvs** (:38111) | **Not an inference server.** An orchestrator: chunks video, calls RT-VLM for captions, then an LLM for synthesis. Holds no model. | `/models` (no `/v1`) is OpenAI-shaped; `/v1/summarize` body is proprietary. **Do not point aiperf at it.** |
| **MERaLiON-3-10B** | **No server — in-process `transformers`**, bf16 + sdpa, `.to("cuda")`, module-level singleton. | Python call only. Needs the shim in §4. |
| **RAG** | RAG Blueprint containers | HTTP `:8081/v1` (server), `:8082/v1` (ingestor) |

Authority: `vss-deploy-dense-captioning/references/deploy-rt-vlm-service.md` ("VLM inference
(vLLM)") and `vss-deploy-profile/references/lvs-profile.md` ("RT-VLM's own runtime is a thin
wrapper around vLLM").

### Two traps that silently invalidate a VLM benchmark

**Trap 1 — RT-VLM has two modes.** `RTVI_VLM_MODEL_TO_USE=cosmos-reason*` loads weights and
serves them with the in-container vLLM (*integrated*). `openai-compat` loads nothing and
**proxies to a remote endpoint** — in that mode you would be benchmarking
`integrate.api.nvidia.com`, not the GPU. Check before every run:

```bash
docker exec vss-rtvi-vlm env | grep -E 'MODEL_TO_USE|MODEL_PATH|ENDPOINT'
```

**Trap 2 — aiperf sends plain OpenAI bodies.** Sherlock's real calls include non-OpenAI
fields (`num_frames_per_second_or_fixed_frames_chunk`, `use_fps_for_chunking` —
`mcp/vss_sherlock_mcp.py`). A default aiperf run therefore measures a *different workload*
than production. Pass them with `--extra-inputs`, or say plainly that the numbers describe
the text/image path rather than Sherlock's video path.

### This also settles the VLM identity question

`phase5_vss.sh` deploys `cosmos-reason1-7b`; `vss_sherlock_mcp.py` requests
`nim_nvidia_cosmos-reason2-8b_hf-1208`. Do not guess — ask the server:

```bash
curl -s http://localhost:8018/v1/models | jq -r '.data[0].id'
```

That exact string is what aiperf must pass as `--model`. Record it in the results.

---

## 4. MERaLiON shim (prerequisite for T2)

MERaLiON loads in-process, so aiperf cannot reach it. `benchmark/shim/meralion_server.py`
wraps it in an OpenAI-compatible FastAPI service: load once at startup, accept audio, return
a chat-shaped response.

Two constraints:
- **Wrap `transformers` directly. Do not assume it loads under vLLM** — it needs
  `trust_remote_code=True` and a custom `MERaLiON3Config` whose `pad_token_id` must be
  patched before `from_pretrained`.
- Honour the **30 s clip limit** (Whisper encoder) and the 16 kHz resample.

This is production-shaped work, not benchmark scaffolding: in-process means the model cannot
be shared, pooled, or scaled, and it forces every caller to hold ~20 GB of VRAM.

---

## 5. Workload corpus

Built from the Phase 3 output — real case data, not synthetic prompts. Measured:

Measured by `benchmark/build_workloads.py` (`workloads/corpus_stats.json`), ~4 chars/token:

| Asset | Count | Mean | Max |
|---|---|---|---|
| Cases | 21 | **2,154 tokens** of text each | **6,354 tokens** (25,416 chars) |
| — case report | 21 | 882 tok | 1,417 tok |
| — lab report | 21 | 529 tok | 1,691 tok |
| — WhatsApp chat | 21 | 469 tok | 1,914 tok |
| — witness statement | 21 | 275 tok | 1,333 tok |
| RAG queries generated | 105 | — | ≥ 50, so p99 is usable |
| VLM prompts generated | 6 | over 2 videos | — |
| Sample WAVs | 4 | 35.3 / 42.4 / 51.4 / 99.0 s | 24–44.1 kHz mono |
| Sample MP4s | 2 | `men_assault.mp4`, `drug-seize.mp4` | — |

**Sizing implication:** a whole case is ~2.2 k tokens typical, ~6.4 k worst case, against a
`VLM_MAX_MODEL_LEN` default of 32,768. Retrieved context, not the raw case, is what drives
ISL — confirm the real distribution in B5 before tuning context length down.

`benchmark/workloads/` holds the generated aiperf inputs, generated by
`benchmark/build_workloads.py`. **Pin ISL/OSL** (`min_tokens == max_tokens`,
`ignore_eos: true`) — without it, cross-run comparison is invalid because output length
varies per run.

> ### MERaLiON is windowed, so audio latency scales with duration
> The encoder caps at 30 s per forward pass. Recordings are **split into windows and
> aggregated** (`data/audio/process_audio.py`, mirrored in the shim) — this replaced an
> earlier hard clip that silently discarded everything past 30 s, which on the 99 s sample
> meant 69 s of unexamined evidence.
>
> **Benchmark consequence:** a MERaLiON request is no longer fixed work. The 35 s / 42 s /
> 51 s / 99 s samples do 2 / 2 / 2 / 4 forward passes respectively. Report latency
> **per window** as well as per request, and never compare a 4-window request against a
> 1-window request as if they were equal work. The response carries `meralion.windows`.

---

## 6. Steps and gates

Each step ends with a gate. Record results in this file as you go.

### B1 — Pre-work: fix defects, settle the VLM identity *(no GPU)*
Fix defects that would corrupt results; settle the VLM identity; capture
`bash deploy/resource_snapshot.sh` as the before state.
**Gate:** clean snapshot; model id recorded.

### B2 — Workload corpus: generate inputs from the 21 cases *(no GPU)*
Generate `benchmark/workloads/*.jsonl` + an audio manifest from `data/cases/`.
**Gate:** deterministic and regenerable from a clean clone.

### B3 — MERaLiON service: put the model behind HTTP *(GPU — a **Phase 4** deliverable)*
`data/audio/meralion_server.py` exposes MERaLiON over OpenAI-compatible HTTP so it can be
shared and pooled rather than loaded per-caller at ~20 GB. Deploy it from
`deploy/phase4_audio.sh`; point `process_audio.py` at it with in-process as fallback.
**Gate:** service and in-process agree on a known WAV, and `bench check` sees it up.

### B4 — Solo baselines: aiperf against the VLM and MERaLiON alone *(GPU)*
Confirm integrated mode and read the model id **first**. Warm up, then sweep request rate.

```bash
aiperf profile \
  --url http://localhost:8018 \
  --model "$(curl -s http://localhost:8018/v1/models | jq -r '.data[0].id')" \
  --endpoint-type chat \
  --input-file benchmark/workloads/vlm_video.jsonl \
  --custom-dataset-type single_turn \
  --streaming \
  --request-rate <r> --arrival-pattern poisson \
  --warmup-request-count 10 \
  --output-artifact-dir benchmark/results/rtx_pro6000/vlm-r<r>
```

Capture TTFT, ITL, e2e p50/p90/p95/p99, throughput, error rate, VRAM high-water, SM%/DRAM%,
and J/req from the power sampler.
**Gate:** error rate 0; p99 flagged when n < 50; mode + model id recorded.

### B5 — RAG layer: stage breakdown via `rag-perf`, quality via RAGAS *(GPU)*
Run `rag-perf` from the RAG Blueprint repo root, and RAGAS via `rag-eval`. The corrected
config schema is in `deploy/PHASE9_PLAN.md` §9c-rag — **use it; an earlier draft used
`rag.host`/`rag.port` and nested `load:` under `aiperf:`, none of which exist, so those
settings were silently ignored.** Verify the collection first:

```bash
curl -s http://localhost:8082/v1/collections   # must contain multimodal_data
```

**Gate:** bottleneck named; citations non-zero (zero citations means the collection name is
wrong, not that the corpus is empty).

### B6 — Contention: what co-resides on one card *(GPU — the headline result)*
```bash
python3 benchmark/cli.py coloc --all --resume
```
Colocations are declared in `benchmark/config/rtx_pro6000.yaml`: `vlm-solo`,
`vlm-meralion`, `vlm-meralion-rag`, `vlm-rate-sweep`. Each tenant is first measured alone
at the same offered rate; degradation is contention/solo.

Answers TODO 3a/3b directly: does a ~46–62 GB VLM plus a ~20 GB MERaLiON fit in 96 GB, and
what do they cost each other. This is the gate on moving the remote NIMs local — a model
that does not co-reside today will not co-reside with more tenants added.
**Gate:** VRAM ceiling measured (resolving the 46-vs-62 GB dispute — if it matches neither,
that is itself a finding); degradation table populated; every window overlapped.

### B7 — Nsight: profile only what B4–B6 flagged *(GPU)*
Only on components B4–B6 flagged.

```bash
nsys profile --trace=cuda,nvtx,osrt --gpu-metrics-devices=all \
  --cuda-memory-usage=true --force-overwrite=true --duration=30 \
  --output=benchmark/results/rtx_pro6000/profiles/<name> <cmd>

nsys stats --report cuda_gpu_kern_sum        --format csv <out>.nsys-rep
nsys stats --report cuda_gpu_mem_time_sum    --format csv <out>.nsys-rep
nsys stats --report gpu_metric_gpu_util_sum  --format csv <out>.nsys-rep
```

Thresholds: SM Active >80 % = compute-bound; DRAM >85 % = memory-bound; H2D+D2H >15 % of
wall time = a data-path problem.
`ERR_NVGPUCTRPERM` → set `NVreg_RestrictProfilingToAdminUsers=0`, or run `--privileged`.
**If nsys cannot run, report that. Never present a wall-clock measurement as a profile.**

### B8 — Report: summary.md + seed knowledge.yaml
`benchmark/results/rtx_pro6000/summary.md`: winner first, then why, then how to improve.
Seed `benchmark/knowledge.yaml` with each diagnosed cause so later runs explain themselves.

---

## 7. Measurement discipline

Adopted deliberately. Each rule exists because violating it produces numbers that look fine
and mean nothing.

- **Open-loop for contention.** Use `--request-rate` with an arrival pattern, never
  closed-loop `--concurrency`. Closed-loop throttles itself when the server slows, which
  hides exactly the degradation you are trying to measure.
- **Shared `t0` and an overlap check.** If tenants did not actually run at the same time,
  the run is **flagged, not reported**.
- **Baselines keyed on request rate**, so a p50 rung is never divided by a p25 baseline.
- **MPS on** for co-residency; without it tenants time-slice rather than share, and the
  ratios describe something else.
- **Safe-operating envelope** = the load where `achieved_rps < 0.95 × offered_rps`.
- **Pinned ISL/OSL**, or runs are not comparable.
- **No silent caps.** Anything skipped, sampled or truncated is stated in `summary.md`.
- **p99 needs n ≥ 50.** Below that, label it unreliable.

## 8. Optimization plan (feeds Track 3c)

Every lever is gated on a measurement — nothing is applied speculatively. Because the VLM
runs on vLLM, the levers are standard vLLM knobs already exposed as host env vars; no
forking required.

| Lever | Knob | Gated on |
|---|---|---|
| Batching / concurrency | `RTVI_VLLM_MAX_NUM_SEQS`, `RTVI_VLLM_MAX_NUM_BATCHED_TOKENS` | B4 rate-sweep knee |
| VRAM share | `RTVI_VLLM_GPU_MEMORY_UTILIZATION` (auto-set to 0.7 when VRAM ≤ 50 GB) | B6 |
| Context sizing | `VLM_MAX_MODEL_LEN` (default 32768) vs measured ISL | B4 |
| **Prefix caching** | `VLLM_ENABLE_PREFIX_CACHING` — **currently `false`**. Sherlock reuses a fixed forensic persona prefix, so this is the cheapest likely TTFT win. | B4 TTFT |
| Model right-sizing | Reason1-7B vs Reason2-8B — frees ~10–15 GB, which probably decides whether MERaLiON co-resides | B6 + quality check on the 2 sample MP4s |
| Quantization | FP8 / NVFP4 on Blackwell — largest expected win; the VLM dominates the card | B4 baseline + quality on the forensic corpus |

Two items that are not knobs:

- **Cache video analysis.** Today 5 `summarize_video` calls produce **0** Elasticsearch
  documents: every question re-runs inference. Caching removes the repeat cost *and* closes
  the provenance gap that makes a `summarize_video` citation point at a non-deterministic
  process rather than a stored artifact. For a court-defensible deliverable that is a
  correctness fix that happens to be free performance.
- **GB10 port.** Unified LPDDR5x at ~273 GB/s is a capacity box, not a latency box.
  Re-derive every setting; do not copy the RTX Pro 6000 values.

**Quality gate on all of it:** an optimization that degrades caption or answer fidelity is
not an optimization here. Evidence that is fast and wrong is worthless.

## 9. Constraints and hazards

- **The dev box has no GPU** (`nsys` present, no driver; `aiperf` absent). B1–B2 run
  anywhere; B3–B7 need the GPU box.
- **rtvi-vlm patches die on container recreate.** Anything that restarts the stack must
  re-run `deploy/patch_vss_rtvi_vlm.sh`, or the VLM changes behaviour mid-suite.
- **nv-ingest must not idle co-run with VSS** — documented memory contention. Stop it before
  capacity runs or the numbers are noise.
- **Skill coverage is partial.** `rag-perf` is the only aiperf-authoritative NVIDIA skill.
  **No skill covers Nsight profiling of NIMs** — the nsys recipe above is borrowed technique
  from `deepstream-profile-pipeline` plus vendor docs, and should be labelled as such.
  Note also that `BENCHMARK.md` inside the NVIDIA skills is an NVSkills-Eval quality report,
  **not** performance guidance.

## 10. Results

**Run 1 — 2026-08-31, RTX PRO 6000 Blackwell (96 GB, x86_64), Boon Ping.**
Three suite attempts in one session. The first two produced no usable contention numbers.
Five defects found, four fixed; every one produced a run that *completed* while measuring
nothing or the wrong thing. Harness fixes: `ee7ee1e`, `d72b1a3`.

| Step | Date | Outcome |
|---|---|---|
| B1 | 2026-08-31 | ✅ VLM identity settled from the server, not config: `/v1/models` reports `nim_nvidia_cosmos-reason2-8b_hf-1208` with ~69 GB resident = integrated mode, not a proxy. `RTVI_VLM_MODEL_TO_USE` is **not in the container env at all**, so the documented `printenv` check cannot answer this — use the model id + VRAM instead |
| B2 | 2026-08-31 | ✅ 21 cases → 105 RAG queries, 6 VLM prompts over 2 videos, 8 audio prompts over 4 WAVs |
| B3 | 2026-08-31 | ✅ MERaLiON shim up on :8500, ~23 GB VRAM, ~45 s load |
| B4 | 2026-08-31 | ✅ VLM: 2.0–3.5 s e2e p50, 1.93 of 2 rps, 0% errors, 88–97% SM, ~175–190 J/req. MERaLiON: 3.8 s warm/short clip, 5.5 s p50 / 20.6 s p95, ~0.18 rps ceiling, 19–25% SM, 963–3271 J/req |
| B5 | — | ⬜ **not started.** Blocked on defect 3: `coloc` cannot drive a `serving: rag_perf` tenant |
| B6 | 2026-08-31 | ✅ **`vlm-meralion-sustained` is the only window that passed the overlap check.** VLM 1.12× e2e p95, MERaLiON 1.05×, throughput ~1.00× both. VRAM peak **93.2 of 96 GB**. The 1 rps windows are correctly voided |
| B7 | 2026-08-31 | ✅ MERaLiON is **decode-bound**: `generate` 46.6% of py-spy samples, `_sample` 41.8%, gemma2 `forward` 41.7%; top GPU kernel `gemvx` (batch-1 matrix-vector) + tens of thousands of tiny elementwise kernels; 6.7 s GPU kernel time over ~19 s driving |
| B8 | 2026-08-31 | ✅ `benchmark/results/rtx_pro6000/summary.md`; `knowledge.yaml` still carries its seeded HYPOTHESIS for the VLM ratio |

### The headline: co-residency is cheap, saturation is not

At rates both models can serve, sharing one card costs little:

| Tenant | offered | throughput kept | e2e p50 | e2e p95 |
|---|---|---|---|---|
| VLM | 2 rps | ≈1.00× | 0.84× | **1.12×** |
| MERaLiON | 0.045 rps | ≈1.00× | ≈1.00× | **1.05×** |

They fit — **93.2 GB peak of 96** (VLM 69.6 + MERaLiON 23.2) — with under 3 GB spare. That
is not a margin to run production on without pinning `RTVI_VLLM_GPU_MEMORY_UTILIZATION`.

At 1 rps MERaLiON is ~20× past its ceiling: achieved 0.108–0.158 rps, driver timed out,
most requests cancelled. **Do not read its 58–95 s p50 there as service time — that is
queueing.** Both 1 rps windows are voided by the overlap check.

### Why MERaLiON is slow, and why the GPU looks idle

25% SM at 140 W while a request takes seconds looked like audio preprocessing. It is not.
py-spy puts the time in HF `transformers` autoregressive generation, and the top CUDA kernel
is `gemvx` — matrix-**vector**, the signature of batch-1 decoding. There is no continuous
batching and no paged attention, so the GPU is latency-bound on small kernels and concurrent
requests queue instead of batching. That single fact explains the low SM, the ~0.18 rps
ceiling, the collapse at 1 rps, and the 963–3271 J/req against the VLM's ~185.

Fixing it means a batching server, and the shim's own docstring records why that is not a
drop-in: MERaLiON needs `trust_remote_code=True` and a custom `MERaLiON3Config` whose
`pad_token_id` is patched before `from_pretrained`, so it is not a vLLM architecture.

### The five defects — all silent

| # | Root cause | How it showed up |
|---|---|---|
| 1 | aiperf resolves its tokenizer from `--model`; the VLM's served id is an NGC NIM artifact name, not a HF repo | 401 → aiperf exited before one request. `--use-server-token-count` does **not** avoid this in 0.11 |
| 2 | `parse_aiperf_records` only understood aiperf ≤0.10's flat export; 0.11 writes `{metadata,metrics}` | 233 successful requests parsed as **0** |
| 3 | `coloc` resolves a model for every tenant regardless of `serving` | the `rag_perf` tenant aborted the whole suite. **Still open** |
| 4 | `audio_manifest.json` is a JSON array; aiperf's `single_turn` loader reads JSONL | `Invalid JSON in dataset file`; MERaLiON never driven in **any** window, which in turn voided every ratio |
| 5 | `warmup` is per-REQUEST, so a fixed 10 cost **441 s** on MERaLiON vs 25 s on the VLM | the slow tenant was still warming while the fast tenant's whole window opened and closed → `TENANTS DID NOT OVERLAP` |

Defect 5 is the instructive one. The VLM *did* degrade 1.47× in that run — real contention,
against MERaLiON's **warmup**, attributed to the wrong phase. Without the overlap check that
would have been published as a contention result.

### Environment traps

- **Gated HF repos.** `nvidia/Cosmos-Reason2-8B` and `MERaLiON/MERaLiON-3-10B` both gate.
  A valid token is not enough — the *account* needs access, and 403 says "not in the
  authorized list", not "bad credentials". Approval was instant for an @nvidia account.
- **Nsight cannot attach to a running process**, so profiling the VLM would mean restarting
  `vss-rtvi-vlm` and discarding its writable-layer patches. Profile MERaLiON instead.
- **`ptrace_scope=1`** (Ubuntu default) blocks `py-spy dump --pid`; `py-spy record -- <cmd>`
  works with no privilege.
- **`perf_event_paranoid=4`** blocks nsys CPU sampling. `sudo sysctl -w kernel.perf_event_paranoid=2`
  flips `process-tree` sampling to OK. The B7 script reads the live value and adapts.
- **nsys needs no download**: `docker cp` it out of `vss-rtvi-vlm`
  (`/usr/local/cuda-13.0/NsightSystems-cli-2025.5.1`, 411 MB).
- **`pkill -f 'meralion_server.py --port 8500'` kills your own shell** — its command line
  contains the pattern. Kill by PID.
- **No swap on this host**, and the card sits at ~95 of 96 GB with both models loaded. A
  second MERaLiON instance OOMs the box and takes sshd with it; B7 guards against it.

### Next

1. **B5** — write a `rag_perf` driver so `coloc` can carry the RAG tenant (closes defect 3).
2. **Pin `RTVI_VLLM_GPU_MEMORY_UTILIZATION`** and re-run `vlm-meralion-sustained` to test
   §5's KV-cache hypothesis, which is still `HYPOTHESIS (unmeasured)`.
3. **Raise MERaLiON's rate toward its measured 0.18 rps ceiling** — 0.045 was chosen from a
   worst-case clip and is conservative.
4. **GB10**: new `gb10.yaml`. 128 GB unified memory; headroom maths does not transfer.
