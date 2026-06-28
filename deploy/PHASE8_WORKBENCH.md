# Phase 8 — Forensic Case Workbench UI

Custom proposal (no skill). Follows DESIGN.md §4.

## What Phase 8 delivers

1. **FastAPI backend** (`ui/server.py`, :8200) — proxies to AI-Q + Neo4j, serves case files
2. **Svelte SPA** (`ui/src/`) — dark forensic theme, 4 panels, SSE chat streaming
3. **Chat with Sherlock** — OpenAI-compatible SSE to AI-Q `/v1/chat/stream`
4. **HITL plan approval** — detect numbered plans in response; Approve/Reject buttons
5. **Entity graph** — Cytoscape.js force-directed view of Neo4j entities/relations
6. **Evidence viewer** — inline file browser + text viewer for all case files
7. **Paralinguistics panel** — audio_analysis.txt display (MERaLiON output)

## Architecture

```
Browser (Svelte SPA — :5173 dev / :8200 prod)
    ↕ REST + Server-Sent Events
FastAPI (:8200)
    ├── /api/cases              → scan data/cases/ + metadata.json
    ├── /api/cases/{id}/graph   → Neo4j → Cytoscape elements format
    ├── /api/cases/{id}/evidence → list + serve text files
    ├── /api/cases/{id}/sentiment → parse audio_analysis.txt
    └── /api/chat               → SSE proxy → AI-Q /v1/chat/stream
```

## Files

| File | Purpose |
|---|---|
| `ui/server.py` | FastAPI backend — all API routes + SPA static serving |
| `ui/package.json` | Svelte + Vite + Cytoscape.js deps |
| `ui/vite.config.js` | Dev server + /api proxy to :8200 |
| `ui/index.html` | SPA entry point |
| `ui/src/main.js` | Svelte mount |
| `ui/src/App.svelte` | Root layout: header + case sidebar + tabbed main panel |
| `ui/src/stores.js` | Svelte stores: selectedCase, chatHistory, pendingPlan, etc. |
| `ui/src/app.css` | Global dark forensic theme (CSS custom properties) |
| `ui/src/lib/CaseSelector.svelte` | Case list with filter; emits 'select' event |
| `ui/src/lib/ChatPanel.svelte` | SSE chat stream + HITL approve/reject banner |
| `ui/src/lib/GraphPanel.svelte` | Cytoscape.js entity graph + node detail panel |
| `ui/src/lib/EvidenceViewer.svelte` | File browser + text viewer |
| `ui/src/lib/SentimentPanel.svelte` | Audio analysis / paralinguistic signals |
| `deploy/compose.workbench.yaml` | Docker Compose for amms-workbench |
| `deploy/phase8_workbench.sh` | Deploy script: npm build + docker up + verify |

## Commands

```bash
# Development (hot-reload)
pip install fastapi uvicorn httpx neo4j
cd ui && npm install && npm run dev      # Svelte dev server :5173 (proxies /api → :8200)
# In another terminal:
cd ui && python3 server.py              # FastAPI :8200

# Production (built SPA served by FastAPI)
cd ui && npm run build                  # → ui/dist/
python3 ui/server.py                    # serves API + static files on :8200

# Docker (all-in-one, no Node.js needed on host)
bash deploy/phase8_workbench.sh
# OR:
docker compose -p amms -f deploy/compose.workbench.yaml up -d
```

## UI Panels

### Chat with Sherlock
- Case context injected as system message on every request: case_id, case_type, district, suspect
- Suggested prompts on empty state: suspects, evidence summary, investigation plan
- HITL detection: when response contains ≥3 numbered steps or "Investigation Plan" heading,
  an approval banner appears at top of chat panel
- Approve → sends "Approved. Please proceed." to continue
- Reject → prompts for reason; sends "Rejected. Please revise: {reason}"

### Entity Graph
- Cytoscape.js cose layout — force-directed, runs client-side
- Node types: Person (blue), Organization (amber), Location (green), Evidence (red)
- Click any node → property detail panel on right
- Toolbar: Fit / Re-layout buttons + node/edge count

### Evidence Viewer
- Left panel: list of .txt and .json files for the case
- Right panel: raw file content in monospace viewer
- Files: case_report.txt, witness_statement.txt, lab_report.txt, whatsapp_chat.txt,
  audio_analysis.txt, metadata.json

### Paralinguistics Panel
- Reads audio_analysis.txt per case
- Extracts stress/pace/tone/confidence/deception signals with regex
- Shows "no audio" guidance (with pipeline command) when audio not processed

## AI-Q Chat API (verified)

```
POST /v1/chat/stream
Body: {
  "messages": [
    {"role": "system", "content": "case context..."},
    {"role": "user", "content": "user message"}
  ],
  "stream": true
}
Response: text/event-stream, OpenAI SSE format
  data: {"choices": [{"delta": {"content": "..."}}]}
  data: [DONE]
```

## Design decisions

- **Svelte + Vite**: matches existing STE MSS front-end stack (confirmed in meeting minutes)
- **FastAPI backend**: Python already on-host; proxies AI-Q + Neo4j without CORS issues
- **SSE streaming**: `fetch()` with `ReadableStream` (EventSource doesn't support POST)
- **HITL detection**: heuristic — ≥3 numbered lines OR "plan" heading in response text
  - Sends standard chat turn for approve/reject (no special API needed)
  - AI-Q clarifier built-in plan approval is conversation-driven
- **Case context injection**: prepend system message with case_id to every chat request
  so Sherlock's graph/RAG tools auto-filter by the correct case
- **No SSR**: pure SPA — investigators run this on desktop/intranet; no public web concerns
- **Docker image reuses python:3.11-slim**: same pattern as Sherlock MCP; installs deps at startup
  - Production: pre-build image with all pip deps baked in

## Known limitations

- Svelte build requires Node 18+ on the host (or run dev mode during development)
- Docker compose container installs pip deps at startup (~45s first run)
- HITL heuristic detects numbered plans reliably but won't catch prose plans
- audio_analysis.txt is sparse — most cases have test stubs only (MERaLiON Phase 4 output)
- Graph re-layout with cose on large graphs (~50+ nodes) can be slow; browser-side only
- Evidence viewer: images/video not viewable as text — binary files excluded by suffix filter
