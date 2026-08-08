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
import asyncio
import json
import os
import re
import socket
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastmcp import Context, FastMCP


def _resolve_host_ip() -> str:
    """Address of the Docker host, resolved at runtime — never hardcoded.

    The VSS services this module talks to (rtvi-vlm :8018, VIOS :30888) run on the
    HOST network, while this MCP server runs in a container, so it needs a routable
    host address. A literal IP goes stale the moment the instance is rebuilt (a
    previous instance's 172.31.33.197 was baked in here and silently cost ~30s per
    call in TCP-connect timeouts once the host IP changed).

    Resolution order, first hit wins:
      1. $HOST_IP            — explicit override, always respected
      2. host.docker.internal — the standard in-container route to the host
      3. default-route source IP — works when running directly on the host
      4. 127.0.0.1           — last resort
    """
    explicit = os.environ.get("HOST_IP", "").strip()
    if explicit:
        return explicit
    try:
        return socket.gethostbyname("host.docker.internal")
    except OSError:
        pass
    try:
        # UDP connect sends no packets; it just selects the default-route interface.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("1.1.1.1", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


REPO_ROOT     = Path(__file__).parent.parent
CASES_DIR     = REPO_ROOT / "data" / "cases"
HOST_IP       = _resolve_host_ip()
VSS_AGENT_URL = os.environ.get("VSS_AGENT_URL", f"http://{HOST_IP}:8000")
VSS_LVS_URL   = os.environ.get("VSS_LVS_URL",   f"http://{HOST_IP}:38111")
VIOS_URL      = os.environ.get("VIOS_URL",      f"http://{HOST_IP}:30888")
RTVI_VLM_URL  = os.environ.get("RTVI_VLM_URL",  f"http://{HOST_IP}:8018")
RTVI_VLM_MODEL = os.environ.get("VIA_VLM_OPENAI_MODEL_DEPLOYMENT_NAME",
                                "nim_nvidia_cosmos-reason2-8b_hf-1208")

mcp = FastMCP("vss-sherlock-mcp")


async def _keepalive_while(coro, ctx, label: str, every: float = 2.0):
    """Await `coro`, emitting an MCP progress notification every `every` seconds.

    AI-Q's MCP client builds its transport as `httpx.AsyncClient(headers=..., auth=...)`
    with NO timeout argument (nat/plugins/mcp/client/client_base.py), so it inherits
    httpx's default Timeout(5.0) -- a 5-second READ timeout on the streamable-http
    session. Any tool that goes quiet for >5s makes the client's read fail; it then
    reconnects with a NEW session id, and the reply to the in-flight call is delivered
    to the dead session and dropped. The caller sits there until tool_call_timeout
    (300s) and the workbench shows "No response received".

    Video analysis legitimately takes ~26s (vss-agent) to ~46s (VLM direct) on GB10, so
    every video call tripped this. On x86 with rtvi-vlm the same call returns in ~4s,
    which is why it only shows up on aarch64.

    Progress notifications are traffic on that session, so the read never idles out.
    Ticking well inside the 5s budget keeps the client alive for the whole call.
    """
    task = asyncio.ensure_future(coro)
    waited = 0.0
    while not task.done():
        done, _ = await asyncio.wait({task}, timeout=every)
        if done:
            break
        waited += every
        if ctx is not None:
            try:
                # log(), not report_progress(): progress notifications are silently
                # dropped unless the client sent a progressToken, and AI-Q's call_tool
                # does not (it passes only read_timeout_seconds). A log notification is
                # unconditional, so it always puts bytes on the session.
                await ctx.log(f"{label} — {int(waited)}s elapsed", level="info")
            except Exception:
                pass  # keepalive is best-effort; never fail the tool over it
    return await task


def _vss_agent_text(data: dict) -> str:
    """Answer text out of a vss-agent /generate response.

    /generate replies {"value": "<text>"} — NOT the OpenAI
    {"choices":[{"message":{"content":...}}]} shape that /v1/chat/completions uses.
    Reading choices[0] against a /generate reply silently yields "", so the tool
    returned an empty summary and AI-Q had nothing to answer with. Accept both.
    """
    if not isinstance(data, dict):
        return str(data)
    choices = data.get("choices") or []
    if choices:
        content = (choices[0].get("message") or {}).get("content") or ""
        if content:
            return content
    return data.get("value") or ""


