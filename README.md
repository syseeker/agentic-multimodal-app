# Agentic Multimodal App

A **customer-neutral reference implementation** showing how to turn a *linear, click-through* LLM application into an **agentic, multimodal** one — built end-to-end on the **NVIDIA software stack**.

It ships with **Socrates**, an example agent persona: a forensic co-worker that ingests **photos**, **audio statements**, and **chat text**, then performs **entity recognition → relationship-graph building → sentiment / paralinguistic analysis**, always with a human-in-the-loop for accountability. Socrates is just a configuration — swap the prompt, tools, and schema to retarget the same skeleton at any domain.

> This repo is *built on* NVIDIA Blueprints and SDKs (AI-Q deep-research pattern, NeMo Agent Toolkit, NeMo Guardrails, NIM/vLLM, NeMo Retriever, RAPIDS cuVS/cuGraph). It is **not** itself an official NVIDIA Blueprint.

---

## Two personas

| Persona | What they do | Where to look |
|---|---|---|
| **Developer** | Learn the *method*: drive Claude Code + NVIDIA skills to assemble an agentic app from NVIDIA building blocks. | [`docs/METHOD.md`](docs/METHOD.md) |
| **User** | Talk to **Socrates** in the UI; upload case assets; approve each agent step; read a cited report with an interactive relationship graph. | [`ui/`](ui/) |

---

## Architecture (short)

```
UI (Svelte) ─▶ Agent Orchestrator (AI-Q pattern: Planner / Investigator / Critic)
                 engine = deepagents (primary) | Hermes (alt)
                 │
                 ├─ tools: image-extract (Qwen3-VL) · audio-extract (MERaLiON-3)
                 │         text-extract (Qwen3) · graph-build (FalkorDB + cuGraph)
                 │         rag (Milvus/cuVS + NeMo Retriever) · sentiment
                 └─ NeMo Guardrails wrap every step (citations, HITL, topic/output)

Serving: vLLM FP8 (ModelOpt)   Obs: NeMo Agent Toolkit → Phoenix/OTLP   Profiling: aiperf + Nsight
```

Full detail: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Quickstart

Full step-by-step (offline checks, full GPU stack, GB10 deploy, **5 demo cases**,
troubleshooting): **[QUICKSTART.md](QUICKSTART.md)**.

TL;DR — requires Docker + the NVIDIA Container Toolkit on a Blackwell-class GPU:

```bash
git clone <this-repo> agentic-multimodal-app
cd agentic-multimodal-app
cp .env.example .env          # set GPU_PROFILE, verify model tags, add tokens if needed
docker compose up --build     # brings up serving + app + ui + milvus + falkordb
```

Then open the UI at `http://localhost:5173`, walk the committed sample case, and watch Socrates plan and execute. No GPU? Run `pytest tests/ -q` for the offline checks (see Path A in the quickstart).

CLI (no UI):
```bash
docker compose run --rm app ama run --case data/sample_case
```

A ready-to-run, text-only sample case is committed at [`data/sample_case/`](data/sample_case/).
Add image + audio assets with `python data/download.py` and `python data/generate.py`.

### Hardware profiles
- **Dev:** `GPU_PROFILE=rtx6000` — RTX PRO 6000 Blackwell (96 GB, x86_64). All 3 models at FP8 (~49 GB).
- **Deploy:** `GPU_PROFILE=gb10` — GB10 / DGX Spark (128 GB unified, arm64/sbsa). See [`docs/DEPLOY_GB10.md`](docs/DEPLOY_GB10.md).

Sizing math: [`docs/GPU_SIZING.md`](docs/GPU_SIZING.md).

---

## Repository layout

```
serving/        vLLM FP8 launch + ModelOpt recipes, GPU-profile switch
app/            agent app: config, engines, tools, graph, guardrails
ui/             SvelteKit UI (chat, upload, graph viz, HITL approvals)
data/           mock case generator + public-dataset downloaders
observability/  NeMo Agent Toolkit + Phoenix/OTLP (P1)
benchmark/      aiperf + Nsight harness (P1)
deploy/         Helm chart + GB10 compose overlay
docs/           METHOD, ARCHITECTURE, GPU_SIZING, DEPLOY_GB10
```

## Status

Built in priority tiers (see the plan): **P0** vertical slice (serving → tools → orchestrator → UI) → **P0.5** mock data → **P1** observability, benchmarking, guardrails, Hermes alt engine, evaluation.

## License

Apache-2.0. Model weights (Qwen, MERaLiON) carry their own licenses — review before commercial use. MERaLiON uses the custom MERaLiON Public License.
