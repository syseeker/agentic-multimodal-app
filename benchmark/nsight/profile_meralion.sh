#!/usr/bin/env bash
# B7 — profile the MERaLiON shim: GPU timeline (Nsight) + Python frames (py-spy).
#
# WHY MERALION, NOT THE VLM. B7's rule is "profile only what B4-B6 flagged". The flagged
# hotspot is MERaLiON: ~57 s e2e p50 while the GPU sits at 25.6% SM / 140 W, versus the
# VLM's 2.5 s at 90.6% SM / 288 W. A quarter-utilised GPU on a minute-long request means
# most of the time is NOT in the forward pass -- audio decode/resample, feature extraction,
# or the 30 s encoder windows running in series. That is a profiling question, and it is
# also why MERaLiON costs 1524 J/req against the VLM's 188.
#
# There is also a hard constraint: Nsight profiles what IT LAUNCHES and cannot attach to an
# arbitrary running process. Profiling the VLM would mean restarting vss-rtvi-vlm under
# nsys, which recreates the container and DISCARDS the patch_vss_rtvi_vlm.sh patches.
# MERaLiON is our own process, so it can be relaunched freely.
#
# Same reason py-spy LAUNCHES rather than attaches: kernel.yama.ptrace_scope=1 (Ubuntu
# default) permits tracing descendants only, so `py-spy dump --pid <running server>` fails
# with "Permission Denied" while `py-spy record -- <cmd>` works with no root at all.
#
# The two profilers run as SEPARATE passes. Both use ptrace/signal machinery and nesting
# them risks one perturbing the other -- and at 5 requests a pass, two passes are cheap.
#
#   bash benchmark/nsight/profile_meralion.sh [n_requests] [mode]
#     mode: both (default) | nsys | pyspy
#
# Output: benchmark/results/rtx_pro6000/nsight/
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

N_REQ="${1:-5}"
MODE="${2:-both}"
PORT="${PORT:-8501}"          # NOT 8500 -- leave the benchmarked shim untouched
OUT_DIR="benchmark/results/rtx_pro6000/nsight"
CLIP="data/audio/sample/SC-2024-03C5F0E4_phone_call_recording.wav"

export PATH="$HOME/.local/bin:$PATH"
[ -f "$CLIP" ] || { echo "ERROR: profile clip missing: $CLIP"; exit 3; }
mkdir -p "$OUT_DIR"
export HF_TOKEN="$(grep -m1 '^HF_TOKEN=' .env | cut -d= -f2- | sed 's/[[:space:]]*#.*//' | tr -d '[:space:]')"

# ── Safety: this box cannot hold two MERaLiON instances ─────────────────────
# Measured 2026-08-31: VLM 69.6 GB + MERaLiON 23.2 GB = 95.4 of 97.9 GB, ~2.5 GB free.
# Each shim is ~23 GB VRAM and ~9 GB host RSS, and the host has NO SWAP -- so launching a
# profiling instance beside the benchmarked one on :8500 CUDA-OOMs at best and pushes the
# box into the OOM killer at worst (which takes sshd with it). Profiling REPLACES the
# running shim; it never runs beside it. Passes are sequential for the same reason.
require_vram_gb() {   # $1 = GB needed
    local free_mib
    free_mib=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1)
    local need_mib=$(( $1 * 1024 ))   # measured footprint 23.2 GB; 24 leaves a margin
    if [ "$free_mib" -lt "$need_mib" ]; then
        echo "ERROR: only ${free_mib} MiB VRAM free; need ~${need_mib} MiB."
        echo "  A MERaLiON instance is ~23 GB. Free the card first:"
        echo "    pkill -f 'meralion_server.py --port 8500'     # stop the benchmarked shim"
        echo "  Do NOT run this while benchmark/cli.py coloc is running -- it would both"
        echo "  OOM and corrupt the contention numbers it is competing with."
        exit 3
    fi
    echo "  VRAM free: ${free_mib} MiB (need ~${need_mib}) -- ok"
}

refuse_if_bench_running() {
    if pgrep -f 'benchmark/cli.py coloc' >/dev/null 2>&1; then
        echo "ERROR: a coloc run is in progress. Profiling now would contend for the GPU and"
        echo "       invalidate both its numbers and this profile. Wait for it to finish."
        exit 3
    fi
}

wait_vram_free() {   # $1 = GB, $2 = tries
    for _ in $(seq 1 "${2:-24}"); do
        local free_mib
        free_mib=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1)
        [ "$free_mib" -ge $(( $1 * 1024 )) ] && return 0
        sleep 5
    done
    return 1
}

