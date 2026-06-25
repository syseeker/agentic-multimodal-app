# Deploying to GB10 / DGX Spark (arm64)

You develop on RTX PRO 6000 (x86_64) but customers deploy on **GB10 / DGX Spark** — Grace-Blackwell, **arm64 (sbsa)**, 128 GB unified memory. This requires multi-arch images and a few profile tweaks.

## 1. Build multi-arch images

```bash
docker buildx create --use --name ama 2>/dev/null || docker buildx use ama
docker buildx build --platform linux/amd64,linux/arm64 \
  -t <registry>/ama-app:0.1.0 --push app/
# repeat for serving/ and ui/
```

Pin base images that publish **arm64/sbsa** tags and have **Blackwell (sm_121)** wheels:
- vLLM: NVIDIA NGC vLLM container (sbsa variant) or a CUDA 12.6+ base.
- RAPIDS (cuVS/cuGraph): `cu12` wheels with arm64 builds.

## 2. Select the GB10 profile

In `.env`:
```bash
GPU_PROFILE=gb10
QUANT=fp8          # keep FP8 — GB10 bandwidth (273 GB/s) makes BF16 decode slow
MAX_MODEL_LEN=16384
```

`serving/` reads `GPU_PROFILE` and applies GB10-tuned vLLM flags (unified-memory-aware
`--gpu-memory-utilization`, conservative `--max-num-seqs`).

## 3. Bring up

```bash
docker compose --profile gb10 up -d
```

## Notes & caveats

- **Unified memory:** GB10 shares 128 GB between CPU and GPU. Leave headroom for OS + the agent/UI containers; don't set `--gpu-memory-utilization` to 1.0.
- **Bandwidth:** decode tokens/s will be lower than on RTX PRO 6000. Acceptable for a 5-user single-terminal MVP. Benchmark with `benchmark/` (aiperf) on the actual unit.
- **Multi-container OOM** (the original pain point): FP8 keeps the three servers at ~49 GB combined, well inside 128 GB — the crash mode on 4090s does not recur here.
- Verify exact arm64 wheel availability for `cugraph-cu12` at build time; if unavailable, run graph analytics on CPU fallback (NetworkX) — the code degrades gracefully.
