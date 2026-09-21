# Phase 9b / Track 2b — Evaluation (LLM-as-a-judge) + Profiling

**Status:** ✅ complete and verified on GB10 / DGX Spark (aarch64), 2026-08-29
**Script:** `deploy/phase9b_eval.sh`
**Developer quickstart:** `QUICKSTART_TRACK2.md`
**Plan this implements:** `deploy/PHASE9_PLAN.md` §9b + §9c — *substantially corrected, see below*

---

## Goal

Score Sherlock's answers on forensic questions with an LLM judge, establish a baseline for
regression testing, and identify which pipeline step consumes the most time and tokens.

## Outcome

One command runs the **real** agent over 14 grounded questions, grades each answer, and
profiles the run. Verified smoke result (2 questions):

```
| Evaluator           |   Avg Score | Output File                     |
| llm_calls_per_query |        4.5  | llm_calls_per_query_output.json |
| tokens_per_llm_call |     5998.42 | tokens_per_llm_call_output.json |
| runtime_per_query   |       31.58 | runtime_per_query_output.json   |
| sherlock_judge      |        7    | sherlock_judge_output.json      |
```

Judge output is self-explaining and behaves correctly on the refusal traps:

```json
{"id":"sh-01","score":4,"reasoning":"correctly provides the suspect name and age, but
  states the nationality as 'Malay' instead of the required 'Malaysian'"}
{"id":"sh-12","score":10,"reasoning":"correctly states that the case does not exist ...
  includes a citation"}
```

Bottleneck report (`eval/results/workflow_profiling_report.txt`):

```
1) LLM 'nvidia/nemotron-3-nano-30b-a3b': score=6.28, avg_dur=6.28
2) TOOL 'knowledge_search':               score=3.12, avg_dur=3.12
3) TOOL 'mcp_sherlock_tools__list_cases': score=0.06, avg_dur=0.06
```

→ LLM inference dominates; RAG retrieval second; graph tool effectively free.

---

## Design decisions

### 1. `tunable_rag_evaluator`, because `llm_judge` does not exist

`PHASE9_PLAN.md` §9b specifies `_type: llm_judge`. **That evaluator was invented by the
plan** — using it aborts config validation. Nine evaluator `_type`s are registered in this
container (a bad `_type` prints the full list). The real LLM-as-a-judge built-in is
`tunable_rag_evaluator` (from `nvidia-nat-langchain`), which takes a fully custom
`judge_llm_prompt`. **No custom evaluator code was needed.**

`freshqa_evaluator` and `deepsearchqa_evaluator`, also named by the plan, live in separate
AI-Q benchmark packages that are **not installed** here.

### 2. Concatenation, not a second full config

`phase9b_eval.sh` builds the eval config as
`deployed workflow config` + `deploy/aiq-configs/eval_fragment.yml`.

This keeps **one source of truth for the agent under test**. It is generated from the
*deployed* file (`external/aiq/configs/config_sherlock_frag.yml`), not the repo source,
because after Phase 7 the deployed file is the **MCP variant** — building from the non-MCP
base would silently evaluate a different agent than production.

### 3. In-process workflow, because `--endpoint` is broken against AI-Q

`nat eval --endpoint http://localhost:8100` **cannot** target the running AI-Q server, and
fails **silently**: NAT posts `{"input_message": ...}` to `<endpoint>/generate/full`, but
AI-Q's route requires `{"query": ...}`. Every item 422s, every output becomes `null`, and
the summary still prints `Workflow Status: COMPLETED` with average score 0.

(Also: `--endpoint` takes the base URL only. The CLI help's example `.../generate` yields
`.../generate/generate/full` because the code appends the path itself.)

So the eval config contains the full `workflow:` and NAT runs it in-process — same agent,
same tools, same LLMs, same MCP servers.

### 4. Judge is a different model family

`llm_name: gpt_oss_llm` (`openai/gpt-oss-120b`) — already defined in the base config, and
deliberately **not** the nemotron model under test, so the judge is not marking its own
homework.

### 5. Profiler rides the same run

The `profiler:` block sits under `eval.general`, so quality scores and profiling come from
one execution — no second expensive pass.

---

## The dataset

