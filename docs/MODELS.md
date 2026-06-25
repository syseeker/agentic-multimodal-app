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
- **Audio — MERaLiON-3:** the only strong fit for English/**Singlish**/SEA **plus**
  emotion/paralinguistics (built on Gemma-2-9B). NVIDIA ASR (Parakeet/Canary)
  lacks paralinguistics and is weak on SEA/Singlish.

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
