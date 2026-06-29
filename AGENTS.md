# Sherlock — Agentic Framework Deep-Dive

This document answers three questions the main DESIGN.md and DESIGN-EXT.md do not:

1. **Where exactly** are the Plan → Act → Observe → Refine elements in this codebase?
2. **Which agent framework** is in use, and who is the orchestrator?
3. **How does this compare** to the NemoClaw / OpenShift + Hermes pattern, and what would a migration look like?

---

## 1. The Agentic Loop: Where Is It?

The canonical agentic loop — **Plan, Act, Observe, Refine** — exists in AI-Q (AgentIQ). It is NOT scattered across scripts. Every loop iteration lives inside the AI-Q container (`amms-aiq-agent`). Here is exactly where each step maps:

### Plan
**Who does it:** `intent_classifier` + (optionally) `clarifier_agent` + the planner inside `deep_research_agent`.

**What it does:**

| Component | Where in code | What it plans |
|-----------|--------------|---------------|
| `intent_classifier` | `functions.intent_classifier._type: intent_classifier` in `config_sherlock_frag.yml` | Decides: shallow research, deep research, or clarification needed |
| `clarifier_agent` | `functions.clarifier_agent._type: clarifier_agent` | Generates a structured investigation plan (title + sections JSON) via `plan_generation.j2` prompt |
| `deep_research_agent.planner_llm` | `deep_research_agent` config, `planner_llm: gpt_oss_llm` | Plans which sub-questions to research and in what order (multi-step decomposition) |

**Where the plan lives at runtime:**  
In the LangGraph state dict passed between workflow nodes. It is NOT stored in a database between requests (stateless per stream, except for the checkpoint DB).

**The planning prompt:**
`deploy/aiq-prompts/clarifier/plan_generation.j2` — injected via volume mount into the AI-Q container. Instructs the LLM to output `{"title": "...", "sections": [...]}` JSON.

---

### Act
**Who does it:** `shallow_research_agent` and `deep_research_agent` — they execute tool calls.

**What it does:** Issues calls to registered tools (MCP or built-in) based on the plan.

| Tool called | Registered as | What action it performs |
|------------|--------------|------------------------|
| `knowledge_search` | `functions.knowledge_search._type: knowledge_retrieval` | HTTP POST to RAG Blueprint → semantic search over Elasticsearch |
| `graph_query_tool` | `function_groups.mcp_sherlock_tools` → MCP → `mcp/sherlock_mcp.py` | Cypher query to Neo4j → entity list |
| `graph_analyze_tool` | same MCP server | NetworkX algorithm on entity graph |
| `extract_entities_tool` | same MCP server | LLM NER → MERGE into Neo4j |

**Where the act loop lives:**
```
shallow_research_agent: max_tool_iterations: 8   # max acts per shallow pass
deep_research_agent:    max_loops: 2             # outer acts (each may spawn researchers)
```
The act loop is inside AI-Q's `shallow_research_agent` and `deep_research_agent` implementations — not in any code in this repo.

---

### Observe
**Who does it:** AI-Q's internal message passing. Each tool call result is returned as a `ToolMessage` in the LangGraph state.

**What it does:** The tool result (JSON from Neo4j / text from RAG / etc.) is appended to the message list and fed back to the LLM as the observation.

**Where you can SEE observations:**
Every `intermediate_data:` SSE event with `name: "Function Complete: <tool_name>"` or `name: "Tool: <tool_name>"` carries the raw observation payload. Example from a live stream:

```
intermediate_data: {
  "name": "Function Complete: mcp_sherlock_tools__graph_query_tool",
  "payload": "**Function Output:**\n{\"entities\": [{\"type\": \"Person\", \"name\": \"Tan Wei Jie\", ...}]}"
}
```

The `ChatPanel.svelte` parser reads these events and maps them to human-readable step labels (e.g. "Searching knowledge base…"). The raw observation text is intentionally NOT shown to the investigator — only the final synthesized answer is.

