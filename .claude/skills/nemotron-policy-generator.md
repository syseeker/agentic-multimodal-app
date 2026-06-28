# SME Summary: nemotron-policy-generator skill

Source: `~/skills/skills/nemotron-policy-generator/`
Skill version: 0.1.0
Always re-read the full skill files before implementing; this summary is a quick reference.

---

## What This Skill Does

Generates custom safety policies for NVIDIA Nemotron content-safety guardrails.
For this project (Phase 7): Define a forensic investigation safety policy that allows
legitimate investigative content while blocking harmful outputs.

---

## When to Use (Phase 7)

- Configuring NeMo Guardrails for Sherlock
- Defining what Sherlock should/should not output in a forensic investigation context
- Setting up HITL policy rules (what requires human approval vs auto-approve)

---

## Target Models for This Project

| Model | Use case |
|---|---|
| `nvidia/Nemotron-Content-Safety-Reasoning-4B` | Text safety (AI-Q outputs) |
| `nvidia/Nemotron-3-Content-Safety` | Multimodal (image analysis outputs) |

Both may be needed given Sherlock handles text + images.

---

## Six-Step Policy Generation Workflow

Read `references/` files in the skill before each step:

1. **Classify input** — deployment context, use cases, target models, inference mode
2. **Map to V2 taxonomy** — read `references/content_safety_taxonomy.md`
3. **Expand each category** — name, definition, in_scope, out_of_scope, severity, examples
4. **Add cross-cutting sections** — allow-list, jurisdiction, refusal guidance
5. **Generate outputs** — Markdown policy + JSON schema + system prompt
6. **Save outputs** — use naming: `sherlock_forensic_v1.0.0.{md,json,_system_prompt.txt}`

---

## Forensic Context for Sherlock Policy

Key considerations for a forensic investigation guardrail policy:

**Must ALLOW (in-scope for investigations):**
- Discussion of criminal activity as evidence (not instruction)
- Explicit descriptions of crimes when citing evidence
- Violent/disturbing content when analyzing crime scene evidence
- Drug-related content when analyzing seized communications
- Financial crime discussion
- Gang/organized crime entity analysis

**Must BLOCK (out-of-scope):**
- Generating new instructions for illegal activities
- Content that could harm investigation subjects' rights (protect PII beyond case facts)
- Speculation beyond evidence (hallucinated "facts")
- Web-sourced information (air-gapped: only internal evidence)

**Special considerations:**
- Singapore jurisdiction (Singlish, SEA context, Singaporean law references)
- Court-defensible outputs: Sherlock must cite its sources, never speculate
- HITL override: any action flagged by guardrails should go to human approval, not auto-block

---

## Severity Model for Sherlock

Use **graded severity** (S0–S4):
- S0: Safe — normal investigative output, auto-proceed
- S1: Minor — borderline, add citation requirement
- S2: Violation — flag for human review (HITL gate)
- S3: Severe — block output, log for audit
- S4: Catastrophic — hard block (e.g., CSAE content — never allow)

---

## CRITICAL: Non-Negotiable Floor

**NEVER allow S7 (Sexual content involving minors / CSAE)** regardless of forensic context.
Even if evidence contains such material, Sherlock must:
- Flag the existence of such material (for investigators to handle via proper legal channels)
- Never reproduce, describe, or analyze such content in its outputs

---

## Output Files Location

Save generated policy files to `deploy/policy/`:
```
deploy/policy/sherlock_forensic_v1.0.0.md
deploy/policy/sherlock_forensic_v1.0.0.json
deploy/policy/sherlock_forensic_v1.0.0_system_prompt.txt
```

---

## Integration with AI-Q (Phase 7)

1. Generate the policy using this skill
2. The system prompt goes into AI-Q's guardrails config
3. NeMo Guardrails reads the policy at runtime
4. HITL gates: policy S2+ triggers AI-Q's built-in plan-approval (human must approve)

Read `~/skills/skills/rag-blueprint/references/configure/guardrails.md` for how NeMo
Guardrails integrates with the RAG Blueprint (same pattern applies to AI-Q).
