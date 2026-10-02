# Historical implementation archive

These records preserve the original phase plans, experiments, corrections and
machine-specific verification. They were moved here during the 2026-10-02 documentation
consolidation. **Use [DESIGN.md](../../DESIGN.md) for the reviewed architecture and
[QUICKSTART_DEVELOPER.md](../../QUICKSTART_DEVELOPER.md) for setup.**

The historical body of each record is retained, including dated status, commands,
model names and measurements. A historical banner was added; the benchmark record's
relative quickstart hyperlink was rebased after the move. The historical roadmap's
old framework link points to its reviewed commit. Inline paths describe the
original repository layout. They are evidence of earlier work, not fresh instructions
or proof that the current branch/host behaves the same way.

## Phase records

| Record | Historical subject |
|---|---|
| [Phase 1 — AI-Q](phases/PHASE1_AIQ.md) | Initial agent deployment / configuration |
| [Phase 2 — RAG](phases/PHASE2_RAG.md) | Ingestion/retrieval and store deployment |
| [Phase 3 — Data simulation](phases/PHASE3_DATA_SIM.md) | Synthetic case generation and text ingestion |
| [Phase 4 — Audio](phases/PHASE4_AUDIO.md) | Speech recognition and local paralinguistics work |
| [Phase 5 — VSS](phases/PHASE5_VSS.md) | Video profile, serving and shared-store integration |
| [Phase 6 — Graph](phases/PHASE6_GRAPH.md) | Neo4j and entity extraction |
| [Phase 7 — Extensions](phases/PHASE7_EXTENSIONS.md) | MCP tools and forensic prompts |
| [Phase 8 — Workbench](phases/PHASE8_WORKBENCH.md) | Custom UI/API and early upload/approval behavior |
| [Phase 9 — Original plan](phases/PHASE9_PLAN.md) | Proposed observability/evaluation/profiling/guardrails; contains options and API assumptions later corrected |
| [Phase 9a — Observability](phases/PHASE9A_OBSERVABILITY.md) | Phoenix implementation and corrections to the plan |
| [Phase 9b — Evaluation](phases/PHASE9B_EVAL.md) | NAT evaluation/profiling implementation and corrections to the plan |
| [Phase 9e — Inference benchmark](phases/PHASE9E_INFERENCE_BENCHMARK.md) | Benchmark plan, gates and RTX run record |
| [Machine status — 2026-08-29](phase-status-2026-08-29.md) | The former phase-status snapshot; subsequent records can be newer |
| [Roadmap before consolidation](roadmap-before-2026-10-02.md) | Original completed checklists, benchmark claims and unverified migration proposals; TODO.md retains the original completed history and backlog |

## Reading historical claims

Some records describe intentions as completed architecture: enforced approval,
all-local/offline serving, image captioning, video indexing into RAG/Neo4j, or graph
GPU acceleration. The [current capability summary](../../DESIGN.md#7-deployment-shapes)
distinguishes those claims from implemented paths. Later corrections in a record
matter more than an earlier plan; actual source and deployed configuration still
need verification.

Benchmarks and latency/memory figures apply to the recorded hardware, workload and
model configuration. Retain them as examples; validate the workload and reporting
before drawing new comparisons. [Committed benchmark examples](../../benchmark/examples/rtx_pro6000-2026-08-31/README.md)
remain with their machine-readable artifacts so the evidence stays together.

[Implementation learnings](../../.claude/context/implementation-learnings.md) and the
[VSS skills catalog](../../.claude/context/vss-skills-catalog.md) remain in their existing
locations as dated troubleshooting/reference material. The active phase-status file retains its original dated records with a review note;
it should not be interpreted as a universal live machine state.
