#!/usr/bin/env python3
"""Sample GPU state during a benchmark run, and derive energy per request.

Without this there is no J/req and no VRAM high-water mark — the two numbers that decide
whether a model fits on the card and what a fleet of them costs.

Standalone:
    python3 benchmark/probes/gpu_sampler.py --out samples.json --duration 120

In-process:
    with GpuSampler() as s:
        ...run the load...
    print(s.summary(requests=412))

Uses `nvidia-smi` rather than DCGM: DCGM gives richer counters (notably DRAM_ACTIVE) but is
not installed on these boxes, and a sampler that silently reports nothing is worse than one
with a stated ceiling. Where a field is unavailable it is reported as None, never as 0 —
a zero would read as "measured and idle".
"""
from __future__ import annotations

import argparse
import json
import subprocess
import threading
import time

# name, memory.used MiB, utilization.gpu %, power.draw W, clocks.sm MHz
_QUERY = "memory.used,memory.total,utilization.gpu,utilization.memory,power.draw"


def _sample() -> dict | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", f"--query-gpu={_QUERY}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode != 0:
            return None
        first = out.stdout.strip().splitlines()[0]
        vals = [v.strip() for v in first.split(",")]

        def num(x):
            try:
                return float(x)
            except ValueError:
                return None  # e.g. "[N/A]" on cards without a power sensor

        return {
            "t": time.time(),
            "mem_used_mib": num(vals[0]),
            "mem_total_mib": num(vals[1]),
            "sm_util_pct": num(vals[2]),
            "mem_util_pct": num(vals[3]),
            "power_w": num(vals[4]),
        }
    except (OSError, subprocess.SubprocessError, IndexError):
        return None


class GpuSampler:
    """Background poller. Context-manager or explicit start()/stop()."""

    def __init__(self, interval_s: float = 1.0):
        self.interval_s = interval_s
        self.samples: list[dict] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.available = _sample() is not None

    def _loop(self):
        while not self._stop.is_set():
            s = _sample()
            if s:
                self.samples.append(s)
            self._stop.wait(self.interval_s)

    def start(self):
        if not self.available:
            return self
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.interval_s * 2)
        return self

    __enter__ = start

    def __exit__(self, *_):
        self.stop()

    def summary(self, requests: int | None = None) -> dict:
        """Aggregate. `requests` enables J/req; omit it and energy_j is still reported."""
        if not self.available:
            return {"available": False,
                    "note": "nvidia-smi unavailable — no GPU numbers were collected"}
        if not self.samples:
            return {"available": True, "samples": 0,
                    "note": "sampler ran but collected nothing"}

        def series(key):
            return [s[key] for s in self.samples if s.get(key) is not None]

        mem, sm, memu, pw = (series("mem_used_mib"), series("sm_util_pct"),
                             series("mem_util_pct"), series("power_w"))
        span_s = self.samples[-1]["t"] - self.samples[0]["t"]

        # Energy by trapezoid over the power series. Idle draw is included deliberately:
        # a fleet pays for the card being on, not only for the kernels.
        energy_j = None
        if len(pw) >= 2 and span_s > 0:
            energy_j = 0.0
            prev = self.samples[0]
            for s in self.samples[1:]:
                if s.get("power_w") is not None and prev.get("power_w") is not None:
                    energy_j += (s["power_w"] + prev["power_w"]) / 2.0 * (s["t"] - prev["t"])
                prev = s

        out = {
            "available": True,
            "samples": len(self.samples),
            "duration_s": round(span_s, 1),
            "vram_peak_mib": max(mem) if mem else None,
            "vram_peak_gb": round(max(mem) / 1024, 1) if mem else None,
            "vram_total_gb": round(self.samples[0]["mem_total_mib"] / 1024, 1)
                             if self.samples[0].get("mem_total_mib") else None,
            "sm_util_mean_pct": round(sum(sm) / len(sm), 1) if sm else None,
            "sm_util_max_pct": max(sm) if sm else None,
            # nvidia-smi's utilization.memory is % of time the memory *interface* was busy.
            # It is NOT DCGM's DRAM_ACTIVE bandwidth figure — do not read it as one.
            "mem_util_mean_pct": round(sum(memu) / len(memu), 1) if memu else None,
            "power_mean_w": round(sum(pw) / len(pw), 1) if pw else None,
            "power_max_w": max(pw) if pw else None,
            "energy_j": round(energy_j, 1) if energy_j is not None else None,
        }
        if energy_j is not None and requests:
            out["requests"] = requests
            out["joules_per_request"] = round(energy_j / requests, 2)
        if pw and out["power_mean_w"] is None:
            out["note"] = "power sensor reported [N/A] — J/req unavailable on this card"

        # Flag the interpretation rules rather than leaving them to memory.
        flags = []
        if out["sm_util_mean_pct"] is not None and out["sm_util_mean_pct"] > 80:
            flags.append("compute-bound (SM active > 80%)")
        if out["vram_peak_gb"] and out["vram_total_gb"]:
            headroom = out["vram_total_gb"] - out["vram_peak_gb"]
            out["vram_headroom_gb"] = round(headroom, 1)
            if headroom < 5:
                flags.append(f"VRAM headroom only {headroom:.1f} GB — co-residency at risk")
        if flags:
            out["flags"] = flags
        return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="-")
    ap.add_argument("--duration", type=float, default=60.0)
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--requests", type=int, default=None, help="enables J/req")
    a = ap.parse_args()

    s = GpuSampler(a.interval)
    if not s.available:
        print(json.dumps({"available": False, "note": "nvidia-smi unavailable"}, indent=2))
        return 1
    s.start()
    try:
        time.sleep(a.duration)
    except KeyboardInterrupt:
        pass
    s.stop()

    doc = {"summary": s.summary(a.requests), "samples": s.samples}
    text = json.dumps(doc, indent=2)
    if a.out == "-":
        print(json.dumps(doc["summary"], indent=2))
    else:
        with open(a.out, "w") as fh:
            fh.write(text + "\n")
        print(f"wrote {a.out} ({len(s.samples)} samples)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
