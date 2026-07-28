"""
VSS Sherlock MCP Server — Video Evidence Tools
================================================
Exposes VSS video capabilities to Sherlock (AI-Q) as MCP tools.
Wraps vss-agent (:8000) and vss-lvs (:38111) from the LVS profile.

Skills referenced (read ALL before modifying):
  ~/skills/skills/vss-ask-video/SKILL.md
  ~/skills/skills/vss-summarize-video/SKILL.md
  ~/skills/skills/vss-manage-video-io-storage/SKILL.md

Tools:
  list_case_videos(case_id)          → list videos uploaded for a case
  ask_video(case_id, video_id, q)    → VLM Q&A on a specific clip
  summarize_video(case_id, video_id) → HITL-free narrative summary + timestamps

Usage (standalone):
  uv run --with fastmcp mcp/vss_sherlock_mcp.py
"""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastmcp import FastMCP

REPO_ROOT     = Path(__file__).parent.parent
CASES_DIR     = REPO_ROOT / "data" / "cases"
VSS_AGENT_URL = os.environ.get("VSS_AGENT_URL", "http://localhost:8000")
VSS_LVS_URL   = os.environ.get("VSS_LVS_URL",   "http://localhost:38111")
VIOS_URL      = os.environ.get("VIOS_URL",       "http://localhost:30888")

mcp = FastMCP("vss-sherlock-mcp")

# ── Case type → (scenario, events) for auto-derive when not supplied ──────────
_CASE_SCENARIOS = {
    "drug_trafficking":  ("forensic drug trafficking investigation",
                          ["exchange of package", "cash transaction", "suspicious vehicle",
                           "lookout behavior", "disposal of evidence"]),
    "homicide":          ("forensic homicide investigation",
                          ["altercation", "physical assault", "victim on ground",
                           "suspect fleeing", "weapon visible"]),
    "robbery":           ("forensic robbery investigation",
                          ["approach victim", "threat display", "property taken",
                           "suspect fleeing", "bystander reaction"]),
    "cybercrime":        ("forensic cybercrime scene investigation",
                          ["suspect at computer", "USB device inserted",
                           "document photographed", "suspicious behavior"]),
    "financial_fraud":   ("forensic financial fraud investigation",
                          ["document exchange", "cash handover", "identity concealment",
                           "meeting at unusual location"]),
    "assault":           ("forensic assault investigation",
                          ["confrontation", "physical contact", "victim injured",
                           "suspect fleeing", "bystander present"]),
    "human_trafficking": ("forensic human trafficking investigation",
                          ["vehicle pickup", "group movement", "coercion visible",
                           "identity concealment", "handover of persons"]),
    "money_laundering":  ("forensic money laundering investigation",
                          ["large cash movement", "bag exchange", "multiple couriers",
                           "structured deposits", "coordination meeting"]),
}
_DEFAULT_SCENARIO = ("forensic investigation", ["suspicious activity", "person movement",
                                                 "object exchange", "vehicle activity"])


def _case_meta(case_id: str) -> dict:
    meta_file = CASES_DIR / case_id / "metadata.json"
    if meta_file.exists():
        return json.loads(meta_file.read_text())
    return {}


def _auto_scenario(case_id: str) -> tuple[str, list[str]]:
    meta = _case_meta(case_id)
    ct   = meta.get("case_type", "")
    return _CASE_SCENARIOS.get(ct, _DEFAULT_SCENARIO)


def _video_dir(case_id: str) -> Path:
    return CASES_DIR / case_id / "video"


# ── Tools ──────────────────────────────────────────────────────────────────────

@mcp.tool()
def list_case_videos(case_id: str) -> str:
    """List video files uploaded for a forensic case.

    Args:
        case_id: Case identifier (e.g. SC-2024-XXXXX)

    Returns:
        JSON list of video files with metadata.
    """
    video_dir = _video_dir(case_id)
    if not video_dir.exists():
        return json.dumps({"case_id": case_id, "videos": [], "message": "No video directory"})

    MEDIA_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".m4v"}
    videos = []
    for f in sorted(video_dir.iterdir()):
        if f.suffix.lower() in MEDIA_EXTS:
            stat = f.stat()
            videos.append({
                "video_id":  f.stem,
                "filename":  f.name,
                "size_mb":   round(stat.st_size / 1_048_576, 2),
                "uploaded":  datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            })

    return json.dumps({"case_id": case_id, "videos": videos, "count": len(videos)}, indent=2)


