# VSS Skills Catalog — Sherlock Feature Map

All 15 NVIDIA VSS skills live at `~/skills/skills/vss-*/`.
This file maps each skill to its forensic relevance for the Sherlock product.
Always `cd ~/skills && git pull` before reading any skill files.

---

## Current Phase (Phase 5): Deployed

| Skill | Status | Sherlock Role |
|---|---|---|
| `vss-deploy-profile` (lvs profile) | **Phase 5 — deploying** | Core video analysis engine |

---

## Skills Map: Forensic Relevance

### Tier 1 — Core to Sherlock (implement or plan)

#### `vss-deploy-profile`
**What it does:** Deploys the full VSS stack — video ingest, RTVI, LLM/VLM reasoning, search, alert engine, UI. Multiple profiles: `lvs` (live/recorded video, 2D), `warehouse`, `edge`.
**Sherlock role:** The video specialist sub-agent. Phase 5 deploys the `lvs` profile (recorded CCTV footage). VSS-agent is registered into AI-Q via MCP in Phase 7.
**Relevant profiles:** `lvs` (Phase 5), `warehouse` (future on-prem with GPU)

#### `vss-search-archive`
**What it does:** Natural language search over ingested video archive. Query like "show me anyone in red near the ATM between 9-11am".
**Sherlock role:** Critical — investigators search CCTV archives for suspects without knowing exact timestamps. First tool an investigator would use.
**Phase:** Phase 5 (available once VSS deploys). Wire as MCP tool in Phase 7.

#### `vss-ask-video`
**What it does:** Direct Q&A against a specific video clip. "What is this person doing?" "What objects are visible at timestamp 14:32?"
**Sherlock role:** Deep analysis on a specific clip after `vss-search-archive` locates it. Chain: search → ask. Gives court-defensible cited frame references.
**Phase:** Phase 5 capability, Phase 7 wiring.

#### `vss-generate-video-report`
**What it does:** Generates a structured report from video — who was seen, when, what activity, anomalies.
**Sherlock role:** Directly produces the "video evidence section" of the case report. High value for Phase 8 (case workbench) — auto-fills the video narrative.
**Phase:** Phase 7/8.

#### `vss-manage-alerts`
**What it does:** Define alert rules (e.g. "notify when person enters zone X") and view triggered alerts across the video stream.
**Sherlock role:** Real-time surveillance mode — not the primary use case (Sherlock works on recorded evidence), but relevant for live stakeout scenarios. Could be wired to push alerts to the case workbench.
**Phase:** Phase 7 or post-Phase 9 extension.

#### `vss-setup-behavior-analytics`
**What it does:** Configures behavioral analytics — loitering detection, crowd density, direction of travel, dwell time.
**Sherlock role:** Automatically surfaces behaviorally anomalous individuals in CCTV footage without needing explicit queries. Can flag "suspect loitered near victim for 23 minutes" automatically.
**Phase:** Phase 7 (configure alongside VSS deploy). High value for cold-case analysis.

#### `vss-setup-video-analytics-api`
**What it does:** Exposes VSS's analytics as a REST API for external consumption.
**Sherlock role:** The integration point for Phase 7 MCP wiring. AI-Q calls VSS via this API (wrapped as MCP tools). Also used for Phase 8 UI to pull live analytics.
**Phase:** Phase 5 (available), Phase 7 (wire to AI-Q MCP).

---

### Tier 2 — Valuable Extensions (post-Phase 9)

#### `vss-deploy-dense-captioning`
**What it does:** Generates dense, timestamped textual descriptions of all video content — every frame described in natural language.
**Sherlock role:** Creates a fully searchable text index of video content. Investigators can find "man in blue jacket carrying black bag" even without visual search. Powerful for cross-referencing with witness statements.
**Phase:** Post-Phase 9. Adds depth to the video RAG layer.
**Compute note:** GPU-intensive. Use with H100/A100 NIM. In remote-all mode, use hosted endpoint.