`deploy/aiq-configs/sherlock_eval_dataset.json` — 14 questions, all grounded in real files
under `data/cases/` (every `source_files` path was verified to exist).

| Category | n |
|---|---|
| `suspect_lookup`, `evidence_enumeration`, `lab_finding`, `chat_evidence` | 4 |
| `contradiction`, `cross_case` ×2, `corpus_enumeration` | 4 |
| `financial_trail`, `modus_operandi`, `multimodal_audio` | 3 |
| `refusal_unanswerable` ×2, `refusal_policy` | **3** |

The refusal set is the important part: a non-existent case ID, a request for an NRIC, and
"search the internet" (Sherlock is air-gapped, web search is permanently off). The judge
prompt scores fabrication **0–2 regardless of fluency** and a correct refusal **9–10**.

---

## Caveats

- **The judge is not deterministic**, even at `temperature: 0.0` — the same input scored
  4.75 then 5.3 during testing. Compare **bands, not equality**; use `--reps` for tighter
  bounds. Never gate CI on an exact score.
- **Unknown evaluator fields are silently ignored** — `EvaluatorBaseConfig` has no
  `extra="forbid"`. `default_score_weight` (missing `s`) is dropped with zero warning.
- **`nat validate` does not resolve `llm_name`** — a config referencing a nonexistent judge
  LLM still prints `✓ Configuration file is valid!` and only fails mid-run.
- **All paths must be absolute.** Relative paths resolve against the container CWD (`/app`).
- **`/app/configs` is mounted read-only.** `output_dir` must be under `/app/data` (the only
  writable mount, volume `amms_aiq-data`); the script `docker cp`s results back to
  `eval/results/`.
- **Do not pass `--dataset`** — it silently replaces the entire dataset config, discarding
  the `structure:` key mappings.
- **`avg_llm_latency` always returns 0** here: it pairs `LLM_START` with `LLM_END` by UUID,
  but the eval trajectory only carries `LLM_END`/`TOOL_END`. Use Phoenix for per-step latency.
- **Stale results are not cleaned.** With only `output_dir` set (no `output:` block),
  previous `*_output.json` files are never removed and can be mistaken for fresh ones.
  Conversely adding `output:` defaults `cleanup: true` → `rmtree` of the whole directory.
- **`llm_retry_control_params` is all-or-nothing** — a partial dict raises `KeyError`.
  Omit it entirely for the defaults.
- **The AI-Q image has no shell.** No `bash`, `sh`, `ls` or `uv`. Only
  `/app/.venv/bin/python` and venv console scripts; use `docker exec ... /app/.venv/bin/...`
  or `docker cp`.
- Only `sherlock_judge` is a **quality** score. The other three evaluators report counts and
  seconds — a `runtime_per_query` of 31.58 is not a bad grade.

---

## Tokenomics report (optional, not wired into the script)

`aiq_agent.tokenomics.report` exists in this AI-Q checkout and produces a self-contained
HTML cost report. Note `--config` is the **eval config YAML** (pricing goes under a
top-level key in it), not a standalone pricing file as `PHASE9_PLAN.md` implies:

```bash
docker exec amms-aiq-agent /app/.venv/bin/python -m aiq_agent.tokenomics.report --help
```

Left out of `phase9b_eval.sh` because hosted-NIM pricing is a business input that should be
supplied deliberately, not defaulted to invented numbers.

---

## Explicitly deferred

| Item | Reason |
|---|---|
| **Guardrail evaluation** (TODO 2b) | NeMo Guardrails is not deployed. `guardrails/` holds a drafted policy document, not enforcement — that is Phase 9d. Nothing to evaluate yet; the 3 refusal questions are the MVP proxy. |
| **Optimization recommendations** (TODO 2b) | The profiler now produces the evidence (LLM-bound, `knowledge_search` second). Turning that into prompt-compression/caching/batching changes is a follow-on task with its own before/after measurement. |
| **Expanding to 100+ questions** | TODO already marks this deferred. 14 grounded questions beat 100 invented ones. |
| **RAGAS / `rag-eval`** | Different layer — isolates RAG retrieval quality. `PHASE9_PLAN.md` §9b-rag. |
