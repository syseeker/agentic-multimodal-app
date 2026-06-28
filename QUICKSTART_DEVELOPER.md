# Developer QUICKSTART — living build playbook

This is the **developer persona's** guide to building (and continuing to build)
Sherlock, phase by phase. It is **living**: every phase is driven by an **NVIDIA
skill**, installed *fresh* so you always get the latest SME guidance — as the skills
improve, re-running a phase picks up the improvements automatically.

Read [DESIGN.md](DESIGN.md) first (architecture + why each component). This file is
*how* to execute it.

## Step 0 — Cold-start on a new instance

```bash
# 1. This repo
git clone https://github.com/syseeker/agentic-multimodal-app ~/agentic-multimodal-app
cd ~/agentic-multimodal-app

# 2. NVIDIA skills repo — SME knowledge, required alongside this repo
git clone https://github.com/NVIDIA/skills ~/skills

# 3. Copy and fill the shared env file (NEVER commit .env)
cp .env.example .env
# Edit .env: fill NVIDIA_API_KEY, NGC_API_KEY, HF_TOKEN
# Ensure these lines are set:
#   COMPOSE_PROJECT_NAME=amms
#   AIQ_PORT=8100

# 4. Install Node.js 20+ (needed to build the Svelte UI)
#    Option A — via system package manager (Ubuntu):
#      curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash -
#      sudo apt-get install -y nodejs
#    Option B — portable (no sudo):
#      curl -fsSL https://nodejs.org/dist/v20.18.1/node-v20.18.1-linux-x64.tar.xz \
#        | tar -xJ -C /tmp/
#      export PATH="/tmp/node-v20.18.1-linux-x64/bin:$PATH"
#      echo 'export PATH="/tmp/node-v20.18.1-linux-x64/bin:$PATH"' >> ~/.bashrc
```

The skills repo (`~/skills`) is the SME source for every NVIDIA component.
**Always read the relevant skill's MD files before implementing each phase.**
Skills are at `~/skills/skills/<skill-name>/`. Summaries are in `.claude/skills/`.

### Already deployed? Just start everything

```bash
bash deploy/start_all.sh
# Opens: http://localhost:8200 (investigator workbench)
```

## Claude Code context — read before prompting

This repo ships a `.claude/` directory that gives any Claude Code instance full
project context automatically:
- `.claude/CLAUDE.md` — entry point: project overview, operating rules, architecture
- `.claude/skills/*.md` — SME knowledge extracted from NVIDIA skills (quick reference)
- `.claude/context/phase-status.md` — current deployment status (update after each phase)
- `.claude/context/implementation-learnings.md` — lessons and gotchas from past attempts

When you open this repo in Claude Code, it reads `.claude/CLAUDE.md` automatically.
You can then prompt it to continue from the last confirmed phase without re-explaining the project.

## Operating rules (non-negotiable)
1. **Read skill files first.** Before implementing or configuring any NVIDIA component,
   read the relevant skill at `~/skills/skills/<skill-name>/`. Claude is NOT an NVIDIA SME.
2. **Skills are the source of truth.** Deploy/configure NVIDIA components only via
   their skill. Never hand-roll what a blueprint provides.
3. **One phase at a time.** Each phase ends with a **✅ Confirmation checkpoint** —
   run the verify, report results, and get sign-off **before** the next phase.
4. **Custom only where flagged.** Items marked *proposal* have no SME skill; build
   them minimally and call them out for review.
5. **Update `.claude/context/`** after each phase — keep `phase-status.md` and
   `implementation-learnings.md` current so the next instance picks up from the right place.

## Install / refresh the skills (do this at the start of every phase)
Skills live in your own Claude Code, not vendored here. Re-add to pull the latest:
```bash
npx skills add nvidia/skills --skill <skill-name> --agent claude-code
# verify signature (optional)
pip install model-signing && model_signing verify certificate <dir> \
  --signature <dir>/skill.oms.sig --certificate_chain nv-agent-root-cert.pem --ignore_unsigned_files
```

## The phase loop (every phase)
```
read skill files → refresh skill → invoke skill (it drives deploy/config) → verify → ✅ confirm → update .claude/context/ → next
```
Drive a phase by prompting Claude Code, e.g.:
> *"Read the `aiq-deploy` skill at `~/skills/skills/aiq-deploy/`, then use it to deploy
> the AI-Q backend headless with web search disabled."*

The skill carries the exact commands/images/env — this playbook only states the goal + checkpoint.
Always reference the skill explicitly so Claude reads it before acting.

---

## Phases

> Air-gapped target ⇒ self-host NIMs in prod (GB10 / RTX PRO 6000, FP8). Dev may
> use hosted NIMs (`build.nvidia.com`). Each phase notes its skill + checkpoint.

### Phase 1 — Deploy AI-Q backend (the agent base)
- **Skill:** `aiq-deploy`. Goal: AI-Q backend running **headless** (no AI-Q UI),
  **web search OFF** (air-gapped).
- **✅ Checkpoint:** `curl -sf http://localhost:8000/health` OK; a chat request
  answers using internal context only (no web tool invoked).

