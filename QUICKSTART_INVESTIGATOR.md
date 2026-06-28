# Investigator QUICKSTART — Sherlock Case Workbench

This guide is for **investigators (users)** — not developers. If you are setting up
Sherlock for the first time on a new machine, see [QUICKSTART_DEVELOPER.md](QUICKSTART_DEVELOPER.md)
and ask your system administrator to complete the deployment before following this guide.

---

## What Sherlock does

Sherlock is a forensic investigation co-worker. Given a case folder (evidence files,
WhatsApp chat logs, lab reports, witness statements, audio transcripts), it:

- Answers questions about suspects, evidence, and relationships — with **cited sources**
- Builds entity relationship graphs (who knows whom, who was where)
- Proposes investigation plans — and waits for **your approval** before proceeding
- Cross-references documents and graph data to surface discrepancies

Sherlock does **not** speculate beyond the evidence. Every factual claim cites its source.

---

## Step 1 — Open the workbench

Your system administrator will give you the address. Default:

```
http://<host-ip>:8200
```

If running locally: **http://localhost:8200**

The workbench should show the Sherlock interface with a case list on the left.

If the page does not load, contact your system administrator — services may need to be started with `bash deploy/start_all.sh`.

---

## Step 2 — Select a case

The left panel lists all available cases. You can filter by:
- Case type (homicide, fraud, robbery…)
- District
- Case ID

Click a case to open it. The header bar will show the case ID, type, and status.

---

## Step 3 — Chat with Sherlock

The **Chat** tab opens automatically. Type your question in the input box and press **Enter**.

**Example questions to start with:**
- `Who are the suspects in this case?`
- `Summarize the key evidence.`
- `What is the relationship between [name] and [name]?`
- `Build an investigation plan for this case.`

Sherlock streams its response in real time and cites every claim to a source file or graph query.

### Reading citations

Sherlock formats citations inline: `[1]`, `[2]`, etc. At the end of each response you will find a **References** section listing the source files.

---

## Step 4 — Approving an investigation plan (HITL)

When you ask Sherlock to `build an investigation plan`, it proposes a structured plan and **pauses for your approval** before proceeding.

A green banner appears at the top of the chat:

> **Sherlock has proposed an investigation plan** — review and approve before proceeding.

Review the numbered steps in the response. Then:

| Action | What happens |
|---|---|
| **Approve & Proceed** | Sherlock executes the plan, querying evidence at each step |
| **Reject & Revise** | You are prompted to give a reason; Sherlock revises and re-presents |

This approval gate is mandatory — Sherlock will not proceed without your explicit go-ahead.

---

## Step 5 — Entity relationship graph

Click the **Entity Graph** tab to see all entities extracted from the case files:

- **Blue nodes** — Persons (suspects, witnesses, victims)
- **Amber nodes** — Organizations
- **Green nodes** — Locations
- **Red nodes** — Evidence items

Click any node to see its properties (role, nationality, age, evidence type, etc.).

Use the **Fit** button to reset the view, or **Re-layout** to re-run the force-directed layout.

---

## Step 6 — Evidence viewer

Click the **Evidence** tab to browse the raw case files:

- `case_report.txt` — case summary and incident details
- `witness_statement.txt` — witness accounts
- `lab_report.txt` — forensic lab findings
- `whatsapp_chat.txt` — extracted chat logs
- `audio_analysis.txt` — transcript + paralinguistic analysis of audio statements
- `metadata.json` — case registration metadata

Click any file to view its full text content.

---

## Step 7 — Paralinguistics panel

Click the **Paralinguistics** tab to view audio statement analysis.

When audio files have been processed through the speech pipeline (Parakeet ASR + MERaLiON), this panel shows:
- Transcript of the statement
- Paralinguistic signals: stress level, speech pace, tone, confidence indicators

If no audio has been processed for this case, the panel shows guidance on how to trigger processing.

---

## Workflow summary

```
Select case → Chat: ask questions → Review cited answers
    → Ask for investigation plan → HITL: Approve or Reject
    → Review entity graph → Browse evidence files
    → Check paralinguistics for audio statements
```

---

## What Sherlock has access to

| Data source | What it contains |
|---|---|
| Case Documents | All text files ingested for this case (RAG search) |
| Case Graph | Entity/relationship data extracted from case files (Neo4j) |

Both sources are filtered to your selected case — Sherlock cannot access data from other cases unless you explicitly switch cases.

---

## Important limitations (know before you rely on findings)

- **Sherlock is not infallible.** It can miss context or misinterpret ambiguous evidence. Always verify cited claims against the source files.
- **Audio analysis is a stub** until the GPU audio pipeline is connected (MERaLiON requires GPU).
- **Video evidence** requires the GPU instance (VSS) to be running. Without it, Sherlock answers from text only.
- **All findings are draft.** Sherlock is a co-investigator, not a final authority. Court submissions require human sign-off.

---

## Getting help

Contact your system administrator or the NVIDIA technical team for:
- Service errors (page not loading, responses failing)
- Adding new evidence to a case
- Processing audio files
- Enabling video analysis
