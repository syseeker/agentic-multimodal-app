# Phase 9a / Track 2a — Phoenix on-premise observability

**Status:** ✅ complete and verified on GB10 / DGX Spark (aarch64), 2026-08-29
**Script:** `deploy/phase9a_observability.sh`
**Developer quickstart:** `QUICKSTART_TRACK2.md`
**Plan this implements:** `deploy/PHASE9_PLAN.md` §9a — *corrected in three places, see below*

---

## Goal

Every Sherlock query produces a visible trace showing agent steps, tool calls, token
counts and latency — with no changes to agent code.

## Outcome

Achieved with **configuration only**: a 6-line `general.telemetry.tracing` block plus a
Phoenix container. AI-Q is built on the NeMo Agent Toolkit, whose Dask job runner already
builds an `ExporterManager` from exactly this YAML (`aiq_api/jobs/runner.py`). NVIDIA ships
the identical block in VSS 3.2.0's own `vss-agent/configs/config.yml`.

Verified trace tree from a live forensic query
("Who is the named suspect in case SC-2024-22DEEE33?"):

```
span kinds: {'CHAIN': 8, 'LLM': 3, 'TOOL': 2}

CHAIN  <workflow>
CHAIN  shallow_research_agent
LLM    nvidia/nemotron-3-nano-30b-a3b   prompt=4338 completion=1348 total=5686
TOOL   mcp_sherlock_tools__graph_query_tool
LLM    nvidia/nemotron-3-nano-30b-a3b   prompt=4033 completion=777
TOOL   mcp_sherlock_tools__graph_query_tool
LLM    nvidia/nemotron-3-nano-30b-a3b   prompt=3948 completion=529
```

## Design decisions

### 1. Dedicated `amms-phoenix`, not VSS's `phoenix`

VSS 3.2.0 already runs a Phoenix (`external/vss-3.2.0/deploy/docker/services/infra/compose.yml`),
published on host **6006**. We deploy a second one on **6007** anyway:

- `amms-aiq-agent` is on `amms_aiq-network` + `nvidia-rag`, **not** `mdx_default`, so it
  cannot reach VSS's Phoenix by container name at all.
- VSS's Phoenix is destroyed by `dev-profile.sh down` / `deploy/stop_all.sh`. Sherlock
  observability must not have a VSS lifecycle dependency.
- Track 2 has to work on a box where Phase 5 was never deployed (GB10 today).
- `arizephoenix/phoenix:14.15.0` is multi-arch, so this is cross-arch safe (CLAUDE.md rule 9).

Rejected alternative: `docker network connect mdx_default amms-aiq-agent`. It works but
permanently couples the two stacks, and VSS already writes its own traces into that
Phoenix under project `DEV-vss-agent-3.2.0`.

### 2. `docker restart`, never `--force-recreate`

The config is a **read-only bind mount** (`external/aiq/configs` → `/app/configs`) read
once at process start.

| Command | Effect |
|---|---|
| `docker compose up -d aiq-agent` | **no-op** — config hash unchanged, YAML never re-read |
| `docker compose up -d --force-recreate` | applies it, but **drops the `nvidia-rag` network** (RAG search then silently returns nothing — see implementation-learnings.md "Fix 5") and **wipes the `runner.py` ContextVar patch** |
| `docker restart amms-aiq-agent` | ✅ re-reads YAML, keeps both networks, keeps the patch |

### 3. Both config variants carry the block

`start_all.sh:263` and `phase7_extensions.sh:91` both `cp` the repo's
`config_sherlock_frag_mcp.yml` over `external/aiq/configs/config_sherlock_frag.yml`.
An edit made only in `external/` survives until the next `start_all.sh`, then vanishes
silently. Both repo-source configs therefore carry an identical tracing block, and
`phase9a_observability.sh` re-materialises whichever matches the running stack.

---

## Corrections to PHASE9_PLAN.md §9a

The plan was written before implementation. Three things in it are wrong:

| Plan says | Reality |
|---|---|
| `endpoint: http://localhost:6006/v1/traces` | Wrong for the containerised deployment — `localhost` inside `amms-aiq-agent` is the agent itself. Use `http://amms-phoenix:6006/v1/traces`. |
| Start Phoenix with `python -m phoenix.server.main serve` inside `external/aiq` | The AI-Q image has **no shell and no `phoenix` package**. Phoenix runs as its own container. |
| Restart via `phase7_extensions.sh restart-aiq` | No such subcommand. Use `docker restart amms-aiq-agent`. |

