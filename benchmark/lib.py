"""Core contracts for the Sherlock inference benchmark.

Deliberately small. The structure is borrowed from inference-pipeline-benchmark, trimmed to
what Sherlock has: three HTTP targets and one GPU. Dropped as unnecessary here: transport
dispatch (everything is HTTP), Triton, multi-device placement, extends/vary/repetitions.

Four things are kept exactly, because they are what make contention numbers mean anything:
  1. ONE SHARED t0 across tenants, with a post-hoc overlap check.
  2. OPEN-LOOP load only (--request-rate + arrival pattern), never --concurrency.
  3. solo_key includes the offered load, so a baseline is only reused at the same rate.
  4. degradation = contention / solo, computed at ANALYSIS time from the manifests.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(__file__).resolve().parent / "config"
RESULTS_ROOT = Path(__file__).resolve().parent / "results"

EXIT_OK = 0
EXIT_GENERIC = 1
EXIT_RUNTIME = 3
EXIT_MISSING_DEP = 4


# ── CLI status contract ───────────────────────────────────────────────────────
def emit(*, command, status, data=None, artifacts=None, next_action=None,
         error=None, json_out=False, exit_code=EXIT_OK):
    """Print a one-line JSON status (or a human line) and exit.

    In --json mode this is the ONLY thing on stdout, so a calling agent can branch on it.
    """
    payload = {
        "status": status,                 # ok | error | skipped
        "command": command,
        "next_action": next_action,
        "artifacts": [str(a) for a in (artifacts or [])],
        "error": error,                   # {"code": int, "remediation": str} | None
        "data": data or {},
    }
    if json_out:
        print(json.dumps(payload, default=str))
    else:
        if status == "ok":
            print(f"[ok] {command}: {next_action or 'done'}")
        elif status == "skipped":
            print(f"[skip] {command}: {next_action or '-'}")
        else:
            print(f"[error] {command}: {(error or {}).get('remediation', 'see logs')}")
        for a in payload["artifacts"]:
            print(f"  - {a}")
    raise SystemExit(exit_code)


# ── Config ────────────────────────────────────────────────────────────────────
def load_config(gpu: str) -> dict:
    import yaml
    p = CONFIG_DIR / f"{gpu}.yaml"
    if not p.is_file():
        raise FileNotFoundError(f"no config for gpu={gpu!r}: {p}")
    with p.open() as fh:
        return yaml.safe_load(fh) or {}


def resolve_model(target: dict) -> str:
    """Model id, discovered from the server when the config says to.

    The VLM's id must come from /v1/models: phase5_vss.sh deploys cosmos-reason1-7b while
    vss_sherlock_mcp.py asks for the cosmos-reason2-8b NIM name, so no config file is
    trustworthy here. The server is the only authority.
    """
    if target.get("model"):
        return target["model"]
    src = target.get("model_from")
    if not src:
        raise ValueError("target has neither `model` nor `model_from`")
    url = target["base_url"].rstrip("/") + src
    out = subprocess.run(["curl", "-sf", "-m", "10", url], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"could not read {url}")
    data = json.loads(out.stdout).get("data") or []
    if not data:
        raise RuntimeError(f"{url} returned no models")
    return data[0]["id"]


def check_required_env(target: dict) -> list[str]:
    """Enforce `require_env`. Returns a list of problems (empty == fine).

    Exists for one case: rtvi-vlm in `openai-compat` mode holds no weights and proxies to a
    remote endpoint, so benchmarking it measures the internet rather than the GPU.
    """
    problems = []
    ctr = target.get("container")
    for var, expect in (target.get("require_env") or {}).items():
        if not ctr:
            continue
        got = subprocess.run(["docker", "exec", ctr, "printenv", var],
                             capture_output=True, text=True).stdout.strip()
        if expect.startswith("!"):
            if got == expect[1:]:
                problems.append(f"{ctr}: {var}={got} is disallowed for benchmarking")
        elif got != expect:
            problems.append(f"{ctr}: {var}={got!r}, expected {expect!r}")
    return problems


# ── Load spec ─────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Load:
    pattern: str = "poisson"
    rps: float = 1.0
    output_tokens: int | None = None

    @property
    def is_open_loop(self) -> bool:
        return self.rps is not None and self.rps > 0


@dataclass(frozen=True)
class Tenant:
    name: str
    target: str
    workload: str
    load: Load
    model: str = ""
    base_url: str = ""


def solo_key(t: Tenant) -> tuple:
    """Identity of a solo baseline.

    Load is PART OF THE KEY on purpose: a baseline is only valid at the same offered rate.
    Dividing a 4 rps contention result by a 1 rps baseline invents degradation that is not
    there — the tenant was simply asked to do more work.
    """
    return (t.target, t.model, t.workload, t.load.pattern, t.load.rps)


def solo_key_from_manifest(m: dict) -> tuple | None:
    t = (m.get("tenants") or [{}])[0]
    if not t:
        return None
    return (t.get("target"), t.get("model"), t.get("workload"),
            (t.get("load") or {}).get("pattern"), (t.get("load") or {}).get("rps"))


# ── aiperf ────────────────────────────────────────────────────────────────────
def build_aiperf_cmd(*, base_url, model, tenant: Tenant, duration_s, artifact_dir,
                     input_file=None, extra_inputs=None, warmup=10, seed=0,
                     endpoint_type="chat", tokenizer=None) -> list[str]:
    """Open-loop by construction: --request-rate + --arrival-pattern, never --concurrency.

    Closed-loop concurrency throttles itself when the server slows down, which conceals
    exactly the degradation a contention run exists to measure.
    """
    if not tenant.load.is_open_loop:
        raise ValueError(f"tenant {tenant.name!r} has no open-loop rate")
    root = base_url.rstrip("/")
    if root.endswith("/v1"):          # aiperf wants the server root, not /v1
        root = root[:-3].rstrip("/")
    cmd = [
        "aiperf", "profile",
        "--url", root,
        "--model", model,
        "--endpoint-type", endpoint_type,
        "--request-rate", str(tenant.load.rps),
        "--arrival-pattern", tenant.load.pattern,
        "--benchmark-duration", str(duration_s),
        "--warmup-request-count", str(warmup),
        "--random-seed", str(seed),
        "--output-artifact-dir", str(artifact_dir),
        "--ui", "none",
        # Without --streaming aiperf emits neither TTFT nor ITL, and the degradation
        # ratio for time-to-first-token becomes uncomputable.
        "--streaming",
    ]
    if tenant.load.output_tokens is not None:
        cmd += ["--extra-inputs", f"max_tokens:{tenant.load.output_tokens}"]
    for k, v in (extra_inputs or {}).items():
        cmd += ["--extra-inputs", f"{k}:{v}"]
    if input_file:
        cmd += ["--input-file", str(input_file), "--custom-dataset-type", "single_turn"]
    # aiperf loads a HuggingFace tokenizer for client-side token counting, defaulting to
    # --model. That breaks for the VLM: its served id is an NGC NIM artifact name
    # (nim_<org>_<model>_<tag>), not a HF repo, so the fetch 401s and aiperf exits before
    # issuing a single request -- the run "completes" with n_requests=0. Prefer an explicit
    # per-target `tokenizer:`; otherwise let the server report token counts, which is valid
    # because every workload here is file-based (never synthetic prompts).
    if tokenizer:
        cmd += ["--tokenizer", tokenizer]
    else:
        cmd += ["--use-server-token-count"]
    return cmd


def parse_aiperf_records(artifact_dir: Path) -> list[dict]:
    """Read aiperf's per-request export into our ndjson shape on the shared epoch clock.

    Two schemas are supported. aiperf <=0.10 wrote flat records (`timestamp`,
    `response_timestamps`, ...). aiperf 0.11 writes `{"metadata": {...}, "metrics": {...}}`
    with ns epoch stamps in metadata and pre-computed millisecond metrics. Silently
    returning [] on the newer shape is what made a run of 233 successful requests report
    n_requests=0, so handle both explicitly rather than assuming a version.
    """
    src = Path(artifact_dir) / "profile_export.jsonl"
    if not src.is_file():
        return []
    recs = []
    for line in src.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue

        md, mx = d.get("metadata"), d.get("metrics")
        if isinstance(md, dict) and isinstance(mx, dict):
            # aiperf 0.11 nested schema
            def _m(name):
                v = mx.get(name)
                return v.get("value") if isinstance(v, dict) else v
            t0 = md.get("request_start_ns")
            t1 = md.get("request_end_ns")
            if t0 is None:
                continue
            cancelled = bool(md.get("was_cancelled"))
            ttft = _m("time_to_first_token")
            if ttft is None:
                ttft = _m("time_to_first_output_token")
            e2e = _m("request_latency")
            recs.append({
                "t_start_ms": t0 / 1e6,
                "t_end_ms": (t1 / 1e6) if t1 is not None else None,
                "ttft_ms": ttft,
                "e2e_ms": e2e,
                "output_tokens": _m("output_token_count") or _m("output_sequence_length"),
                "ok": (not cancelled) and t1 is not None,
                "error": None,
            })
            continue

        # legacy flat schema (aiperf <= 0.10)
        ts = d.get("timestamp")
        if ts is None:
            continue
        t_start = ts / 1e6
        resp = d.get("response_timestamps") or []
        t_end = (resp[-1] / 1e6) if resp else None
        ttft = ((resp[0] - ts) / 1e6) if resp else None
        recs.append({
            "t_start_ms": t_start,
            "t_end_ms": t_end,
            "ttft_ms": ttft,
            "e2e_ms": (t_end - t_start) if t_end else None,
            "output_tokens": d.get("output_token_count"),
            "ok": bool(resp) and not d.get("error"),
            "error": d.get("error"),
        })
    return recs


# ── Result record ─────────────────────────────────────────────────────────────
def _pct(vals: list[float], q: float):
    if not vals:
        return None
    s = sorted(vals)
    i = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return round(s[i], 2)


@dataclass
class TenantResult:
    """One tenant's measured behaviour in one window.

    Split on serialisation into {configs, results}: configs describe what was asked for,
    results what happened. achieved_rps is a RESULT — it is the thing offered_rps is
    tested against.
    """
    # configs
    name: str = ""
    target: str = ""
    model: str = ""
    workload: str = ""
    arrival_pattern: str = ""
    offered_rps: float = 0.0
    colocation_id: str = ""
    co_tenants: list[str] = field(default_factory=list)
    isolation: str = "none"
    duration_s: float = 0.0
    # results
    n_requests: int = 0
    n_ok: int = 0
    error_rate: float = 0.0
    achieved_rps: float | None = None
    ttft_p50: float | None = None
    ttft_p95: float | None = None
    e2e_p50: float | None = None
    e2e_p95: float | None = None
    e2e_p99: float | None = None
    output_tokens_mean: float | None = None
    notes: list[str] = field(default_factory=list)

    _CONFIG = {"name", "target", "model", "workload", "arrival_pattern", "offered_rps",
               "colocation_id", "co_tenants", "isolation", "duration_s"}

    @classmethod
    def from_records(cls, tenant: Tenant, recs: list[dict], *, duration_s, colocation_id,
                     co_tenants, isolation) -> "TenantResult":
        ok = [r for r in recs if r.get("ok")]
        e2e = [r["e2e_ms"] for r in ok if r.get("e2e_ms") is not None]
        ttft = [r["ttft_ms"] for r in ok if r.get("ttft_ms") is not None]
        toks = [r["output_tokens"] for r in ok if r.get("output_tokens")]
        r = cls(
            name=tenant.name, target=tenant.target, model=tenant.model,
            workload=tenant.workload, arrival_pattern=tenant.load.pattern,
            offered_rps=tenant.load.rps, colocation_id=colocation_id,
            co_tenants=co_tenants, isolation=isolation, duration_s=duration_s,
            n_requests=len(recs), n_ok=len(ok),
            error_rate=round(1 - len(ok) / len(recs), 4) if recs else 0.0,
            achieved_rps=round(len(ok) / duration_s, 3) if duration_s else None,
            ttft_p50=_pct(ttft, 0.50), ttft_p95=_pct(ttft, 0.95),
            e2e_p50=_pct(e2e, 0.50), e2e_p95=_pct(e2e, 0.95), e2e_p99=_pct(e2e, 0.99),
            output_tokens_mean=round(sum(toks) / len(toks), 1) if toks else None,
        )
        # State the limits of the sample rather than leaving a reader to infer them.
        if len(ok) < 50:
            r.notes.append(f"p99 unreliable: only {len(ok)} successful requests (< 50)")
        if r.ttft_p50 is not None and r.ttft_p50 < 1:
            r.notes.append("TTFT p50 < 1 ms — measurement bug, not a fast model")
        if r.error_rate > 0:
            r.notes.append(f"error_rate {r.error_rate:.1%} — results are suspect")
        return r

    def to_dict(self) -> dict:
        flat = asdict(self)
        return {"configs": {k: v for k, v in flat.items() if k in self._CONFIG},
                "results": {k: v for k, v in flat.items() if k not in self._CONFIG}}


# ── Overlap verification ──────────────────────────────────────────────────────
def overlap_window(traces: dict[str, list[dict]]) -> tuple[float, float] | None:
    """The window during which ALL tenants had requests in flight.

    Returns None when they never actually overlapped — in which case the run measured
    sequential execution and its degradation ratios are meaningless. Callers must treat
    None as "flag the run", never as "assume it was fine".
    """
    starts, ends = [], []
    for recs in traces.values():
        ts = [r["t_start_ms"] for r in recs if r.get("t_start_ms")]
        te = [r["t_end_ms"] for r in recs if r.get("t_end_ms")]
        if not ts or not te:
            return None
        starts.append(min(ts))
        ends.append(max(te))
    if not starts:
        return None
    lo, hi = max(starts), min(ends)
    return (lo, hi) if lo < hi else None


def have(binary: str) -> bool:
    return shutil.which(binary) is not None
