# GPU sizing — 5-user MVP, three models

Models: **Qwen3 (~14B)** + **Qwen3-VL (~8B)** + **MERaLiON-3 (~10B)** ≈ **32B params total**.

## VRAM math

| Component | BF16 | FP8 | INT4/AWQ |
|---|---|---|---|
| Weights (~32B) | ~64 GB | ~32 GB | ~17 GB |
| KV cache, 5 users @ 8–16k ctx | ~16 GB (FP16) | ~8–16 GB | ~8–16 GB |
| Runtime overhead | ~10–15 GB | ~10 GB | ~10 GB |
| **Total** | **~90 GB** | **~49 GB** | **~37 GB** |

Context length is the dominant driver: 32k context inflates KV to 60–80 GB.

## GPU choices

| GPU | VRAM / BW | Verdict |
|---|---|---|
| **RTX PRO 6000 Blackwell** (dev) | 96 GB / 1.79 TB/s | **Sweet spot.** All 3 at FP8 (~49 GB) with headroom; high bandwidth = snappy decode for 5 users. |
| **GB10 / DGX Spark** (deploy) | 128 GB unified / 273 GB/s | Fits all 3 at FP8 *or* BF16, but low bandwidth = slower tokens. Fine for single-terminal 5-user MVP; set latency expectations. arm64/sbsa. |
| H100 | 80 GB / 3.35 TB/s | FP8 fits; BF16 tight. |
| H200 | 141 GB / 4.8 TB/s | BF16 + 32k headroom, fastest. Step up here for big context / datacenter throughput. |
| L40S | 48 GB / 864 GB/s | Budget: FP8/INT4 or split across two cards. |

## Recommendation

- **Develop** on RTX PRO 6000 at FP8.
- **Deploy** to GB10 — the 128 GB unified memory comfortably holds all three; quantize to FP8 to keep decode acceptable.
- Same FP8 artifacts run on both via the `serving/` GPU-profile switch (`GPU_PROFILE`).
- Need 32k context or higher throughput → H200.
