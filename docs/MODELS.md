# Model selection (verified mid-2026)

Picks favor **ready-made quantized checkpoints** so you skip running ModelOpt
yourself. Verify the exact card revisions before a production run — these are
fast-moving repos.

## Recommended picks

| Modality | Repo | Precision | Serve via |
|---|---|---|---|
| **Text** (entities/relations) | [`Qwen/Qwen3-14B-FP8`](https://huggingface.co/Qwen/Qwen3-14B-FP8) | FP8 (official) | vLLM (no ModelOpt needed) |
| **Vision-Language** (OCR/scene) | [`Qwen/Qwen3-VL-8B-Instruct-FP8`](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-FP8) | FP8 (official) | vLLM ≥0.11.1 + `qwen-vl-utils==0.0.14` |
| **Audio** (ASR + paralinguistics) | [`MERaLiON/MERaLiON-3-10B`](https://huggingface.co/MERaLiON/MERaLiON-3-10B) | bf16 | **Transformers shim** (`serving/meralion_shim.py`) |

## Why these

- **Text — Qwen3-14B:** best ~14B dense, 100+ languages (native Chinese, SEA),
  strong tool-calling/JSON. Dense ⇒ the quant kernels are stable on Blackwell.
  No newer dense 14B exists (the line jumps 4B → 27B).
- **VLM — Qwen3-VL-8B:** OCR across 32 languages, robust to low-light/blur/tilt —
  ideal for seized screenshots and document photos.
- **Audio — MERaLiON-3:** not Singlish-only — it does ASR **plus**
  emotion/paralinguistics across English, **Singlish**, Chinese, Malay, Tamil,
  Indonesian, Thai, Vietnamese (built on Gemma-2-9B). That breadth + paralinguistics
  is why it's the default; NVIDIA ASR models lack paralinguistics and SEA/Singlish.

### Alternative ASR — NVIDIA Canary (A/B comparison)

A swappable, **ASR-only** NVIDIA option is wired in for benchmarking against
MERaLiON (it has no paralinguistics, so the sentiment tool falls back to
text-only when it's active):

- [`nvidia/canary-1b-v2`](https://huggingface.co/nvidia/canary-1b-v2) — multilingual
  ASR + speech translation (default `ASR_ALT_MODEL`).
- [`nvidia/canary-qwen-2.5b`](https://huggingface.co/nvidia/canary-qwen-2.5b) —
  English, top of the HF Open ASR leaderboard.

Run it alongside MERaLiON on port 8004:
```bash
docker compose --profile asr-compare up serving-asr-canary
# benchmark both: ./benchmark/run_aiperf.sh audio 8003   (MERaLiON)
#                 ./benchmark/run_aiperf.sh audio 8004   (Canary)
```
To run the whole app on Canary instead of MERaLiON, point `AUDIO_BASE_URL` at
`http://serving-asr-canary:8004/v1`. Served via NeMo (`serving/canary_shim.py`),
not vLLM. Note: Canary/Parakeet are weak on SEA/Singlish vs MERaLiON.

## NVFP4 alternatives (lower VRAM, Blackwell-native FP4)

- **Text:** [`RedHatAI/Qwen3-14B-NVFP4`](https://huggingface.co/RedHatAI/Qwen3-14B-NVFP4)
  — vLLM-ready (≥0.9.1); set `TEXT_QUANT=nvfp4` and serve with
  `--quantization modelopt_fp4`. Dense ⇒ safe on sm_120/121.
- **VLM:** no vLLM-ready **8B** NVFP4 exists (only 235B). Stay on FP8 for the 8B.
  A community 8B NVFP4 (`kaitchup/...`) is **not** vLLM-compatible — avoid.
- **Audio:** no quantized MERaLiON-3 checkpoint exists yet.

## Caveats (act on these)

1. **Blackwell vLLM kernel gaps (sm_120/121):** NVFP4-**MoE** and some FP8-MoE
   paths are still incomplete mid-2026. Our picks are **dense**, so they're fine.
   Avoid MoE quant variants on RTX PRO 6000 / GB10 unless you've tested the build.
   Requires CUDA ≥12.8.
2. **MERaLiON-3 has no vLLM path yet** (card says "vLLM coming soon") and no quant
   checkpoint — hence the Transformers shim. Swap `AUDIO_BACKEND=vllm` once
   support lands.
3. **No dedicated NIM** confirmed for Qwen3-14B / Qwen3-VL. NIM-turnkey FP8/NVFP4
   realistically applies to NVIDIA's own models. If you want an NVFP4 + NIM doc
   VLM, consider
   [`nvidia/NVIDIA-Nemotron-Nano-12B-v2-VL`](https://build.nvidia.com/nvidia/nemotron-nano-12b-v2-vl/modelcard)
   as the `VLM_MODEL`.
4. **ModelOpt is now optional.** `serving/quantize.py` remains for MERaLiON-3 (no
   ready quant) or any model lacking a published FP8/NVFP4 checkpoint.
