# Sherlock — Agentic Forensic Co-Worker (NVIDIA-stack reference)

An agentic co-worker for forensic investigators: ingests seized **photos**, **audio
statements (口供)**, and **chat text**, then plans + performs **entity recognition →
relationship graph → sentiment/paralinguistics**, returning **cited, human-approved**
findings. Built on **NVIDIA blueprints/SDKs** — deployed/configured via the NVIDIA
**skills**, not reimplemented.

> **Build rule:** never hand-roll what an NVIDIA blueprint provides. The agent is
> AI-Q's deepagents agent **borrowed + extended** for forensics (its native tools
> kept, web search off, forensic tools added). Capabilities come from RAG Blueprint,
> VSS, and NIMs. Custom code only where no skill is the SME (flagged as *proposal*).

## Start here
- **[DESIGN.md](DESIGN.md)** — architecture: problem statement, layers, block
  diagram, component decisions, storage, phased plan.
- **[QUICKSTART.md](QUICKSTART.md)** — the **living** developer playbook: build it
  phase by phase, each driven by an NVIDIA skill, each with a confirmation gate.

## Status
Design signed off; implementation is phased with a **confirmation checkpoint** at the
end of every phase (see QUICKSTART). Nothing is deployed until Phase 1 is approved.