async def resolve_vios_url(case_id: str, video_stem: str) -> str | None:
    """VIOS download URL for one case's video, or None if that case has no such video.

    Two correctness rules, both learned the hard way:

    1. The filename must contain BOTH the case id AND the video stem. Matching on the
       stem alone (or on `case_id OR stem`, as this did) meant a case with no registered
       video silently matched ANOTHER case's footage -- observed live: an ask_video call
       for SC-2024-22DEEE33 was answered with SC-2024-03C5F0E4's men_assault video.
       Presenting one case's footage as another's is evidence contamination; returning
       "no video" is always the correct answer when this case has none.

    2. When several registrations match, take the MOST RECENT. VIOS cannot delete or
       overwrite (see process_video.py::content_sensor_name), so a re-uploaded video adds
       a second entry and the older one is still there. Iterating in dict order picked the
       oldest, i.e. the superseded footage.
    """
    try:
        async with httpx.AsyncClient() as client:
            tl_resp = await client.get(f"{VIOS_URL}/vst/api/v1/storage/timelines", timeout=5.0)
            tl_data = json.loads(tl_resp.text)
    except Exception:
        return None
    if not tl_data:
        return None

    matches = []
    async with httpx.AsyncClient() as client:
        for file_uuid, entries in (tl_data or {}).items():
            if not entries:
                continue
            ent = entries[0]
            try:
                url_ep = (f"{VIOS_URL}/vst/api/v1/storage/file/{file_uuid}/url"
                          f"?startTime={ent['startTime']}&endTime={ent['endTime']}"
                          f"&blocking=true&disableAudio=true")
                candidate = json.loads((await client.get(url_ep, timeout=5.0)).text).get("videoUrl", "")
            except Exception:
                continue
            name = candidate.rsplit("/", 1)[-1]
            if case_id in name and video_stem in name:
                matches.append((ent.get("startTime", ""), candidate))

    if not matches:
        return None
    _, newest = max(matches, key=lambda m: m[0])
    # rtvi-vlm is on the host network, so rewrite loopback to the resolved host
    # address -- a container's "localhost" is itself.
    return newest.replace("localhost", HOST_IP).replace("127.0.0.1", HOST_IP)

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
async def ask_video(case_id: str, video_id: str, question: str, ctx: Context = None) -> str:
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
    # RTVI_VLM_URL / RTVI_VLM_MODEL are module-level (host resolved at import).

    # Get the VIOS download URL for this video (UUID-based temp_files path).
    # Scoped to THIS case — never falls back to another case's footage.
    video_url = await resolve_vios_url(case_id, video_file.stem)

    if video_url:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
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
                        "num_frames_per_second_or_fixed_frames_chunk": 1.0,
                        "use_fps_for_chunking": True,
                    },
                    timeout=httpx.Timeout(30.0, connect=2.0),
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
        except Exception:
            pass  # Fall through to vss-agent fallback

    # Fallback: vss-agent /generate (slower ~30s but more capable)
    sensor_id = f"{case_id}_{video_file.stem}"
    instruction = (
        f"Call the video_understanding tool to answer the following forensic question "
        f"about the video evidence file '{sensor_id}' for case {case_id}: {question}"
    )
    try:
        async def _call():
            async with httpx.AsyncClient() as client:
                return await client.post(
                    f"{VSS_AGENT_URL}/generate",
                    json={"input_message": instruction},
                    timeout=120.0,
                )
        resp = await _keepalive_while(_call(), ctx, f"Analysing video for {case_id}")
        resp.raise_for_status()
        data = resp.json()
        answer = _vss_agent_text(data)
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
async def summarize_video(
    case_id:  str,
    video_id: str,
    scenario: str = "",
    events:   str = "",
    ctx:      Context = None,
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

    # Get the VIOS temp_files URL via UUID (name-based URL returns 400 from rtvi-vlm).
    # Scoped to THIS case — never falls back to another case's footage.
    clip_url = await resolve_vios_url(case_id, video_file.stem)
    if not clip_url:
        # Fail fast and honestly. Previously this fell through to LVS /v1/summarize with
        # a name-based URL that VIOS rejects; LVS then blocked until AI-Q's 300s tool
        # timeout, so "video not registered" presented as a hung query.
        return json.dumps({
            "case_id":  case_id,
            "video_id": video_id,
            "error":    (f"'{video_id}' is on disk for {case_id} but is not registered in VIOS, "
                         f"so it cannot be analysed. Re-upload it via the workbench, or run: "
                         f"uv run data/video/process_video.py --case-id {case_id}"),
        }, indent=2)

    # FAST PATH: call rtvi-vlm /v1/chat/completions directly with summary prompt.
    # Bypasses LVS /v1/summarize which adds a 20-30s LLM synthesis step (total >30s).
    # The SSE keepalive window is ~30s — any tool taking longer loses the session.
    # RTVI_VLM_URL / RTVI_VLM_MODEL are module-level (host resolved at import).
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
            async def _rtvi_call():
                async with httpx.AsyncClient() as client:
                    return await client.post(
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
                            "num_frames_per_second_or_fixed_frames_chunk": 1.0,
                            "use_fps_for_chunking": True,
                        },
                        timeout=httpx.Timeout(20.0, connect=2.0),
                    )
            rtvi_resp = await _keepalive_while(_rtvi_call(), ctx, f"Analysing video for {case_id}")
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
    model_id = "nim_nvidia_cosmos3-nano-reasoner_bf16-final"  # skill default
    try:
        async with httpx.AsyncClient() as client:
            models_resp = await client.get(f"{VSS_LVS_URL}/models", timeout=10.0)
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
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{VSS_LVS_URL}/v1/summarize",
                json=payload,
                timeout=45.0,
            )
        resp.raise_for_status()
        data = resp.json()

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

    except Exception as e:
        # Fallback: use vss-agent /generate if LVS fails (connection refused, timeout, or HTTP error)
        fallback_sensor_id = f"{case_id}_{video_file.stem}"
        try:
            async def _fb_call():
                async with httpx.AsyncClient() as client:
                    return await client.post(
                        f"{VSS_AGENT_URL}/generate",
                        json={"input_message": (
                            f"Summarise the video evidence '{fallback_sensor_id}' for case {case_id}. "
                            f"Focus on: {', '.join(events_list)}. "
                            f"Context: {scenario}. "
                            f"Provide a timestamped narrative of key events."
                        )},
                        timeout=120.0,
                    )
            fallback_resp = await _keepalive_while(_fb_call(), ctx, f"Summarising video for {case_id}")
            fallback_resp.raise_for_status()
            fb_data    = fallback_resp.json()
            fb_content = _vss_agent_text(fb_data)
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


if __name__ == "__main__":
    port = int(os.environ.get("VSS_MCP_PORT", "9903"))
    print(f"VSS Sherlock MCP server starting on http://0.0.0.0:{port}/mcp", flush=True)
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port, allowed_hosts=["*"])
