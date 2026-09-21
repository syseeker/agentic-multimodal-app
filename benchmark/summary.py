"""Build benchmark/results/<gpu>/summary.md from the run manifests.

Two rules carried over deliberately:
  * degradation = contention / solo, computed HERE from the manifests — never stored by
    the runner, so a re-analysis can never disagree with the raw traces.
  * a cause is only stated when knowledge.yaml has one. Otherwise the bullet keeps its
    [TBD] and a human fills it in. The harness does not invent explanations.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
KNOWLEDGE = BENCH_DIR / "knowledge.yaml"


@lru_cache(maxsize=1)
def _knowledge() -> dict:
    if not KNOWLEDGE.is_file():
        return {}
    try:
        import yaml
        with KNOWLEDGE.open() as fh:
            return yaml.safe_load(fh) or {}
    except Exception:
        return {}


def lookup(gpu: str, target: str, symptom: str) -> tuple[str | None, str | None]:
    """(why, how_to_improve) for a (gpu, target, symptom) tuple, or (None, None)."""
    e = ((_knowledge().get(gpu) or {}).get(target) or {}).get(symptom)
    if isinstance(e, dict):
        return e.get("why"), e.get("how_to_improve")
    return None, None


def _phrase(why, how, fb_why, fb_how) -> tuple[str, str]:
    one = lambda s: " ".join(str(s).split()) if s else None
    return (one(why) or fb_why, one(how) or fb_how)


def load_manifests(gpu_dir: Path) -> list[dict]:
    out = []
    for m in sorted(gpu_dir.rglob("manifest.json")):
        try:
            out.append(json.loads(m.read_text()))
        except (OSError, ValueError):
            continue
    return out


def _solo_index(manifests: list[dict]) -> dict[tuple, dict]:
    """key -> that tenant's results, from solo runs only."""
    idx = {}
    for m in manifests:
        if not m.get("solo"):
            continue
        for t in m.get("tenants", []):
            r = (m.get("results") or {}).get(t["name"])
            if r:
                idx[(t["target"], t["model"], t["workload"],
                     t["load"]["pattern"], t["load"]["rps"])] = r
    return idx


def _ratio(contention, solo):
    if contention is None or solo is None or solo == 0:
        return None
    return contention / solo


def _fmt_ratio(v) -> str:
    if v is None:
        return "-"
    if v > 1.05:
        return f"▲{v:.2f}×"
    if v < 0.95:
        return f"▼{v:.2f}×"
    return f"≈{v:.2f}×"


