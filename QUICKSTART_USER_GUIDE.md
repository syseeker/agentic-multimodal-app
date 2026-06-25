# User Guide — working a case with the agent

For the **user persona** (e.g. an investigator). This describes how a user interacts
with the finished app via the case-workbench UI. The example agent is **Sherlock**
(forensic co-worker); the same flow applies to any domain the app is retargeted to.

> Status: the UI is built in **Phase 8** (see [QUICKSTART_DEVELOPER.md](QUICKSTART_DEVELOPER.md)).
> Until then this is the intended user experience; a developer can drive the agent
> headless in earlier phases.

## The workflow

1. **Create a case** — name it, state an objective ("Map the parties and the money
   flow"), and upload the evidence: **photos**, **audio statements**, **chat
   exports**.
2. **Review the plan (approve)** — the agent proposes which assets to process and
   which capabilities to run. **You approve or reject** before anything runs — the
   human-in-the-loop gate. The agent advises; you decide.
3. **Investigate** — on approval, the agent extracts entities, builds the
   **relationship graph**, transcribes audio, and runs **sentiment/paralinguistic**
   analysis across the approved evidence.
4. **Read the cited findings** — a summary where **every claim links to the source
   asset** (court-defensible). Explore the **relationship graph** (entities, edges,
   key players) and the **sentiment panel** per statement.
5. **Ask follow-ups** — chat with the agent ("Who transferred money to whom?").
   Answers stay grounded in the case evidence, with citations, and never reach the
   internet (the system is air-gapped).

## What you can rely on
- **Nothing consequential runs without your approval.**
- **Every finding is cited** to a specific asset you can open and verify.
- **Air-gapped** — evidence never leaves the system; deep research is over your case
  files only.

## What the UI gives you (per [DESIGN.md](DESIGN.md) §4)
Multimodal intake · chat · plan + approve/reject gates · relationship-graph view ·
cited findings/report with click-through · sentiment/paralinguistic panel · evidence
viewer (image / audio / transcript).
