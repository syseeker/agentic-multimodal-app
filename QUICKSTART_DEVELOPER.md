# Developer QUICKSTART — living build playbook

This is the **developer persona's** guide to building (and continuing to build)
Sherlock, phase by phase. It is **living**: every phase is driven by an **NVIDIA
skill**, installed *fresh* so you always get the latest SME guidance — as the skills
improve, re-running a phase picks up the improvements automatically.

Read [DESIGN.md](DESIGN.md) first (architecture + why each component). This file is
*how* to execute it.

## Operating rules (non-negotiable)
1. **Skills are the source of truth.** Deploy/configure NVIDIA components only via
   their skill. Never hand-roll what a blueprint provides.
2. **One phase at a time.** Each phase ends with a **✅ Confirmation checkpoint** —
   run the verify, report results, and get sign-off **before** the next phase.
3. **Custom only where flagged.** Items marked *proposal* have no SME skill; build
   them minimally and call them out for review.

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
refresh skill → invoke skill (it drives deploy/config) → verify → ✅ confirm → next
```
Drive a phase by asking Claude Code, e.g.: *"Use the `aiq-deploy` skill to deploy
the AI-Q backend headless with web search disabled."* The skill carries the exact
commands/images/env — this playbook only states the goal + the checkpoint.

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
- To resume, re-read [DESIGN.md](DESIGN.md), find the last **✅ confirmed** phase,
  refresh that phase's skill, and continue at the next.
- Because skills are re-installed fresh, re-running a phase adopts the latest SME
  fixes (new image tags, config, defaults) without changing this playbook.
- Keep the *proposal* pieces thin and revisit them when a skill later covers them.
