# Sherlock inference benchmark — rtx_pro6000

4 solo baseline(s), 4 contention window(s).

## 1. Decision metrics

| run | tenant | model | offered | achieved | e2e p50 | e2e p95 | TTFT p95 | err |
|---|---|---|---:|---:|---:|---:|---:|---:|
| vlm-meralion-sustained:solo:meralion | meralion | MERaLiON/MERaLiON-3-10B | 0.045/s | 0.053/s | 5473.1 | 20566.96 | 20566.96 | 0.0% |
| vlm-rate-sweep:solo:meralion | meralion | MERaLiON/MERaLiON-3-10B | 1/s | 0.158/s | 58972.77 | 89893.42 | 89893.42 | 0.0% |
| vlm-rate-sweep:solo:vlm | vlm | nim_nvidia_cosmos-reason2-8b_hf-1208 | 1/s | 0.908/s | 2032.94 | 4040.19 | 4040.19 | 0.0% |
| vlm-meralion-sustained:solo:vlm | vlm | nim_nvidia_cosmos-reason2-8b_hf-1208 | 2/s | 1.927/s | 3532.51 | 6521.32 | 6521.32 | 0.0% |
| vlm-meralion | vlm | nim_nvidia_cosmos-reason2-8b_hf-1208 | 2/s | 1.872/s | 3614.25 | 6624.88 | 6624.88 | 0.0% |
| vlm-meralion | meralion | MERaLiON/MERaLiON-3-10B | 1/s | 0.0/s | - | - | - | 0.0% |
| vlm-meralion-sustained | vlm | nim_nvidia_cosmos-reason2-8b_hf-1208 | 2/s | 1.93/s | 2977.34 | 7300.58 | 7300.58 | 0.0% |
| vlm-meralion-sustained | meralion | MERaLiON/MERaLiON-3-10B | 0.045/s | 0.053/s | 5490.99 | 21562.14 | 21562.14 | 0.0% |
| vlm-rate-sweep | vlm | nim_nvidia_cosmos-reason2-8b_hf-1208 | 1/s | 0.908/s | 3149.23 | 5564.62 | 5564.62 | 0.0% |
| vlm-rate-sweep | meralion | MERaLiON/MERaLiON-3-10B | 1/s | 0.108/s | 77584.09 | 94838.13 | 94838.13 | 0.0% |
| vlm-solo | vlm | nim_nvidia_cosmos-reason2-8b_hf-1208 | 2/s | 1.933/s | 3531.03 | 6613.43 | 6613.43 | 0.0% |

## 2. Degradation vs solo

Ratio of contention to the SAME tenant measured alone at the SAME offered rate. `▲` = worse under contention.

| colocation | tenant | co-tenants | throughput kept | e2e p50 | e2e p95 | TTFT p95 |
|---|---|---|---:|---:|---:|---:|
| vlm-meralion | vlm | meralion | ≈0.97× | ≈1.02× | ≈1.02× | ≈1.02× |
| vlm-meralion | meralion | vlm | ▼0.00× | - | - | - |
| vlm-meralion-sustained | vlm | meralion | ≈1.00× | ▼0.84× | ▲1.12× | ▲1.12× |
| vlm-meralion-sustained | meralion | vlm | ≈1.00× | ≈1.00× | ≈1.05× | ≈1.05× |
| vlm-rate-sweep | vlm | meralion | ≈1.00× | ▲1.55× | ▲1.38× | ▲1.38× |
| vlm-rate-sweep | meralion | vlm | ▼0.68× | ▲1.32× | ▲1.06× | ▲1.06× |
| vlm-solo | vlm | - | ≈1.00× | ≈1.00× | ≈1.01× | ≈1.01× |

## 3. GPU resource usage

| run | VRAM peak | headroom | SM mean | power mean | J/req |
|---|---:|---:|---:|---:|---:|
| vlm-meralion-sustained:solo:meralion | 93.1 GB | 2.5 GB | 19.3% | 126.2 W | 3270.53 |
| vlm-rate-sweep:solo:meralion | 93.1 GB | 2.5 GB | 24.8% | 138.1 W | 962.98 |
| vlm-rate-sweep:solo:vlm | 93.2 GB | 2.4 GB | 69.4% | 270.4 W | 349.26 |
| vlm-meralion-sustained:solo:vlm | 93.2 GB | 2.4 GB | 96.7% | 327.0 W | 174.16 |
| vlm-meralion | 92.8 GB | 2.8 GB | 44.3% | 186.1 W | 406.6 |
| vlm-meralion-sustained | 93.2 GB | 2.4 GB | 88.1% | 322.9 W | 177.58 |
| vlm-rate-sweep | 93.2 GB | 2.4 GB | 55.3% | 207.9 W | 522.06 |
| vlm-solo | 92.8 GB | 2.8 GB | 94.1% | 316.1 W | 185.37 |

## 4. Validity flags

Every item here weakens or invalidates a number above.

- **vlm-meralion-sustained:solo:meralion/meralion** — p99 unreliable: only 32 successful requests (< 50)
- **vlm-rate-sweep:solo:meralion** — meralion: achieved 0.158/s vs offered 1/s — past the safe envelope
- **vlm-rate-sweep:solo:meralion/meralion** — p99 unreliable: only 19 successful requests (< 50)
- **vlm-rate-sweep:solo:vlm** — vlm: achieved 0.908/s vs offered 1/s — past the safe envelope
- **vlm-meralion** — meralion: driver timed out and was killed
- **vlm-meralion** — meralion: no requests recorded — driver or endpoint failed
- **vlm-meralion** — TENANTS DID NOT OVERLAP — this window measured sequential execution; its degradation ratios are not valid
- **vlm-meralion** — vlm: achieved 1.872/s vs offered 2/s — past the safe envelope
- **vlm-meralion** — meralion: achieved 0/s vs offered 1/s — past the safe envelope
- **vlm-meralion/meralion** — p99 unreliable: only 0 successful requests (< 50)
- **vlm-meralion-sustained/meralion** — p99 unreliable: only 32 successful requests (< 50)
- **vlm-rate-sweep** — TENANTS DID NOT OVERLAP — this window measured sequential execution; its degradation ratios are not valid
- **vlm-rate-sweep** — vlm: achieved 0.908/s vs offered 1/s — past the safe envelope
- **vlm-rate-sweep** — meralion: achieved 0.108/s vs offered 1/s — past the safe envelope
- **vlm-rate-sweep/meralion** — p99 unreliable: only 13 successful requests (< 50)

## 5. Core findings

- **Worst degradation:** `vlm` in `vlm-rate-sweep` at 1.38× solo e2e p95. **Why:** HYPOTHESIS (unmeasured): rtvi-vlm's vLLM sizes its KV cache from VLLM_GPU_MEMORY_UTILIZATION at startup, which is a whole-card fraction and is blind to a co-resident tenant. With MERaLiON holding ~20 GB the VLM's cache is squeezed, so batches split and queueing time appears in e2e rather than in the forward pass. Confirm by comparing kv usage and queue time between the solo and coloc windows before believing this. **How to improve:** Set RTVI_VLLM_GPU_MEMORY_UTILIZATION explicitly rather than relying on the auto value, sized as (96 - co-tenant weights - headroom) / 96. Then re-run the same colocation and check whether the ratio moves.