drive_requests() {   # $1 = port, $2 = n
    python3 - "$1" "$2" "$CLIP" <<'PY'
import base64, json, sys, time, urllib.request
port, n, clip = sys.argv[1], int(sys.argv[2]), sys.argv[3]
b64 = base64.b64encode(open(clip, "rb").read()).decode()
for i in range(n):
    body = {"model": "MERaLiON/MERaLiON-3-10B", "max_tokens": 256, "messages": [{"role": "user", "content": [
        {"type": "text", "text": "Describe the speaker's emotion, stress level and language."},
        {"type": "input_audio", "input_audio": {"data": b64, "format": "wav"}}]}]}
    req = urllib.request.Request(f"http://localhost:{port}/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t = time.time()
    urllib.request.urlopen(req, timeout=900).read()
    print(f"    request {i+1}/{n}: {time.time()-t:.1f}s")
PY
}

wait_ready() {       # $1 = port
    echo -n "  waiting for the shim to load"
    for _ in $(seq 1 90); do
        if curl -sf --max-time 3 "http://localhost:$1/v1/health/ready" >/dev/null 2>&1; then
            echo " ready"; return 0
        fi
        sleep 5; echo -n "."
    done
    echo " TIMEOUT"; return 1
}

refuse_if_bench_running
require_vram_gb 24

# ── Pass 1: Nsight Systems — the GPU timeline ────────────────────────────────
if [ "$MODE" = both ] || [ "$MODE" = nsys ]; then
    command -v nsys >/dev/null || {
        echo "ERROR: nsys not on PATH."
        echo "  No download or sudo needed -- the VSS container ships Nsight Systems, and"
        echo "  MERaLiON runs on the host, so copy it out:"
        echo "    docker cp vss-rtvi-vlm:/usr/local/cuda-13.0/NsightSystems-cli-2025.5.1 \\"
        echo "              ~/.local/opt/NsightSystems-cli-2025.5.1"
        echo "    ln -sf ~/.local/opt/NsightSystems-cli-2025.5.1/target-linux-x64/nsys ~/.local/bin/nsys"
        echo "  (411 MB; adjust the CUDA version if the image changes.)"
        exit 4
    }

    # CPU sampling needs perf_event_open, which kernel.perf_event_paranoid gates. At the
    # Ubuntu default of 4 it is unavailable and asking for it yields warnings plus empty CPU
    # rows, so decide from the live value instead of hardcoding either way.
    PARANOID="$(cat /proc/sys/kernel/perf_event_paranoid 2>/dev/null || echo 4)"
    if [ "$PARANOID" -le 2 ]; then
        SAMPLE_ARGS=(--sample=process-tree --cpuctxsw=process-tree)
        echo "  perf_event_paranoid=$PARANOID -> CPU sampling ENABLED"
    else
        SAMPLE_ARGS=(--sample=none --cpuctxsw=none)
        echo "  perf_event_paranoid=$PARANOID -> CPU sampling OFF (GPU trace only)."
        echo "    Enable with: sudo sysctl -w kernel.perf_event_paranoid=2"
        echo "    py-spy still gives Python-level frames without any privilege change."
    fi

    REP="$OUT_DIR/meralion-${N_REQ}req"
    echo "=== B7 pass 1/2: Nsight (${N_REQ} requests, port ${PORT}) ==="
    # --delay skips the ~45 s checkpoint load so the trace is inference, not weight loading.
    nsys profile \
        --output "$REP" --force-overwrite true \
        --trace cuda,nvtx,cudnn,cublas \
        --cuda-memory-usage true \
        "${SAMPLE_ARGS[@]}" \
        --delay 45 --duration 600 \
        uv run data/audio/meralion_server.py --port "$PORT" &
    NSYS_PID=$!
    wait_ready "$PORT" || true
    echo "  driving ${N_REQ} request(s)..."
    drive_requests "$PORT" "$N_REQ" || true
    kill "$NSYS_PID" 2>/dev/null || true
    wait "$NSYS_PID" 2>/dev/null || true
    echo "  report: ${REP}.nsys-rep"
    nsys stats --report cuda_gpu_kern_sum "${REP}.nsys-rep" 2>/dev/null | head -20 || true
fi

# ── Pass 2: py-spy — which Python function eats the minute ───────────────────
if [ "$MODE" = both ] || [ "$MODE" = pyspy ]; then
    command -v py-spy >/dev/null || { echo "ERROR: py-spy missing — pip install --user py-spy"; exit 4; }
    # Pass 1's instance must be fully gone before this one allocates, or the two overlap by
    # ~23 GB on a card with ~2.5 GB spare.
    if ! wait_vram_free 24 24; then
        echo "ERROR: VRAM did not free after pass 1 (a stale python may still hold it)."
        nvidia-smi --query-compute-apps=pid,used_memory,process_name --format=csv,noheader | sed 's/^/    /'
        exit 3
    fi
    FLAME="$OUT_DIR/meralion-${N_REQ}req.pyspy.svg"
    echo "=== B7 pass 2/2: py-spy (${N_REQ} requests, port $((PORT+1))) ==="
    # `record --` LAUNCHES the server: ptrace_scope=1 forbids attaching to a process that is
    # not a descendant. --subprocesses because `uv run` execs a child interpreter.
    py-spy record --subprocesses --rate 100 --output "$FLAME" -- \
        uv run data/audio/meralion_server.py --port "$((PORT+1))" &
    SPY_PID=$!
    wait_ready "$((PORT+1))" || true
    echo "  driving ${N_REQ} request(s)..."
    drive_requests "$((PORT+1))" "$N_REQ" || true
    kill -INT "$SPY_PID" 2>/dev/null || true      # INT so py-spy writes the flamegraph
    wait "$SPY_PID" 2>/dev/null || true
    echo "  flamegraph: $FLAME"
fi

echo
echo "=== B7 done — artifacts in $OUT_DIR ==="
