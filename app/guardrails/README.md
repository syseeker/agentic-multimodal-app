# guardrails/ — NeMo Guardrails (P1)

Programmatic enforcement of the accountability rules declared in
`app/config/config_socrates.yml`:

- **Input rails:** keep queries on-task (case material only); block jailbreaks.
- **Dialog rails:** never take consequential action autonomously; route such
  requests to a human-approval gate.
- **Output rails:** reject any answer with an uncited factual claim; redact PII
  not relevant to the objective.

Generated/scaffolded with the `nemotron-policy-generator` skill. Implementation
(Colang `policy.co` + `config.yml`) lands in P1 (PR11); until then the
phase-explicit orchestrator + UI approval gates provide the human-in-the-loop
guarantee.