@mcp.tool()
def ask_video(case_id: str, video_id: str, question: str) -> str:
    """Ask a visual question about a specific video clip for a forensic case.

    Uses VSS vss-agent's video_understanding tool for fresh VLM inference
    on the uploaded video clip. Best for specific factual questions about
    what is visible in the footage.

    Skill: vss-ask-video (POST /generate on vss-agent with video_understanding call)

    Args:
        case_id:   Case identifier (e.g. SC-2024-XXXXX)
        video_id:  Video identifier (filename without extension)
        question:  Visual question to answer (e.g. "What is the suspect wearing?
                   Describe the events at 00:42.")

    Returns:
        VLM answer citing what is visible in the video.
    """
    # Resolve file path
    video_dir = _video_dir(case_id)
    video_file = None
    for ext in [".mp4", ".mov", ".avi", ".mkv", ".m4v", ".wmv"]:
        candidate = video_dir / f"{video_id}{ext}"
        if candidate.exists():
            video_file = candidate
            break

    if not video_file:
        return json.dumps({"error": f"Video {video_id} not found for case {case_id}. "
                           f"Upload it first via the workbench."})

    # Direct rtvi-vlm call via /v1/chat/completions (OpenAI multimodal format).
    # Bypasses vss-agent /generate which adds 25-30s overhead due to its own agent loop.
    # rtvi-vlm accepts video_url in message content and returns VLM answer in ~4-8 seconds.
    RTVI_VLM_URL = os.environ.get("RTVI_VLM_URL", "http://172.31.33.197:8018")
    RTVI_VLM_MODEL = os.environ.get("VIA_VLM_OPENAI_MODEL_DEPLOYMENT_NAME", "nim_nvidia_cosmos-reason2-8b_hf-1208")

    # Get the VIOS download URL for this video (UUID-based temp_files path)
    video_url = None
    try:
        vios_base = VIOS_URL  # e.g. http://localhost:30888
        tl_resp = httpx.get(f"{vios_base}/vst/api/v1/storage/timelines", timeout=5.0)
        tl_data = tl_resp.json() if "json" in tl_resp.headers.get("content-type","") else \
                  __import__("json").loads(tl_resp.text)
        for file_uuid, entries in tl_data.items():
            if entries:
                ent = entries[0]
                url_ep = (f"{vios_base}/vst/api/v1/storage/file/{file_uuid}/url"
                          f"?startTime={ent['startTime']}&endTime={ent['endTime']}"
                          f"&blocking=true&disableAudio=true")
                u_resp = httpx.get(url_ep, timeout=5.0)
                u_data = __import__("json").loads(u_resp.text)
                candidate = u_data.get("videoUrl", "")
                if video_file.stem.split("_")[0] in candidate or case_id in candidate:
                    # Use the IP that rtvi-vlm can reach (it's on host network)
                    video_url = candidate.replace("localhost", "172.31.33.197")
                    break
    except Exception as vios_e:
        pass  # Fall through to vss-agent fallback

    if video_url:
        try:
            resp = httpx.post(
                f"{RTVI_VLM_URL}/v1/chat/completions",
                json={
                    "model": RTVI_VLM_MODEL,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "video_url", "video_url": {"url": video_url}},
                            {"type": "text", "text": f"Forensic video analysis for case {case_id}. {question}"},
                        ]
                    }],
                    "max_tokens": 1024,
                    "num_frames_per_second_or_fixed_frames_chunk": 1.0,  # 1 fps → 10 frames for 10s clip
                    "use_fps_for_chunking": True,
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            answer = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            if answer:
                return json.dumps({
                    "case_id":  case_id,
                    "video_id": video_id,
                    "question": question,
                    "answer":   answer,
                    "source":   "rtvi-vlm direct",
                }, indent=2)
        except Exception as rtvi_e:
            pass  # Fall through to vss-agent fallback

    # Fallback: vss-agent /generate (slower ~30s but more capable)
    sensor_id = f"{case_id}_{video_file.name}"
    instruction = (
        f"Call the video_understanding tool to answer the following forensic question "
        f"about the video evidence file '{sensor_id}' for case {case_id}: {question}"
    )
    try:
        resp = httpx.post(
            f"{VSS_AGENT_URL}/generate",
            json={"input_message": instruction},
            timeout=120.0,
        )
        resp.raise_for_status()
        data = resp.json()
        answer = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        answer = re.sub(r"<agent-think>.*?</agent-think>", "", answer, flags=re.DOTALL).strip()
        return json.dumps({
            "case_id":  case_id,
            "video_id": video_id,
            "question": question,
            "answer":   answer or str(data),
            "source":   "vss-agent fallback",
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "hint": "Ensure vss-agent and rtvi-vlm are running"})