### Phase 2 — Deploy RAG Blueprint, wire as AI-Q FRAG
- **Skill:** `rag-blueprint` (deploy) + `aiq-deploy` → `references/frag.md` (wire).
  Goal: ingest docs/images/text into the shared Elasticsearch; AI-Q retrieves via FRAG.
- **✅ Checkpoint:** ingest a sample doc; AI-Q answers a question citing it.

### Phase 3 — Forensic config + demo cases
- **Skill:** `aiq` configs/customization + `data-designer` (synthetic cases).
  Goal: retarget prompts to forensic investigation; load a demo case; get a cited
  deep-research finding over the case files.
- **✅ Checkpoint:** a demo case produces a cited findings summary, no web access.

### Phase 4 — Audio path
- **Skill:** `nemotron-speech` (Parakeet ASR; Canary optional). **Proposal:**
  self-hosted **MERaLiON-3** for paralinguistics/Singlish-SEA.
- **✅ Checkpoint:** an audio statement → transcript in the corpus; paralinguistic
  cues available for sentiment.

### Phase 5 — Deploy VSS + Neo4j CA-RAG (video ER)
- **Skill:** `vss-deploy-profile` (lvs), `vss-summarize-video` (CA-RAG `graph_db`
  → Neo4j, `LVS_EMB_ENABLE=true`). Goal: video → dense captions → ER in **shared
  Neo4j**.
- **✅ Checkpoint:** a sample video yields entities/relations queryable in Neo4j.

### Phase 6 — Non-video ER into the shared Neo4j *(proposal)*
- **Proposal:** LLM-based entity/relationship extraction for chat/image/audio text,
  written to the **same Neo4j** (matching VSS's schema), namespaced by `case_id`;
  expose graph query + **cuGraph** analytics (centrality/community) as a tool.
- **✅ Checkpoint:** chat+statement entities appear in the same graph as video ER;
  centrality returns a key player.

### Phase 7 — Extend AI-Q (the lead agent) for forensics
- **Source:** `aiq configs`/customization + `nemotron-policy-generator` (guardrails/HITL).
  AI-Q stays the lead agent — extend it via its own points: register the
  **video-specialist `vss-agent` over MCP** (Phase 5), the **Knowledge Layer** (RAG-BP,
  Phase 2), and **tools** for speech/graph/sentiment (Phases 4/6); set forensic prompts;
  rely on AI-Q's **built-in HITL plan-approval** + guardrails. No separate supervisor.
- **✅ Checkpoint:** for a mixed-modality case, AI-Q proposes a plan, the human
  approves, AI-Q delegates video to `vss-agent` and calls the tools, and returns
  **cited** findings + graph + sentiment.

### Phase 8 — Custom case-workbench UI *(proposal)*
- **Proposal:** purpose-built UI per [DESIGN.md](DESIGN.md) §4 (intake, chat,
  approve/reject gates, graph view, cited report with click-through, sentiment,
  evidence viewer). Informed by AI-Q + VSS UIs; neither fits a case workbench.
- **✅ Checkpoint:** an investigator runs a full case end-to-end in the UI.

### Phase 9 — Observability / eval / benchmark
- **Skill/source:** NeMo Agent Toolkit (obs/eval → Phoenix), `aiperf`, Nsight.
- **✅ Checkpoint:** agent + tool spans visible in Phoenix; eval report runs;
  TTFT/throughput benchmarked on the target GPU.

---

## Continuing later / picking up improvements
- To resume, check `.claude/context/phase-status.md` for the last confirmed phase,
  re-read [DESIGN.md](DESIGN.md) for context, read the next phase's skill, and continue.
- Because skills are re-installed fresh, re-running a phase adopts the latest SME
  fixes (new image tags, config, defaults) without changing this playbook.
- Keep the *proposal* pieces thin and revisit them when a skill later covers them.
- **After every phase: update `.claude/context/phase-status.md` and
  `implementation-learnings.md`, then commit.** This is how knowledge survives across
  instances and developers.

## Key files new developers must know

| File | Purpose |
|---|---|
| `deploy/start_all.sh` | Start all services in the right order |
| `deploy/aiq-prompts/` | **Committed** Sherlock prompt templates (Jinja2). Mounted into AI-Q at runtime via `compose.amms.override.yaml`. Do NOT edit `external/aiq/` prompts directly — changes there are gitignored and will be lost. Edit here instead. |
| `deploy/compose.amms.override.yaml` | Docker Compose overlay that wires our config over AI-Q's upstream compose |
| `external/aiq/configs/config_sherlock_frag.yml` | AI-Q Sherlock config (MCP tools + RAG + no web search). **Gitignored** — recreated by Phase 7 deployment. |
| `QUICKSTART_INVESTIGATOR.md` | End-user guide (investigators, not developers) |

### Prompt editing workflow
The Sherlock AI persona lives in two Jinja2 templates. Edit them in the committed location:
```
deploy/aiq-prompts/shallow_researcher/researcher.j2   ← Sherlock research persona
deploy/aiq-prompts/clarifier/plan_generation.j2       ← Investigation plan structure
```
After editing, restart AI-Q to pick up the changes:
```bash
docker compose -p amms -f external/aiq/deploy/compose/docker-compose.yaml \
  -f deploy/compose.amms.override.yaml \
  up -d --no-build aiq-agent
```
