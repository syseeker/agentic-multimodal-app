# serving/ — vLLM FP8 model serving

Three OpenAI-compatible vLLM servers (text / VLM / audio), one model each, sharing
one GPU. FP8 (NVIDIA ModelOpt) keeps the combined footprint ~49 GB so all three
fit on a 96 GB RTX PRO 6000 or a 128 GB GB10 — fixing the original multi-container
OOM on 4090s.

## Files
- `Dockerfile` — vLLM base for text + VLM (override `BASE` for arm64/sbsa on GB10).
- `entrypoint.sh` — launches one vLLM server; flags adapt to `QUANT`/`GPU_PROFILE`.
- `Dockerfile.meralion` + `meralion_shim.py` — Transformers OpenAI-compatible shim
  for **MERaLiON-3** (no vLLM support yet).
- `quantize.py` — **optional** ModelOpt export. Not needed for text/VLM (we use
  ready FP8 checkpoints); keep it for MERaLiON-3 or any model without a published
  FP8/NVFP4. See [`../docs/MODELS.md`](../docs/MODELS.md).

## Precisions (`*_QUANT` in .env)
`fp8` (pre-quantized checkpoint, auto-detected) · `fp8-online` (quantize raw
weights) · `nvfp4` (`--quantization modelopt_fp4`, dense models only on Blackwell)
· `awq` · `bf16`.

## Run (via the root compose)
```bash
docker compose up serving-text serving-vlm serving-audio
```

## Verify
```bash
curl -s http://localhost:8001/v1/models                       # text
curl -s http://localhost:8002/v1/models                       # vlm
curl -s http://localhost:8003/v1/models                       # audio
nvidia-smi                                                     # expect < 60 GB total
```

## Model tags
Set in `.env` (`TEXT_MODEL`, `VLM_MODEL`, `AUDIO_MODEL`). **Verify the latest exact
tags on Hugging Face** — defaults in `.env.example` are not guaranteed current.
MERaLiON-3 vLLM support may require its plugin or a recent vLLM; if unavailable,
serve it via Transformers and point `AUDIO_BASE_URL` at that shim.