#### `vss-deploy-detection-tracking-2d`
**What it does:** Deploys 2D object detection and multi-object tracking (MOT). Tracks individuals across frames with persistent IDs.
**Sherlock role:** Enables "track this person across all camera feeds." Core for reconstructing a suspect's movement path from entry to exit. Critical for robbery/assault timelines.
**Phase:** Phase 7 or post-Phase 9 extension. Combine with `vss-search-archive` for "find all frames containing person ID 42."

#### `vss-deploy-detection-tracking-3d`
**What it does:** 3D object detection and tracking. Requires depth sensors or stereo cameras.
**Sherlock role:** Relevant only if crime scene has depth-sensing cameras (uncommon in Singapore police). Defer unless specific hardware is available.
**Phase:** Post-Phase 9, hardware-dependent.

#### `vss-deploy-video-embedding`
**What it does:** Generates vector embeddings for video clips. Enables semantic video similarity search ("find clips similar to this reference clip").
**Sherlock role:** Find other CCTV footage that looks similar to a known incident clip. Cross-case pattern detection ("same MO as Case SC-2023-X"). High value for serialised crimes.
**Phase:** Post-Phase 9. Requires Milvus/cuVS for production vector search.

#### `vss-generate-video-calibration`
**What it does:** Generates calibration data for video cameras — lens distortion, homography, real-world coordinate mapping.
**Sherlock role:** Converts pixel coordinates to real-world distances. Enables "suspect was 2.3m from victim at timestamp 14:32" — court-defensible spatial evidence. Important for reconstructing crime scenes from overhead CCTV.
**Phase:** Post-Phase 9 (requires physical camera calibration step on-prem).

#### `vss-manage-video-io-storage`
**What it does:** Manages video ingest sources (RTSP streams, file upload, NVR integration) and storage backends (VIOS, S3, NFS).
**Sherlock role:** Production storage management. Configures how CCTV footage flows into VSS. Critical for on-prem deployment where footage comes from existing NVR systems.
**Phase:** Phase 9 (on-prem hardening). Dev uses file upload; production uses RTSP/NVR.

#### `vss-query-analytics`
**What it does:** Query pre-computed analytics results (heatmaps, traffic counts, dwell times, event logs) stored in the VSS analytics database.
**Sherlock role:** Retrieve aggregated patterns rather than raw video. "How many times did a person enter this zone last Tuesday?" Useful for building the case timeline without replaying raw footage.
**Phase:** Phase 7 (wire as AI-Q tool via VSS analytics API).

#### `vss-summarize-video`
**What it does:** Generates a concise natural-language summary of a video segment.
**Sherlock role:** Auto-generates the "video evidence synopsis" for the case file. Investigators review the summary, approve, and it becomes part of the case record. Direct input to Phase 8 workbench.
**Phase:** Phase 7/8. Works alongside `vss-generate-video-report`.

---

## Recommended Phase 7 MCP Tool Registration Order

When wiring VSS to AI-Q via MCP (Phase 7), prioritize tools in this order:

1. `vss-setup-video-analytics-api` — confirm API is live, expose endpoint
2. `vss-search-archive` → MCP tool: `search_video_archive(query, time_range, camera_id)`
3. `vss-ask-video` → MCP tool: `ask_video(clip_id, question)`
4. `vss-summarize-video` → MCP tool: `summarize_video(clip_id)`
5. `vss-generate-video-report` → MCP tool: `generate_video_report(clip_ids, case_id)`
6. `vss-query-analytics` → MCP tool: `query_video_analytics(metric, time_range)`
7. `vss-manage-alerts` → MCP tool: `create_alert(rule, camera_id, notify_url)`
8. `vss-setup-behavior-analytics` → configure at deploy time, surface alerts via MCP

---

## Skills NOT Deployed in Phase 5

The following skills are for profiles other than `lvs` or require separate deployment:
- `vss-deploy-dense-captioning` — separate NIM deployment
- `vss-deploy-detection-tracking-2d/3d` — separate NIM deployment
- `vss-deploy-video-embedding` — requires Milvus

Read the respective skill MD files before deploying any of these.