---

### Refine
**Who does it:** Multiple layers:

| Layer | Mechanism | Where configured |
|-------|-----------|-----------------|
| **Within a request** | Deep researcher loops (`max_loops: 2`) — if first pass unsatisfactory, re-queries with refined search terms | `deep_research_agent.max_loops` in config |
| **Clarifier turns** | Up to 3 clarification rounds before committing to a plan | `clarifier_agent.max_turns: 3` |
| **Human-in-the-loop (HITL)** | Investigator approves/rejects investigation plans via the workbench banner | `ChatPanel.svelte` `detectPlan()` + approve/reject buttons |
| **Across sessions** | **Not implemented** — AI-Q does not learn from past sessions. Each request starts fresh. Long-term memory would require adding an episodic memory tool (e.g. write to a `memory` Neo4j node). |

**The HITL refine loop in Sherlock (current implementation):**
```
Investigator sends message
  → AI-Q deep researcher executes
  → Response contains numbered plan (detectPlan() matches)
  → Workbench shows Approve / Reject banner
  → Investigator clicks Reject → sends "Rejected. Please revise: <reason>"
  → AI-Q reruns with the feedback
```
This is our workbench-level refine loop, independent of AI-Q's internal clarifier.

---

## 2. The Framework: AI-Q (AgentIQ)

### What AI-Q Is

**AI-Q (AgentIQ)** is NVIDIA's agent orchestration framework. It is:
- **Config-driven**: agents, LLMs, tools, and workflow topology are declared in YAML (`config_sherlock_frag.yml`). No orchestration code written by us.
- **LangGraph-backed**: AI-Q's internal workflow engine uses LangGraph (a directed graph of agent nodes with state). Nodes pass a shared state dict; edges are conditional (intent_classifier output routes to different next nodes).
- **OpenAI-API-compatible**: exposes `/v1/chat/stream` (SSE) so any client that can speak OpenAI streaming can talk to it.
- **Job-store-aware**: for async deep research, jobs are persisted in Postgres/SQLite (`aiq_api` front-end + `AIQAPIWorker`). The workbench uses sync streaming (`/v1/chat/stream`), not the async job API.

### The Orchestrator

The orchestrator is AI-Q's **`shallow_research_workflow`**, declared as:

```yaml
workflow:
  _type: shallow_research_workflow
```

This is a pre-built AI-Q workflow type. It routes every query directly to the `shallow_research_agent` — no intent classifier, no deep research, no async job submission. The flow is:

```
User message
  │
  ▼
shallow_research_agent    ← Nemotron-3-nano-30b-a3b, thinking enabled
  │  tool loop (max_tool_iterations: 8)
  ├──▶ graph_query_tool      (Neo4j entity lookup)
  ├──▶ graph_analyze_tool    (centrality / community detection)
  └──▶ knowledge_search      (RAG Blueprint semantic search)
  │
  ▼
synthesis → cited answer (25–60s total)
```

**Why not `chat_deepresearcher_agent`?** The deep researcher routes complex queries (e.g. "build an investigation plan") to a `deep_research_agent` that uses a 120B model and runs autonomous file I/O loops (write_todos, task, glob, ls, grep) — taking 3+ minutes. For a forensic investigator who needs answers in seconds, `shallow_research_workflow` with tool calling is faster, more predictable, and produces equally good cited answers.

**No custom orchestration code in this repo.** The routing logic above is inside AI-Q's `shallow_research_workflow` implementation. We only configure it.

### The LLMs

Three LLM roles, each tuned differently:

| Role | Model | Temp | Used by |
|------|-------|------|---------|
| `nemotron_llm_intent` | nemotron-3-nano-30b-a3b | 0.5 | intent_classifier (fast, decisive) |
| `nemotron_nano_llm` | nemotron-3-nano-30b-a3b | 0.1 | shallow_researcher, clarifier (precise, low-hallucination) |
| `gpt_oss_llm` | openai/gpt-oss-120b | 1.0 | deep_research_agent orchestrator + planner (creative, broad reasoning) |

