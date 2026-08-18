#!/usr/bin/env python3
"""`bench` — Sherlock inference benchmark CLI.

    bench check    --gpu rtx_pro6000     # are the Phase 1-8 services measurable?
    bench workloads                       # regenerate inputs from data/cases/
    bench coloc    --gpu rtx_pro6000 --colocation vlm-meralion [--all] [--resume]
    bench summary  --gpu rtx_pro6000

Every command takes --json and prints exactly one status line to stdout in that mode, so a
calling agent can branch on it. Exit codes: 0 ok, 1 generic, 3 runtime, 4 missing dep.

THIS TOOL NEVER LAUNCHES A MODEL. Phases 1-8 deploy the stack; Phase 9 only measures it.
If a service is down, `bench check` names the phase script that brings it up and stops —
starting things here would mean benchmarking a configuration nobody deployed.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import (EXIT_GENERIC, EXIT_MISSING_DEP, EXIT_OK, EXIT_RUNTIME, RESULTS_ROOT,
                 check_required_env, emit, have, load_config, resolve_model)

# Which phase script deploys each target — printed when something is not reachable.
OWNED_BY = {
    "vlm": "deploy/phase5_vss.sh (then deploy/patch_vss_rtvi_vlm.sh)",
    "meralion": "deploy/phase4_audio.sh — the MERaLiON service must be running",
    "rag": "deploy/phase2_rag.sh",
}


def _http_ok(url: str, timeout: int = 10) -> bool:
    return subprocess.run(["curl", "-sf", "-m", str(timeout), "-o", "/dev/null", url],
                          capture_output=True).returncode == 0


# ── check ─────────────────────────────────────────────────────────────────────
def cmd_check(a):
    cfg = load_config(a.gpu)
    data, problems = {"targets": {}}, []

    if not have("aiperf"):
        problems.append("aiperf not installed — pip install 'aiperf>=0.10'")
    if not have("nvidia-smi"):
        problems.append("nvidia-smi unavailable — no GPU numbers can be collected")

    for name, t in cfg["targets"].items():
        info = {"serving": t["serving"], "base_url": t["base_url"], "up": False}
        health = t["base_url"].rstrip("/") + t.get("health", "/health")
        info["up"] = _http_ok(health)
        if not info["up"]:
            problems.append(f"{name}: not reachable at {health} — deploy it with "
                            f"{OWNED_BY.get(name, 'its phase script')}. "
                            f"bench does not start services.")
        else:
            # Refuses proxy mode: benchmarking it would measure the remote endpoint.
            env_problems = check_required_env(t)
            problems.extend(f"{name}: {p}" for p in env_problems)
            if not env_problems and t["serving"] == "openai_chat":
                try:
                    info["model"] = resolve_model(t)
                except Exception as e:
                    problems.append(f"{name}: could not resolve model id — {e}")
        data["targets"][name] = info

    if problems:
        emit(command="check", status="error", data=data,
             error={"code": EXIT_RUNTIME, "remediation": " | ".join(problems)},
             json_out=a.json, exit_code=EXIT_RUNTIME)
    emit(command="check", status="ok", data=data,
         next_action=f"{len(data['targets'])} target(s) measurable",
         json_out=a.json)


# ── workloads ─────────────────────────────────────────────────────────────────
def cmd_workloads(a):
    script = Path(__file__).resolve().parent / "build_workloads.py"
    res = subprocess.run([sys.executable, str(script)], capture_output=a.json, text=True)
    if res.returncode != 0:
        emit(command="workloads", status="error",
             error={"code": EXIT_GENERIC, "remediation": (res.stderr or "failed")[:400]},
             json_out=a.json, exit_code=EXIT_GENERIC)
    wl = Path(__file__).resolve().parent / "workloads"
    emit(command="workloads", status="ok",
         artifacts=sorted(str(p) for p in wl.glob("*")),
         next_action="workloads regenerated from data/cases/", json_out=a.json)


# ── coloc ─────────────────────────────────────────────────────────────────────
def cmd_coloc(a):
    import coloc as coloc_mod

    cfg = load_config(a.gpu)
    names = list(cfg["colocations"]) if a.all else (a.colocation or [])
    if not names:
        emit(command="coloc", status="error",
             error={"code": EXIT_GENERIC,
                    "remediation": f"pass --colocation or --all. Available: "
                                   f"{', '.join(cfg['colocations'])}"},
             json_out=a.json, exit_code=EXIT_GENERIC)

    unknown = [n for n in names if n not in cfg["colocations"]]
    if unknown:
        emit(command="coloc", status="error",
             error={"code": EXIT_GENERIC, "remediation": f"unknown colocation(s): {unknown}"},
             json_out=a.json, exit_code=EXIT_GENERIC)

    if a.dry_run:
        plan = {n: [t["name"] for t in cfg["colocations"][n]["tenants"]] for n in names}
        emit(command="coloc", status="ok", data={"plan": plan},
             next_action=f"{len(names)} colocation(s) would run", json_out=a.json)

    if not have("aiperf"):
        emit(command="coloc", status="error",
             error={"code": EXIT_MISSING_DEP,
                    "remediation": "aiperf not installed — pip install 'aiperf>=0.10'"},
             json_out=a.json, exit_code=EXIT_MISSING_DEP)

    root = RESULTS_ROOT / a.gpu / "coloc"
    root.mkdir(parents=True, exist_ok=True)
    done, failed = [], []
    for n in names:
        print(f"== {n} ==", file=sys.stderr)
        try:
            ms = coloc_mod.run_colocation(cfg, n, root, resume=a.resume,
                                          solo_only=a.solo_only)
            done.append({"colocation": n, "windows": len(ms),
                         "warnings": sum(len(m.get("warnings", [])) for m in ms)})
        except Exception as e:
            failed.append({"colocation": n, "error": str(e)})
            if not a.continue_on_error:
                emit(command="coloc", status="error", data={"done": done, "failed": failed},
                     error={"code": EXIT_RUNTIME, "remediation": str(e)},
                     json_out=a.json, exit_code=EXIT_RUNTIME)

    if not a.no_summary:
        subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "summary.py"),
                        "--gpu", a.gpu], capture_output=a.json)

    warn_total = sum(d["warnings"] for d in done)
    emit(command="coloc",
         status="error" if failed else "ok",
         data={"done": done, "failed": failed},
         artifacts=[str(RESULTS_ROOT / a.gpu / "summary.md")],
         error={"code": EXIT_RUNTIME, "remediation": f"{len(failed)} failed"} if failed else None,
         next_action=(f"{len(done)} colocation(s); {warn_total} validity warning(s) — "
                      f"read section 4 of summary.md"),
         json_out=a.json, exit_code=EXIT_RUNTIME if failed else EXIT_OK)


# ── summary ───────────────────────────────────────────────────────────────────
def cmd_summary(a):
    res = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent / "summary.py"),
         "--gpu", a.gpu], capture_output=a.json, text=True)
    dest = RESULTS_ROOT / a.gpu / "summary.md"
    if res.returncode != 0:
        emit(command="summary", status="error",
             error={"code": EXIT_GENERIC, "remediation": (res.stderr or "failed")[:400]},
             json_out=a.json, exit_code=EXIT_GENERIC)
    emit(command="summary", status="ok", artifacts=[str(dest)],
         next_action=f"wrote {dest}", json_out=a.json)


def main() -> int:
    p = argparse.ArgumentParser(prog="bench", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--gpu", default="rtx_pro6000")
        sp.add_argument("--json", action="store_true",
                        help="emit one JSON status line to stdout")
        return sp

    common(sub.add_parser("check", help="verify the Phase 1-8 stack is measurable")
           ).set_defaults(fn=cmd_check)

    w = sub.add_parser("workloads", help="regenerate inputs from data/cases/")
    w.add_argument("--json", action="store_true")
    w.set_defaults(fn=cmd_workloads)

    c = common(sub.add_parser("coloc", help="run contention windows"))
    c.add_argument("--colocation", action="append")
    c.add_argument("--all", action="store_true")
    c.add_argument("--solo-only", action="store_true")
    c.add_argument("--dry-run", action="store_true")
    c.add_argument("--resume", action="store_true",
                   help="reuse matching solo baselines instead of re-measuring")
    c.add_argument("--continue-on-error", action="store_true")
    c.add_argument("--no-summary", action="store_true")
    c.set_defaults(fn=cmd_coloc)

    common(sub.add_parser("summary", help="regenerate summary.md")).set_defaults(fn=cmd_summary)

    a = p.parse_args()
    try:
        a.fn(a)
    except SystemExit:
        raise
    except Exception as e:
        emit(command=a.cmd, status="error",
             error={"code": EXIT_GENERIC, "remediation": str(e)},
             json_out=getattr(a, "json", False), exit_code=EXIT_GENERIC)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
