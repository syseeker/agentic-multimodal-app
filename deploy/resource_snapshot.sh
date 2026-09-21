#!/usr/bin/env bash
# Resource snapshot — run at any point to capture memory/disk/GPU state.
# Use to compare RTX Pro 6000 (discrete VRAM + RAM) vs GB10 (128 GB unified).
#
# On GB10 unified memory: total footprint = VRAM used + RAM used.
# If that sum > 128 GB, the workload won't fit on GB10.
#
# Usage:
#   bash deploy/resource_snapshot.sh              # prints to stdout
#   bash deploy/resource_snapshot.sh > snapshot_$(date +%Y%m%d_%H%M%S).txt

set -euo pipefail
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
ARCH=$(uname -m)

echo "========================================================"
echo "Resource Snapshot — $TIMESTAMP"
echo "Arch: $ARCH | Host: $(hostname)"
echo "========================================================"

# ── GPU / VRAM ────────────────────────────────────────────────────────────────
echo ""
echo "── GPU ──────────────────────────────────────────────────"
if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu \
        --format=csv,noheader | while IFS=, read -r name total used free util temp; do
        echo "  Model   : $name"
        echo "  VRAM    : $used used / $total total ($free free)"
        echo "  GPU util: $util | Temp: $temp"
    done

    echo ""
    echo "  VRAM by process:"
    nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader 2>/dev/null | \
        sed 's/^/    /' || echo "    (no running GPU processes)"
else
    echo "  nvidia-smi not available (CPU-only or aarch64 UMA)"
fi

# ── System RAM ────────────────────────────────────────────────────────────────
echo ""
echo "── RAM ──────────────────────────────────────────────────"
free -h | grep -E "Mem|Swap" | awk '{printf "  %-6s total=%-8s used=%-8s free=%-8s available=%s\n", $1, $2, $3, $4, $7}'

# ── Unified memory estimate (for GB10 comparison) ─────────────────────────────
echo ""
echo "── GB10 Unified Memory Estimate ─────────────────────────"
VRAM_USED_MIB=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader 2>/dev/null | grep -o '[0-9]*' | head -1 || echo 0)
RAM_USED_KIB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
RAM_FREE_KIB=$(grep MemAvailable /proc/meminfo | awk '{print $2}')
RAM_USED_KIB=$((RAM_USED_KIB - RAM_FREE_KIB))
RAM_USED_MIB=$((RAM_USED_KIB / 1024))
TOTAL_MIB=$((VRAM_USED_MIB + RAM_USED_MIB))
TOTAL_GIB=$((TOTAL_MIB / 1024))

echo "  VRAM used : ${VRAM_USED_MIB} MiB"
echo "  RAM used  : ${RAM_USED_MIB} MiB"
echo "  ─────────────────────────────"
printf "  Total UMA : %d MiB (~%d GiB)\n" "$TOTAL_MIB" "$TOTAL_GIB"
echo ""
if [ "$TOTAL_GIB" -le 90 ]; then
    echo "  GB10 fit  : ✅ fits in 128 GB UMA (~$((128 - TOTAL_GIB)) GiB headroom)"
elif [ "$TOTAL_GIB" -le 115 ]; then
    echo "  GB10 fit  : ⚠️  tight in 128 GB UMA (~$((128 - TOTAL_GIB)) GiB headroom)"
else
    echo "  GB10 fit  : ❌ exceeds 128 GB UMA by ~$((TOTAL_GIB - 128)) GiB"
fi

# ── Docker containers RAM ─────────────────────────────────────────────────────
echo ""
echo "── Container RAM (top consumers) ────────────────────────"
docker stats --no-stream --format "{{.Name}}\t{{.MemUsage}}" 2>/dev/null | \
    sort -t'/' -k1 -rh | head -20 | awk '{printf "  %-45s %s\n", $1, $2}'

# ── Disk ──────────────────────────────────────────────────────────────────────
echo ""
echo "── Disk ─────────────────────────────────────────────────"
df -h / | tail -1 | awk '{printf "  /  used=%s  free=%s  (%s)\n", $3, $4, $5}'
echo ""
docker system df --format "{{.Type}}\t{{.Size}}\t{{.Reclaimable}}" 2>/dev/null | \
    awk '{printf "  Docker %-12s size=%-10s reclaimable=%s\n", $1, $2, $3}'

# ── CPU ───────────────────────────────────────────────────────────────────────
echo ""
echo "── CPU ──────────────────────────────────────────────────"
uptime | awk '{print "  Load avg:", $(NF-2), $(NF-1), $NF}'
echo "  Cores: $(nproc) logical"

echo ""
echo "========================================================"
