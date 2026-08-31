"""Colocation runner — how much do Sherlock's models degrade each other on one card?

This is the question that gates moving the remote NIMs local: what already fits on the
96 GB, and what does adding a tenant cost the others.

Method (each rule is load-bearing, not stylistic):
  * Tenants are launched together against ONE shared t0, then the traces are checked for
    genuine overlap. A window where tenants did not actually run concurrently measured
    sequential execution; it is FLAGGED, never reported as contention.
  * Load is open-loop. See lib.build_aiperf_cmd.
  * Each tenant is first measured SOLO at the same offered rate. Baselines are keyed on
    that rate and reused across colocations, so one solo run serves many windows.
  * degradation = contention / solo, computed later in summary.py from the manifests.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from lib import (Load, Tenant, TenantResult, build_aiperf_cmd, check_required_env,
                 overlap_window, parse_aiperf_records, resolve_model, solo_key,
                 solo_key_from_manifest)


def _tenant_from_cfg(spec: dict, cfg: dict, models: dict) -> Tenant:
    tname = spec["target"]
    target = cfg["targets"][tname]
    wl = cfg["workloads"].get(spec["workload"], {})
    load = spec.get("load") or {}
    return Tenant(
        name=spec["name"], target=tname, workload=spec["workload"],
        load=Load(pattern=load.get("pattern", "poisson"),
                  rps=float(load.get("rps", 1)),
                  output_tokens=wl.get("output_tokens")),
        model=models[tname], base_url=target["base_url"],
    )


def run_dir_for(root: Path, coloc_id: str, tenants: list[Tenant], solo: bool) -> Path:
    tag = "-".join(f"{t.name}@{t.load.rps:g}" for t in tenants)
    if solo:
        # Shared baselines dir, named as a pure function of the key, so the same baseline
        # always lands at the same path and is found again on resume.
        t = tenants[0]
        h = abs(hash(solo_key(t))) % (16 ** 8)
        return root / "_baselines" / f"solo-{t.target}-{t.workload}@{t.load.rps:g}-{h:08x}"
    return root / coloc_id / f"coloc-{tag}"


def find_existing_baseline(baselines_dir: Path, tenant: Tenant) -> Path | None:
    """Resume by IDENTITY, not by path — a baseline is valid if its key matches."""
    want = solo_key(tenant)
    if not baselines_dir.is_dir():
        return None
    for m in sorted(baselines_dir.glob("*/manifest.json")):
        try:
            got = solo_key_from_manifest(json.loads(m.read_text()))
        except (OSError, ValueError):
            continue
        if got is not None and got == want:
            return m.parent
    return None


def _input_file(cfg: dict, workload: str) -> Path | None:
    f = (cfg["workloads"].get(workload) or {}).get("file")
    if not f:
        return None
    p = Path(f)
    return p if p.is_absolute() else (Path(__file__).resolve().parent.parent / p)


def run_window(cfg: dict, coloc_id: str, coloc: dict, tenants: list[Tenant],
               out_dir: Path, *, solo: bool, sampler=None) -> dict:
    """Run one timed window with N tenants and write a manifest. Returns the manifest."""
    out_dir.mkdir(parents=True, exist_ok=True)
    duration = float(coloc.get("duration_s", 120))
    isolation = coloc.get("isolation", "none")

    procs, art_dirs = {}, {}
    # ONE shared t0 for every tenant in this window. Everything downstream is relative to
    # it; without a common clock the traces cannot be checked for overlap.
    t0_ms = time.time() * 1000.0

    for t in tenants:
        target = cfg["targets"][t.target]
        art = out_dir / f"{t.name}.aiperf"
        art_dirs[t.name] = art
        cmd = build_aiperf_cmd(
            base_url=t.base_url, model=t.model, tenant=t, duration_s=duration,
            artifact_dir=art, input_file=_input_file(cfg, t.workload),
            extra_inputs=target.get("extra_inputs"),
            tokenizer=target.get("tokenizer"),
        )
        log = (out_dir / f"{t.name}.driver.log").open("w")
        procs[t.name] = (subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT), log)
        (out_dir / f"{t.name}.cmd").write_text(" ".join(cmd) + "\n")

    warnings: list[str] = []
    for name, (p, log) in procs.items():
        try:
            p.wait(timeout=max(120, duration * 3))
        except subprocess.TimeoutExpired:
            p.kill()
            warnings.append(f"{name}: driver timed out and was killed")
        finally:
            log.close()

    traces, results = {}, {}
    for t in tenants:
        recs = parse_aiperf_records(art_dirs[t.name])
        traces[t.name] = recs
        (out_dir / f"{t.name}.ndjson").write_text(
            "".join(json.dumps(r) + "\n" for r in recs))
        results[t.name] = TenantResult.from_records(
            t, recs, duration_s=duration, colocation_id=coloc_id,
            co_tenants=[o.name for o in tenants if o.name != t.name],
            isolation=isolation,
        ).to_dict()
        if not recs:
            warnings.append(f"{t.name}: no requests recorded — driver or endpoint failed")

    # Overlap is the validity gate for a contention window.
    win = overlap_window(traces) if len(tenants) > 1 else None
    if len(tenants) > 1 and win is None:
        warnings.append(
            "TENANTS DID NOT OVERLAP — this window measured sequential execution; "
            "its degradation ratios are not valid")

    # Offered vs achieved: the safe-operating envelope.
    thr = cfg.get("thresholds", {})
    ratio_gate = float(thr.get("envelope_ratio", 0.95))
    for name, r in results.items():
        ach, off = r["results"]["achieved_rps"], r["configs"]["offered_rps"]
        if ach is not None and off and ach < ratio_gate * off:
            warnings.append(
                f"{name}: achieved {ach:g}/s vs offered {off:g}/s — past the safe envelope")

    manifest = {
        "colocation_id": coloc_id,
        "solo": solo,
        "description": coloc.get("description", ""),
        "duration_s": duration,
        "isolation": isolation,
        "t0_epoch_ms": t0_ms,
        "overlap_window_ms": win,
        "tenants": [{"name": t.name, "target": t.target, "model": t.model,
                     "workload": t.workload,
                     "load": {"pattern": t.load.pattern, "rps": t.load.rps}}
                    for t in tenants],
        "results": results,
        "gpu": sampler.summary() if sampler else {"available": False},
        "warnings": warnings,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def run_colocation(cfg: dict, coloc_id: str, root: Path, *, resume=False,
                   solo_only=False) -> list[dict]:
    """Run solo baselines (as needed) then the contention window."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent / "probes"))
    from gpu_sampler import GpuSampler

    coloc = cfg["colocations"][coloc_id]

    models = {}
    for spec in coloc["tenants"]:
        tname = spec["target"]
        if tname not in models:
            target = cfg["targets"][tname]
            problems = check_required_env(target)
            if problems:
                raise RuntimeError("; ".join(problems))
            models[tname] = resolve_model(target)

    tenants = [_tenant_from_cfg(s, cfg, models) for s in coloc["tenants"]]
    manifests = []

    # ── solo baselines ────────────────────────────────────────────────────────
    if coloc.get("solo_baselines") == "auto" and len(tenants) > 1:
        for t in tenants:
            existing = find_existing_baseline(root / "_baselines", t) if resume else None
            if existing:
                manifests.append(json.loads((existing / "manifest.json").read_text()))
                print(f"  reusing baseline: {existing.name}")
                continue
            d = run_dir_for(root, coloc_id, [t], solo=True)
            print(f"  solo baseline: {t.name} @ {t.load.rps:g} rps -> {d.name}")
            with GpuSampler() as s:
                manifests.append(run_window(cfg, f"{coloc_id}:solo:{t.name}", coloc,
                                            [t], d, solo=True, sampler=s))

    if solo_only:
        return manifests

    # ── contention window ─────────────────────────────────────────────────────
    d = run_dir_for(root, coloc_id, tenants, solo=False)
    print(f"  contention: {', '.join(t.name for t in tenants)} -> {d.name}")
    with GpuSampler() as s:
        manifests.append(run_window(cfg, coloc_id, coloc, tenants, d,
                                    solo=False, sampler=s))
    return manifests