def build(gpu: str, results_root: Path) -> str:
    gpu_dir = results_root / gpu
    manifests = load_manifests(gpu_dir)
    out: list[str] = [f"# Sherlock inference benchmark — {gpu}", ""]

    if not manifests:
        out += ["No runs found. Execute `bench coloc` or `bench run` first.", ""]
        return "\n".join(out)

    solo = _solo_index(manifests)
    coloc_runs = [m for m in manifests if not m.get("solo")]
    out += [f"{len(manifests) - len(coloc_runs)} solo baseline(s), "
            f"{len(coloc_runs)} contention window(s).", ""]

    # ── 1. Decision metrics ───────────────────────────────────────────────────
    out += ["## 1. Decision metrics", "",
            "| run | tenant | model | offered | achieved | e2e p50 | e2e p95 | TTFT p95 | err |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|"]
    for m in manifests:
        for name, r in (m.get("results") or {}).items():
            c, v = r["configs"], r["results"]
            out.append(
                f"| {m['colocation_id']} | {name} | {c['model'] or '-'} | "
                f"{c['offered_rps']:g}/s | "
                f"{v['achieved_rps'] if v['achieved_rps'] is not None else '-'}/s | "
                f"{v['e2e_p50'] or '-'} | {v['e2e_p95'] or '-'} | "
                f"{v['ttft_p95'] or '-'} | {v['error_rate']:.1%} |")
    out.append("")

    # ── 2. Degradation ────────────────────────────────────────────────────────
    if coloc_runs:
        out += ["## 2. Degradation vs solo", "",
                "Ratio of contention to the SAME tenant measured alone at the SAME offered "
                "rate. `▲` = worse under contention.", "",
                "| colocation | tenant | co-tenants | throughput kept | e2e p50 | e2e p95 | TTFT p95 |",
                "|---|---|---|---:|---:|---:|---:|"]
        for m in coloc_runs:
            for t in m.get("tenants", []):
                r = (m.get("results") or {}).get(t["name"])
                if not r:
                    continue
                s = solo.get((t["target"], t["model"], t["workload"],
                              t["load"]["pattern"], t["load"]["rps"]))
                if not s:
                    out.append(f"| {m['colocation_id']} | {t['name']} | "
                               f"{', '.join(r['configs']['co_tenants']) or '-'} | "
                               "no solo baseline | - | - | - |")
                    continue
                sv, cv = s["results"], r["results"]
                out.append(
                    f"| {m['colocation_id']} | {t['name']} | "
                    f"{', '.join(r['configs']['co_tenants']) or '-'} | "
                    f"{_fmt_ratio(_ratio(cv['achieved_rps'], sv['achieved_rps']))} | "
                    f"{_fmt_ratio(_ratio(cv['e2e_p50'], sv['e2e_p50']))} | "
                    f"{_fmt_ratio(_ratio(cv['e2e_p95'], sv['e2e_p95']))} | "
                    f"{_fmt_ratio(_ratio(cv['ttft_p95'], sv['ttft_p95']))} |")
        out.append("")

    # ── 3. GPU / capacity ─────────────────────────────────────────────────────
    out += ["## 3. GPU resource usage", "",
            "| run | VRAM peak | headroom | SM mean | power mean | J/req |",
            "|---|---:|---:|---:|---:|---:|"]
    for m in manifests:
        g = m.get("gpu") or {}
        if not g.get("available"):
            out.append(f"| {m['colocation_id']} | (no sampler) | - | - | - | - |")
            continue
        n_ok = sum(r["results"]["n_ok"] for r in (m.get("results") or {}).values())
        jpr = (round(g["energy_j"] / n_ok, 2)
               if g.get("energy_j") and n_ok else None)
        out.append(
            f"| {m['colocation_id']} | {g.get('vram_peak_gb', '-')} GB | "
            f"{g.get('vram_headroom_gb', '-')} GB | "
            f"{g.get('sm_util_mean_pct', '-')}% | {g.get('power_mean_w', '-')} W | "
            f"{jpr if jpr is not None else '-'} |")
    out.append("")

    # ── 4. Validity ───────────────────────────────────────────────────────────
    # Surfaced as its own section rather than a footnote: a reader who misses these can
    # draw a confident conclusion from a run that measured nothing.
    problems = []
    for m in manifests:
        for w in m.get("warnings", []):
            problems.append((m["colocation_id"], w))
        for name, r in (m.get("results") or {}).items():
            for n in r["results"].get("notes", []):
                problems.append((f"{m['colocation_id']}/{name}", n))
    out += ["## 4. Validity flags", ""]
    if problems:
        out += ["Every item here weakens or invalidates a number above.", ""]
        out += [f"- **{k}** — {v}" for k, v in problems]
    else:
        out.append("None. All windows overlapped, no errors, samples adequate.")
    out.append("")

    # ── 5. Findings ───────────────────────────────────────────────────────────
    out += ["## 5. Core findings", ""]
    worst = None
    for m in coloc_runs:
        for t in m.get("tenants", []):
            r = (m.get("results") or {}).get(t["name"])
            s = solo.get((t["target"], t["model"], t["workload"],
                          t["load"]["pattern"], t["load"]["rps"]))
            if not r or not s:
                continue
            ratio = _ratio(r["results"]["e2e_p95"], s["results"]["e2e_p95"])
            if ratio and (worst is None or ratio > worst[0]):
                worst = (ratio, t["target"], t["name"], m["colocation_id"])
    if worst:
        why, how = lookup(gpu, worst[1], "contention_degradation")
        why_t, how_t = _phrase(
            why, how,
            "[TBD — memory bandwidth, SM contention, or KV-cache pressure?]",
            "[TBD — cap gpu_memory_utilization, lower the co-tenant rate, or move it off-card]")
        out.append(f"- **Worst degradation:** `{worst[2]}` in `{worst[3]}` at "
                   f"{worst[0]:.2f}× solo e2e p95. **Why:** {why_t} "
                   f"**How to improve:** {how_t}")
    else:
        out.append("- No paired solo/contention data yet — run `bench coloc` with "
                   "`solo_baselines: auto`.")
    out.append("")
    return "\n".join(out)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--gpu", default="rtx_pro6000")
    ap.add_argument("--results-dir", default=str(BENCH_DIR / "results"))
    a = ap.parse_args()
    root = Path(a.results_dir)
    text = build(a.gpu, root)
    dest = root / a.gpu / "summary.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text)
    print(f"wrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
