# Phase 9e — Inference Benchmark (RAG · VLM · MERaLiON)

Part of Phase 9. Closes TODO.md Track 2c (Nsight + aiperf) and Track 3a (benchmarking).
Target hardware: **RTX Pro 6000 Blackwell (x86_64, 96 GB)** first; GB10 second.

Companion script dir: `benchmark/`. Results land in `benchmark/results/<gpu>/` (gitignored).

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
ISL — confirm the real distribution in S4 before tuning context length down.

`benchmark/workloads/` holds the generated aiperf inputs, generated by
`benchmark/build_workloads.py`. **Pin ISL/OSL** (`min_tokens == max_tokens`,
`ignore_eos: true`) — without it, cross-run comparison is invalid because output length
varies per run.

> ### ⚠️ Finding: MERaLiON only ever sees the first 30 s
> `data/audio/process_audio.py` hard-clips audio to 30 s (Whisper encoder limit) before
> paralinguistic analysis. **All four sample recordings exceed it** — 35.3 s, 42.4 s,
> 51.4 s and 99.0 s — so on the 99 s phone call **69 s of evidence is silently discarded**
> and the emotion/stress result describes only the opening.
>
> Two consequences. For the benchmark: MERaLiON latency is effectively constant regardless
> of input length, so a duration sweep measures nothing — say so rather than reporting a
> flat line as a result. For the product: presenting a first-30-s analysis as *the*
> paralinguistic finding is misleading in an evidentiary context. Chunk-and-aggregate, or
> state the limit in the workbench. Tracked as a Phase 9e output, not a benchmark artifact.

---

## 6. Steps and gates

Each step ends with a gate. Record results in this file as you go.

### S0 — Pre-work (no GPU)
Fix defects that would corrupt results; settle the VLM identity; capture
`bash deploy/resource_snapshot.sh` as the before state.
**Gate:** clean snapshot; model id recorded.

### S1 — Workload corpus (no GPU)
Generate `benchmark/workloads/*.jsonl` + an audio manifest from `data/cases/`.
**Gate:** deterministic and regenerable from a clean clone.

### S2 — MERaLiON shim (GPU)
Build the shim; point `data/audio/process_audio.py` at it, keeping in-process as fallback.
**Gate:** shim and in-process produce the same result for a known WAV.

### S3 — T1 + T2 aiperf (GPU)
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

### S4 — T3 RAG (GPU)
Run `rag-perf` from the RAG Blueprint repo root, and RAGAS via `rag-eval`. The corrected
config schema is in `deploy/PHASE9_PLAN.md` §9c-rag — **use it; an earlier draft used
`rag.host`/`rag.port` and nested `load:` under `aiperf:`, none of which exist, so those
settings were silently ignored.** Verify the collection first:

```bash
curl -s http://localhost:8082/v1/collections   # must contain multimodal_data
```

**Gate:** bottleneck named; citations non-zero (zero citations means the collection name is
wrong, not that the corpus is empty).

### S5 — Co-residency (GPU) — the headline result
VLM alone → VLM + MERaLiON → add RAG traffic. Open-loop only.
Answers TODO 3a/3b directly: does a ~46–62 GB VLM plus a ~20 GB MERaLiON fit in 96 GB, and
what do they cost each other.
**Gate:** VRAM ceiling measured — this also resolves the 46-vs-62 GB documentation dispute
empirically. If it matches neither figure, that is itself a finding.

### S6 — Nsight (GPU)
Only on components S3–S5 flagged.

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

### S7 — Report
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
| Batching / concurrency | `RTVI_VLLM_MAX_NUM_SEQS`, `RTVI_VLLM_MAX_NUM_BATCHED_TOKENS` | S3 rate-sweep knee |
| VRAM share | `RTVI_VLLM_GPU_MEMORY_UTILIZATION` (auto-set to 0.7 when VRAM ≤ 50 GB) | S5 |
| Context sizing | `VLM_MAX_MODEL_LEN` (default 32768) vs measured ISL | S3 |
| **Prefix caching** | `VLLM_ENABLE_PREFIX_CACHING` — **currently `false`**. Sherlock reuses a fixed forensic persona prefix, so this is the cheapest likely TTFT win. | S3 TTFT |
| Model right-sizing | Reason1-7B vs Reason2-8B — frees ~10–15 GB, which probably decides whether MERaLiON co-resides | S5 + quality check on the 2 sample MP4s |
| Quantization | FP8 / NVFP4 on Blackwell — largest expected win; the VLM dominates the card | S3 baseline + quality on the forensic corpus |

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

- **The dev box has no GPU** (`nsys` present, no driver; `aiperf` absent). S0–S1 run
  anywhere; S2–S6 need the GPU box.
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

*(fill in as steps complete — commands run, what worked, what failed, decisions taken)*

| Step | Date | Outcome |
|---|---|---|
| S0 | | |
| S1 | | |
| S2 | | |
| S3 | | |
| S4 | | |
| S5 | | |
| S6 | | |
| S7 | | |
