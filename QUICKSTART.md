# Quickstart

Get Socrates running and walk a case end-to-end. Three paths, easiest first.

- [Path A — no GPU: offline checks](#path-a--no-gpu-offline-checks) (2 min)
- [Path B — full stack on a GPU box](#path-b--full-stack-on-a-gpu-box) (the demo)
- [Path C — deploy to GB10](#path-c--deploy-to-gb10)
- [Demo cases — the agentic showcase](#demo-cases--the-agentic-showcase)

---

## Prerequisites

| Path | Needs |
|---|---|
| A | Python 3.11+ (3.10 works for the offline tests) |
| B | Docker + [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html), a Blackwell-class GPU (RTX PRO 6000 / GB10), ~60 GB free VRAM at FP8 |
| C | A GB10 / DGX Spark (arm64) + a registry for multi-arch images |

Hugging Face access for the model weights (`HF_TOKEN` if any are gated). Model
picks + precisions are documented in [docs/MODELS.md](docs/MODELS.md).

---

## Path A — no GPU: offline checks

Validates the schemas, the cuGraph→NetworkX analytics fallback, and the eval
scorer. No models, no Docker.

```bash
cd agentic-multimodal-app
pip install pydantic pydantic-settings networkx pytest
python3 -m pytest tests/ -q          # expect: 9 passed
```

You can also inspect the committed cases in `data/sample_case/` and `data/demos/`.

---

## Path B — full stack on a GPU box

This is the actual demo: text + VLM vLLM servers, the MERaLiON-3 shim, Milvus +
FalkorDB, the agent, and the UI.

### 1. Configure

```bash
cp .env.example .env
```

Edit `.env`:
- `GPU_PROFILE=rtx6000` (dev) — see Path C for GB10.
- Model tags default to **ready FP8 checkpoints** (`Qwen/Qwen3-14B-FP8`,
  `Qwen/Qwen3-VL-8B-Instruct-FP8`) and `MERaLiON/MERaLiON-3-10B` (bf16 shim).
  Verify the exact revisions on Hugging Face. See [docs/MODELS.md](docs/MODELS.md).
- Add `HF_TOKEN` if any weights are gated.

### 2. Bring up the stack

```bash
docker compose up --build
```

First run downloads weights — give it time. Watch each server report ready.

### 3. Verify serving

```bash
curl -s http://localhost:8001/v1/models    # text  (Qwen3-14B-FP8)
curl -s http://localhost:8002/v1/models    # vlm   (Qwen3-VL-8B-FP8)
curl -s http://localhost:8003/v1/models    # audio (MERaLiON-3 shim)
nvidia-smi                                  # expect < 60 GB total
curl -s http://localhost:8000/health        # {"status":"ok",...}
```

### 4. Walk a case in the UI

Open **http://localhost:5173** and:
1. Keep the defaults (case `sample-case`, load dir `data/sample_case`) → **1 · Plan**.
2. Review the Planner's plan, untick any asset you don't want → **2 · Approve & Investigate**.
3. Inspect the relationship graph (key players are the larger nodes) → **3 · Synthesize report**.
4. Read the cited report; ask follow-ups in **Ask Socrates**.

To run a demo case instead, set the **Load dir** to one of the `data/demos/*`
paths below.

### 5. Or run headless (CLI)

```bash
docker compose run --rm app ama run --case data/sample_case --yes
# or any demo: ... --case data/demos/03_hidden_kingpin
```

---

## Path C — deploy to GB10

```bash
# in .env
GPU_PROFILE=gb10
TEXT_QUANT=fp8     # keep FP8 — GB10 bandwidth makes bf16 decode slow
```

Build multi-arch images and deploy. Full notes (sbsa base images, unified-memory
tuning, cuGraph arm64 caveat) in [docs/DEPLOY_GB10.md](docs/DEPLOY_GB10.md).

```bash
make build-multiarch REGISTRY=<your-registry>
docker compose up -d
```

---

## Demo cases — the agentic showcase

Five committed cases (`data/demos/`) each highlight something the **old linear
flow could not do**. They're synthetic and text-centric so they run out of the
box; cases 1 and 4 note where image/audio would be used in production. Run a case
by pointing the UI **Load dir** (or `ama run --case`) at its folder.

| # | Folder | What to try | Old linear flow | New agentic way |
|---|---|---|---|---|
| 1 | `data/demos/01_multimodal_correlation` | "Trace the 25k." | One analyzer per asset; the human stitches chat + statement + photo together by hand. | Planner fans out across all modalities; the graph **fuses** one money trail and the report cites every source. |
| 2 | `data/demos/02_contradiction` | "Does his statement hold up?" | Statement analyzer summarizes; nobody auto-checks it against the chat. | The **Critic** cross-checks the statement vs the chat and flags the contradiction ("claims never met Rajesh — chat shows pickup"). |
| 3 | `data/demos/03_hidden_kingpin` | "Who's really in charge?" | Reader skims the busiest chatter (Wei Jie) and guesses. | **cuGraph centrality** surfaces "Uncle" — the quiet broker everyone routes through — as the key player. |
| 4 | `data/demos/04_duress_sentiment` | "Was the witness under duress?" | Plain transcript; tone is lost. | **MERaLiON-3 paralinguistics** (annotated here) drives a sentiment/duress flag the agent raises for human review. |
| 5 | `data/demos/05_network_communities` | "One org or separate cells?" | Two chats analyzed separately; the link is missed. | **cuGraph community detection** finds two cells **bridged by Rajesh**, the single broker connecting supply and distribution. |

Across all five, the human-in-the-loop gates each phase and every claim is cited —
the accountability "middle ground" investigators require.

---

## Observability (P1)

```bash
docker compose -f docker-compose.yml -f observability/compose.phoenix.yml up -d
echo "ENABLE_TRACING=true" >> .env && docker compose restart app
open http://localhost:6006        # traces, token in/out, TTFT
```

Benchmark TTFT / tok-s and score accuracy:

```bash
pip install aiperf
./benchmark/run_aiperf.sh text 8001
python eval/score.py --run data/sample_case
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| A server OOMs at startup | Confirm the `*_QUANT` are `fp8`; lower `--gpu-memory-utilization` in `serving/entrypoint.sh`; or reduce `MAX_MODEL_LEN`. |
| `model not found` / 404 from a server | The HF tag in `.env` is wrong or gated — verify on Hugging Face, set `HF_TOKEN`. |
| MERaLiON audio server slow/uses memory | It runs via Transformers (bf16, no vLLM yet) — expected. See `serving/README.md` + `docs/MODELS.md`. |
| VLM server won't start | Qwen3-VL-FP8 needs vLLM ≥ 0.11.1; rebuild `serving/` with a newer `BASE`. |
| UI can't reach the API | The browser hits `PUBLIC_API_URL` (default `http://localhost:8000`); set it in `ui/.env` if the app runs elsewhere. |
| Milvus slow to start | It depends on etcd + minio; wait for all three healthy, or set `VECTOR_BACKEND=chroma` for a no-GPU dev fallback. |
| cuGraph import fails (esp. arm64) | Analytics auto-falls back to NetworkX on CPU — non-fatal. |