### The Persona

AI-Q's "who am I" is in the Jinja2 system prompt:
`deploy/aiq-prompts/shallow_researcher/researcher.j2`

This is the **Sherlock persona** — injected at request time. It defines:
- Role: "forensic investigation co-worker for Singapore Police Force"
- Conduct rules (cite everything, flag inferences, cross-reference)
- Source hierarchy (graph first for suspect questions, docs for reports)
- Citation format

The prompt is volume-mounted into `amms-aiq-agent`, overriding the default NVIDIA research prompt without modifying the AI-Q image.

### What AI-Q Does NOT Do

- **No persistent learning** across sessions (Postgres stores jobs/checkpoints, not learned knowledge)
- **No episodic memory** (each request is independent unless you pass prior chat history)
- **No agent-to-agent messaging** (tools call services, but agents don't send structured messages to each other — only the VSS sub-agent via MCP is an exception)
- **No per-agent identity files** (persona is in one J2 file, not per-agent PERSONA.md)

---

## 3. Comparing to NemoClaw / OpenShift + Hermes

NVIDIA's NemoClaw is a different agent deployment pattern, primarily for **production multi-agent systems on Kubernetes/OpenShift**. It uses Hermes as the inter-agent messaging protocol.

### Identity Model Comparison

| Concept | Current (AI-Q) | NemoClaw + Hermes |
|---------|---------------|------------------|
| **Agent persona** | Single `researcher.j2` Jinja2 prompt file, injected into one container | `PERSONA.md` per agent (structured identity doc) |
| **Tools declaration** | `function_groups:` section in YAML config | `TOOLS.md` per agent (describes each tool, its contract, when to use it) |
| **Skills declaration** | `functions:` section in YAML config | `SKILLS.md` per agent (lists capabilities and domain knowledge) |
| **Orchestration** | AI-Q workflow type (`chat_deepresearcher_agent`) — single container routes internally | Hermes message bus — agents are separate services, communicate via typed messages |
| **Deployment** | Docker Compose, single `amms-aiq-agent` container | OpenShift (Kubernetes), one pod per agent |
| **State passing** | LangGraph state dict (in-memory, same process) | Hermes message payloads (network messages, serialized) |

### What Stays the Same

If Sherlock were migrated to NemoClaw:
- **Storage** (Elasticsearch, Neo4j, Postgres) — unchanged, same services
- **Tool implementations** (Sherlock MCP server, RAG Blueprint, Parakeet ASR) — unchanged
- **Prompts content** — the same forensic persona text, just restructured into PERSONA.md files
- **HITL logic** — would move from workbench UI into a Hermes approval message handler

### The Mapping: Current → NemoClaw Equivalent

| Current component | NemoClaw equivalent |
|------------------|---------------------|
| `deploy/aiq-prompts/shallow_researcher/researcher.j2` | `sherlock-lead/PERSONA.md` |
| `function_groups.mcp_sherlock_tools` in YAML | `sherlock-lead/TOOLS.md` (graph_query, graph_analyze, etc.) |
| `functions.knowledge_search` in YAML | `sherlock-lead/TOOLS.md` (knowledge_search) |
| `functions.shallow_research_agent` + `deep_research_agent` | `sherlock-lead/SKILLS.md` (research capability) |
| `vss-agent` via MCP | `vss-agent/PERSONA.md` + `vss-agent/TOOLS.md` (separate pod) |
| AI-Q `chat_deepresearcher_agent` workflow | Hermes orchestrator service (routes messages between agents) |
| `clarifier_agent.enable_plan_approval` | Hermes `HumanApprovalMessage` type |
| `intermediate_data:` SSE events | Hermes event stream (same concept, different protocol) |

### What Would Change

```
Current (AI-Q, monolithic):
  amms-aiq-agent (one container)
    └── intent_classifier
    └── clarifier_agent
    └── shallow_research_agent
    └── deep_research_agent
    
NemoClaw (distributed):
  sherlock-lead-pod
    └── PERSONA.md: "You are Sherlock, forensic co-worker..."
    └── TOOLS.md:   graph_query, knowledge_search, ...
    └── SKILLS.md:  forensic investigation, citation rules, ...
  
  vss-agent-pod
    └── PERSONA.md: "You are the video analysis specialist..."
    └── TOOLS.md:   summarize_video, search_video, describe_frame
    └── SKILLS.md:  video temporal reasoning, frame analysis, ...
  
  hermes-orchestrator
    └── routes HumanMessage → sherlock-lead
    └── routes VideoQuery → vss-agent
    └── handles HumanApprovalMessage (HITL)
```

### Why Not Migrate Now

AI-Q already provides:
- The same Plan/Act/Observe/Refine loop
- The same tool-calling capability
- HITL (just disabled AI-Q's built-in; using workbench UI instead)
- Streaming output

NemoClaw/Hermes adds value for:
- **True multi-agent parallelism** (agents running simultaneously on different pods)
- **Agent versioning** (deploy a new `vss-agent` v2 without touching sherlock-lead)
- **Production Kubernetes** (health checks, auto-scaling, rolling updates per agent)
- **Auditability** (every Hermes message is a typed, logged event — better than SSE `intermediate_data:`)

**Recommendation for when to migrate:** When deploying to production on OpenShift, or when the number of specialist agents exceeds 3 (video, audio, graph become independent pods). Not worth the complexity for the current dev/demo phase.

---

## 4. Known Gaps vs. True Agentic Systems

| Capability | Sherlock now | What a fuller system would add |
|-----------|-------------|-------------------------------|
| **Learning across sessions** | ❌ None | Add a `memory` tool: write key findings to Neo4j `Memory` nodes; read them at session start |
| **Proactive alerting** | ❌ None | Cron job queries AI-Q with new evidence → pushes alerts to investigator |
| **Agent self-correction** | Partial (deep_research_agent loops) | Add a verifier agent that critiques each finding before output |
| **Cross-case reasoning** | ❌ Per-case only | Query Neo4j across case_id boundaries (disabled for privacy; re-enable per investigation scope) |
| **Episodic memory** | ❌ None | Store approved plans + outcomes in Postgres; retrieve as few-shot examples next session |
| **Explicit Refine signal** | Partial (HITL) | Structured feedback form on rejection: "too vague / wrong suspect / missing evidence" |

---

## 5. Debugging the Agentic Loop

When a response is empty or wrong, trace the loop through these signals:

| Signal | Where to look | What it tells you |
|--------|--------------|------------------|
| `intermediate_data: Function Start: intent_classifier` | SSE stream | Loop started |
| `intermediate_data: Function Complete: intent_classifier` | SSE stream | Routing decided (check payload for decision) |
| `intermediate_data: Function Start: shallow/deep_research_agent` | SSE stream | Act phase started |
| `intermediate_data: Tool: mcp_sherlock_tools__graph_query_tool` | SSE stream | Observation requested |
| `intermediate_data: Function Complete: mcp_sherlock_tools__graph_query_tool` | SSE stream | Observation received (payload has raw result) |
| `data: {"choices":[{"delta":{"content":"..."}}]}` | SSE stream | Synthesis complete — user-visible output |
| `data: {"choices":[{"delta":{"content":""}}]}` | SSE stream | Empty response (clarifier HITL pause, or LLM returned nothing) |
| AI-Q container logs | `docker logs amms-aiq-agent` | Exceptions, tool errors, timeouts |
| Workbench logs | `/tmp/sherlock.log` | Proxy errors (timeout, connection refused) |

**Current known issue (fixed):** `clarifier_agent.enable_plan_approval: true` caused the stream to close after generating a plan JSON with an empty `data:` content event. Fixed by setting `enable_plan_approval: false` — plan requests now route to the deep researcher, which returns cited content via normal `data:` events.
