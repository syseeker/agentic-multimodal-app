# benchmark/ — inference benchmarking & profiling (P1)

Quantify the serving layer so you can defend the FP8 choice and the GPU sizing.

## TTFT + output tok/s (aiperf)
```bash
pip install aiperf
./benchmark/run_aiperf.sh text 8001     # text model
./benchmark/run_aiperf.sh vlm 8002      # VLM
./benchmark/run_aiperf.sh audio 8003    # audio
```
Profile is long-input / short-output (forensic summarization). Run once per
`QUANT` (bf16 vs fp8) and per `GPU_PROFILE` (rtx6000 vs gb10) and compare.

## GPU timeline + kernels (Nsight)
```bash
./benchmark/nsight_profile.sh serving-text   # capture while aiperf drives load
```

## What to report
| Metric | Why |
|---|---|
| TTFT p50/p99 | interactivity for the investigator |
| Output tok/s | throughput for 5 concurrent users |
| VRAM (nvidia-smi) | confirms the 3 models fit (no multi-container OOM) |
| bf16 vs fp8 delta | justifies FP8 + ModelOpt |
| rtx6000 vs gb10 | sets latency expectations on the deploy box |