---

## Verified exporter schema

`_type: phoenix` (registered at `nat/plugins/phoenix/register.py`) accepts **exactly**
these fields. There is no `headers`, no `protocol`, no `resource_attributes`.

| Field | Type | Default | |
|---|---|---|---|
| `project` | str | — | **required** |
| `endpoint` | str | — | **required**, must end `/v1/traces` |
| `batch_size` | int | 100 | |
| `flush_interval` | float | 5.0 | seconds — why traces lag ~5s |
| `max_queue_size` | int | 1000 | |
| `drop_on_overflow` | bool | false | |
| `shutdown_timeout` | float | 10.0 | |
| `timeout` | float | 30.0 | HTTP timeout to Phoenix |

Transport is **OTLP over HTTP only** — it hard-wires `phoenix.otel.HTTPSpanExporter`, so
the gRPC port 4317 is not an option.

Validate a block without restarting anything:

```bash
docker exec amms-aiq-agent /app/.venv/bin/python -c "
import yaml
from nat.runtime.loader import PluginTypes, discover_and_register_plugins
discover_and_register_plugins(PluginTypes.ALL)
from nat.data_models.config import TelemetryConfig
TelemetryConfig.rebuild_annotations()
print(TelemetryConfig.model_validate(yaml.safe_load('''
tracing:
  phoenix:
    _type: phoenix
    endpoint: http://amms-phoenix:6006/v1/traces
    project: sherlock
''')).tracing['phoenix'].model_dump(by_alias=True))"
```

---

## Caveats

- **`/v1/traces` suffix is mandatory.** Without it: agent works fine, Phoenix stays empty,
  one `Failed to export span batch code: 405` in the logs. The most expensive silent failure here.
- **Never use bare hostname `phoenix`** from the agent — corporate DNS resolves it to
  `phoenix.nvidia.com` (10.31.52.19) when no local alias claims it. Compose does register a
  `phoenix` alias for `amms-phoenix` on `amms_aiq-network` (derived from the service key),
  but do not depend on it; always write `amms-phoenix`.
- **`force_flush() == True` is not proof of delivery.** It returns True even on HTTP 405.
  The pass criterion must be Phoenix's own span count — which step 5 of the script uses.
- **Every MCP tool call yields TWO spans** with the same name (one `TOOL` from the LangChain
  callback handler, one `CHAIN` from NAT's `Function.ainvoke` wrapper). They are parent/child
  ~1ms apart — not double-counted latency.
- **Token counts appear only on `LLM` spans**, and only for agents registered with
  `framework_wrappers=[LLMFrameworkEnum.LANGCHAIN]`. All Sherlock agents are; a hand-written
  function shows a CHAIN span with zeros.
- **The Sherlock MCP server's own LLM calls are NOT traced.** `graph/tools.py`'s
  `extract_entities` runs inside `amms-sherlock-mcp`, a separate process, and NAT's MCP
  client does not propagate `traceparent`. Instrumenting it needs openinference's OpenAI
  instrumentor inside that container — deliberately out of scope for this MVP, and note
  `mcp/vss_sherlock_mcp.py` uses raw `httpx` so it would not be covered by that anyway.
- **`weave` is documented in AI-Q's `observability.md` but is NOT installed** in this image.
  That YAML will fail validation.
- Leftover probe projects (`sherlock-dnscheck`, `sherlock-mcp-probe`, `verify-amms`) exist in
  Phoenix from verification. Phoenix 14.15.0's `deleteProject` GraphQL mutation errors;
  delete them from the UI if you want a clean slate.

---

## Production / air-gapped path (not deployed)

For STE MSS, replace the Phoenix exporter with AI-Q's own redacting OTEL exporter
(registered from `/app/src/aiq_agent/observability/otel_header_redaction_exporter.py`,
**not** from NAT). **PII redaction is mandatory for forensic case data.**

```yaml
tracing:
  otel:
    _type: otelcollector_redaction
    project: sherlock-production
    endpoint: http://otel-collector:4318/v1/traces
    redaction_enabled: true
    redaction_attributes: [input.value, output.value, nat.metadata]
    redaction_value: "[REDACTED]"
```

The plain NAT `_type: otelcollector` has no redaction fields at all.