@mcp.tool()
def summarize_video(
    case_id:  str,
    video_id: str,
    scenario: str = "",
    events:   str = "",
) -> str:
    """Generate a narrative summary with timestamped events for a forensic video.

    Uses VSS vss-lvs (Long Video Summarization service) to chunk the video,
    caption each segment via RT-VLM, and produce a structured evidence report.
    Best for long recordings (minutes to hours) where a full timeline is needed.

    Skill: vss-summarize-video (POST /v1/summarize on vss-lvs :38111)

    Args:
        case_id:  Case identifier (e.g. SC-2024-XXXXX)
        video_id: Video identifier (filename without extension)
        scenario: Investigation scenario (e.g. "drug trafficking near Bedok MRT").
                  Auto-derived from case type if not provided.
        events:   Comma-separated events to look for
                  (e.g. "package exchange,suspect vehicle,lookout behavior").
                  Auto-derived from case type if not provided.

    Returns:
        JSON with video_summary (narrative) and events (timestamped list).
    """
    video_dir = _video_dir(case_id)
    video_file = None
    for ext in [".mp4", ".mov", ".avi", ".mkv", ".m4v", ".wmv"]:
        candidate = video_dir / f"{video_id}{ext}"
        if candidate.exists():
            video_file = candidate
            break

    if not video_file:
        return json.dumps({"error": f"Video {video_id} not found for case {case_id}."})

    # Auto-derive scenario/events from case metadata if not supplied
    if not scenario or not events:
        auto_scenario, auto_events = _auto_scenario(case_id)
        scenario = scenario or auto_scenario
        events_list = [e.strip() for e in events.split(",") if e.strip()] if events else auto_events
    else:
        events_list = [e.strip() for e in events.split(",") if e.strip()]

    # Get the VIOS temp_files URL via UUID (name-based URL returns 400 from rtvi-vlm)
    sensor_id = f"{case_id}_{video_file.name}"
    clip_url  = f"{VIOS_URL}/vst/api/v1/storage/file/{sensor_id}"  # fallback (may fail)
    try:
        tl_resp = httpx.get(f"{VIOS_URL}/vst/api/v1/storage/timelines", timeout=5.0)
        tl_data = __import__("json").loads(tl_resp.text)
        for file_uuid, entries in tl_data.items():
            if entries:
                ent = entries[0]
                url_ep = (f"{VIOS_URL}/vst/api/v1/storage/file/{file_uuid}/url"
                          f"?startTime={ent['startTime']}&endTime={ent['endTime']}"
                          f"&blocking=true&disableAudio=true")
                u_resp = httpx.get(url_ep, timeout=5.0)
                u_data = __import__("json").loads(u_resp.text)
                v_url = u_data.get("videoUrl", "")
                if v_url and (video_file.stem.split("_")[0] in v_url or case_id in v_url):
                    clip_url = v_url  # use temp_files URL with correct IP
                    break
    except Exception:
        pass  # use fallback clip_url

    # FAST PATH: call rtvi-vlm /v1/chat/completions directly with summary prompt.
    # Bypasses LVS /v1/summarize which adds a 20-30s LLM synthesis step (total >30s).
    # The SSE keepalive window is ~30s — any tool taking longer loses the session.
    RTVI_VLM_URL = os.environ.get("RTVI_VLM_URL", "http://172.31.33.197:8018")
    RTVI_VLM_MODEL = os.environ.get("VIA_VLM_OPENAI_MODEL_DEPLOYMENT_NAME", "nim_nvidia_cosmos-reason2-8b_hf-1208")
    if clip_url and "temp_files" in clip_url:
        try:
            events_str = ", ".join(events_list)
            summary_prompt = (
                f"You are a forensic video analyst. Analyze this video evidence for case {case_id}. "
                f"Context: {scenario}. "
                f"Focus on detecting: {events_str}. "
                f"Provide a detailed narrative summary of all events visible in the footage, "
                f"including persons, actions, timeline, and any forensic-relevant observations."
            )
            rtvi_resp = httpx.post(
                f"{RTVI_VLM_URL}/v1/chat/completions",
                json={
                    "model": RTVI_VLM_MODEL,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "video_url", "video_url": {"url": clip_url}},
                            {"type": "text", "text": summary_prompt},
                        ]
                    }],
                    "max_tokens": 1024,
                    "num_frames_per_second_or_fixed_frames_chunk": 1.0,  # 1 fps → full temporal coverage
                    "use_fps_for_chunking": True,
                },
                timeout=20.0,
            )
            rtvi_resp.raise_for_status()
            answer = rtvi_resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            if answer:
                return json.dumps({
                    "case_id":       case_id,
                    "video_id":      video_id,
                    "scenario":      scenario,
                    "events_sought": events_list,
                    "summary":       answer,
                    "events_found":  [],
                    "source":        "rtvi-vlm direct",
                }, indent=2)
        except Exception:
            pass  # fall through to LVS path

    # LVS PATH (fallback): POST /v1/summarize — slower but more structured
    try:
        # Get model name from LVS (it reads from RT-VLM internally)
        models_resp = httpx.get(f"{VSS_LVS_URL}/models", timeout=10.0)
        model_id = "nim_nvidia_cosmos3-nano-reasoner_bf16-final"  # skill default
        if models_resp.status_code == 200:
            models_data = models_resp.json()
            if models_data.get("data"):
                model_id = models_data["data"][0].get("id", model_id)
    except Exception:
        pass  # use default

    payload = {
        "model":    model_id,
        "scenario": scenario,
        "events":   events_list,
        "url":      clip_url,
        "chunk_duration":                         10,
        "num_frames_per_second_or_fixed_frames_chunk": 1,
    }

    try:
        resp = httpx.post(
            f"{VSS_LVS_URL}/v1/summarize",
            json=payload,
            timeout=45.0,    # if LVS/generate_captions fails (VIOS URL issue), fall back to vss-agent quickly
        )
        resp.raise_for_status()
        data = resp.json()

        # Parse structured response (vss-summarize-video skill pattern)
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
        try:
            structured = json.loads(content) if isinstance(content, str) else content
        except json.JSONDecodeError:
            structured = {"video_summary": content, "events": []}

        return json.dumps({
            "case_id":       case_id,
            "video_id":      video_id,
            "scenario":      scenario,
            "events_sought": events_list,
            "summary":       structured.get("video_summary", ""),
            "events_found":  structured.get("events", []),
        }, indent=2)

    except httpx.HTTPStatusError as e:
        # Fallback: use vss-agent /generate if LVS fails (vss-summarize-video skill fallback)
        try:
            fallback_resp = httpx.post(
                f"{VSS_AGENT_URL}/generate",
                json={"input_message": (
                    f"Summarise the video evidence '{sensor_id}' for case {case_id}. "
                    f"Focus on: {', '.join(events_list)}. "
                    f"Context: {scenario}. "
                    f"Provide a timestamped narrative of key events."
                )},
                timeout=120.0,
            )
            fallback_resp.raise_for_status()
            fb_data    = fallback_resp.json()
            fb_content = fb_data.get("choices", [{}])[0].get("message", {}).get("content", "")
            fb_content = re.sub(r"<agent-think>.*?</agent-think>", "", fb_content, flags=re.DOTALL).strip()
            return json.dumps({
                "case_id":       case_id,
                "video_id":      video_id,
                "note":          "LVS unavailable — used vss-agent fallback (lower quality)",
                "summary":       fb_content,
                "events_found":  [],
            }, indent=2)
        except Exception as fallback_e:
            return json.dumps({"error": str(e), "fallback_error": str(fallback_e)})

    except Exception as e:
        return json.dumps({"error": str(e)})


if __name__ == "__main__":
    port = int(os.environ.get("VSS_MCP_PORT", "9903"))
    print(f"VSS Sherlock MCP server starting on http://0.0.0.0:{port}/mcp", flush=True)
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port, allowed_hosts=["*"])
