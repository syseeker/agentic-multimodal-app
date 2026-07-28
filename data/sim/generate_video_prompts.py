#!/usr/bin/env python3
"""
Forensic Case Video Prompt Generator
======================================
Generates CCTV/forensic video prompts for each case from the existing
case text files. NO API calls, NO cost — outputs text prompt files only.

You paste the prompt into your video generation tool of choice:
  - Kling AI (kling.ai) — realistic CCTV-style, good for Singapore settings
  - Runway Gen-3 (runwayml.com)
  - Sora (sora.com)
  - Pika (pika.art)

Output: data/cases/<case_id>/video/video_prompt.txt

Usage:
  python3 data/sim/generate_video_prompts.py
  python3 data/sim/generate_video_prompts.py --case SC-2024-XXXXX
  python3 data/sim/generate_video_prompts.py --all
  python3 data/sim/generate_video_prompts.py --all --format kling
"""
import argparse, json, re, sys
from pathlib import Path

REPO_ROOT  = Path(__file__).parent.parent.parent
CASES_DIR  = REPO_ROOT / "data" / "cases"

# Singapore-specific scene descriptions by district
DISTRICT_SCENES = {
    "Bedok":       "HDB void deck at Bedok, Block 35x, multi-storey car park nearby",
    "Tampines":    "Tampines MRT station bus interchange, busy pedestrian area",
    "Jurong East": "Jurong East shopping belt, Westgate / JEM vicinity",
    "Woodlands":   "Woodlands Causeway checkpoint area, heavy traffic, lorry park",
    "Ang Mo Kio":  "Ang Mo Kio Hub vicinity, town centre, coffee shop area",
    "Clementi":    "Clementi MRT station exit, void deck between blocks",
    "Bukit Timah": "Upper Bukit Timah, landed residential area, quiet street",
    "Geylang":     "Geylang lorong, dimly lit shophouse row, pedestrian walkway",
    "Toa Payoh":   "Toa Payoh HDB estate, wet market area, open-air carpark",
    "Yishun":      "Yishun Ring Road, industrial estate perimeter, loading bay",
    "Hougang":     "Hougang Avenue HDB estate, multi-storey car park, void deck",
    "Punggol":     "Punggol Waterway area, new estate, open park connector path",
}

# Case type → typical visual action for CCTV footage
CASE_TYPE_ACTIONS = {
    "drug_trafficking":   "Two men making a brief exchange near a parked vehicle. One passes a small package.",
    "cybercrime":         "Person at laptop in a coffee shop, looking around nervously, using public WiFi.",
    "financial_fraud":    "Man in business attire handing documents and an envelope to another person.",
    "robbery":            "Masked figure approaching a person from behind near an ATM machine.",
    "homicide":           "Two men in heated argument, shoving, near the lift lobby of an HDB block.",
    "assault":            "Physical altercation between two individuals outside a coffee shop.",
    "human_trafficking":  "Van pulling up slowly, two people quickly entering the vehicle.",
    "money_laundering":   "Two individuals exchanging bags outside a money changer shop.",
}

# Time of day descriptions
def time_of_day(hour: int) -> str:
    if 5 <= hour < 7:   return "early morning, pre-dawn light, street lamps still on"
    if 7 <= hour < 12:  return "morning, natural daylight, some foot traffic"
    if 12 <= hour < 14: return "noon, bright sunlight, busy lunch crowd"
    if 14 <= hour < 18: return "afternoon, warm light, moderate pedestrian traffic"
    if 18 <= hour < 20: return "evening, golden hour transitioning to dusk"
    if 20 <= hour < 23: return "night, dark, orange sodium street lamp glow, sparse foot traffic"
    return "late night, near empty, CCTV night vision mode (slight green tint)"


def extract_incident_summary(case_dir: Path, max_chars: int = 300) -> str:
    """Extract the incident summary from case_report.txt."""
    report = case_dir / "case_report.txt"
    if not report.exists():
        return ""
    text = report.read_text(encoding="utf-8")
    # Find the incident narrative section
    for marker in ["INCIDENT DETAILS", "INCIDENT SUMMARY", "NARRATIVE", "SUMMARY OF INCIDENT"]:
        idx = text.upper().find(marker)
        if idx != -1:
            section = text[idx + len(marker):].strip()
            # Take first non-empty paragraph
            for line in section.splitlines():
                if line.strip() and not line.startswith("=") and not line.startswith("-"):
                    return line.strip()[:max_chars]
    # Fallback: first substantial sentence after the header block
    lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 60]
    return lines[0][:max_chars] if lines else ""


def generate_prompt(case_dir: Path, fmt: str = "generic") -> str:
    meta_file = case_dir / "metadata.json"
    if not meta_file.exists():
        return ""

    meta         = json.loads(meta_file.read_text())
    case_id      = meta.get("case_id", case_dir.name)
    case_type    = meta.get("case_type", "unknown")
    district     = meta.get("district", "Singapore")
    date_str     = meta.get("incident_date", "2024-01-01")
    severity     = meta.get("severity", "medium")
    suspect_name = meta.get("suspect_name", "Unknown")
    suspect_age  = meta.get("suspect_age", "")
    suspect_nat  = meta.get("suspect_nationality", "")

    # Parse date/time
    try:
        from datetime import datetime
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        date_display = dt.strftime("%d %b %Y")
        # Assign a plausible time based on case type
        hour_map = {
            "drug_trafficking": 23, "homicide": 22, "assault": 21,
            "robbery": 20, "financial_fraud": 14, "cybercrime": 11,
            "human_trafficking": 2, "money_laundering": 16,
        }
        hour = hour_map.get(case_type, 20)
        time_display = f"{hour:02d}:{30 if severity == 'high' else 15}"
        day_desc = time_of_day(hour)
    except Exception:
        date_display = date_str
        time_display = "20:30"
        day_desc = "night, dark, street lamp glow"

    scene    = DISTRICT_SCENES.get(district, f"{district} area, Singapore urban environment")
    action   = CASE_TYPE_ACTIONS.get(case_type, "Two individuals in an exchange near an HDB block.")
    summary  = extract_incident_summary(case_dir)
    if summary:
        action = action + f" Context: {summary[:200]}"

    # Format suspect description
    suspect_desc = f"{suspect_name}"
    if suspect_age:
        suspect_desc += f", ~{suspect_age} years old"
    if suspect_nat:
        suspect_desc += f", {suspect_nat}"

    # Build the prompt
    if fmt == "kling":
        prompt = f"""=== KLING AI PROMPT — {case_id} ===
Case: {case_id} | Type: {case_type.replace('_', ' ').title()} | Severity: {severity}

[POSITIVE PROMPT]
Security CCTV footage, 1080p, static wide-angle camera, grainy texture, slight lens distortion. {scene}. {day_desc}. White timestamp overlay top-left showing {date_display} {time_display}. {action} Suspect profile: {suspect_desc}. Documentary-realistic style, no music, ambient Singapore street sounds.

[NEGATIVE PROMPT]
Cartoon, anime, overly cinematic, dramatic lighting, Hollywood style, unrealistic colors, text overlays other than timestamp.

[SETTINGS]
Duration: 10-15 seconds | Aspect: 16:9 | Style: Realistic/documentary | Camera: Static

=== VARIATIONS ===
CLOSE-UP: Tight shot of the exchange or confrontation, face partially visible.
BIRD'S-EYE: Overhead view of {scene.split(',')[0]}, showing movement paths.
NIGHT VISION: Monochrome green-tinted CCTV night mode, timestamp visible.
"""

    elif fmt == "runway":
        prompt = f"""=== RUNWAY GEN-3 PROMPT — {case_id} ===
Style: Realistic security camera footage
Scene: {scene}
Time: {date_display} {time_display} ({day_desc})
Action: {action}
Subject: {suspect_desc}
Camera: Static CCTV, wide angle, grainy 1080p, timestamp overlay
Duration: ~10 seconds
Mood: Documentary, neutral, surveillance aesthetic
"""

    else:  # generic
        prompt = f"""=== VIDEO PROMPT — {case_id} ===
CASE DETAILS
  Case ID    : {case_id}
  Type       : {case_type.replace('_', ' ').title()}
  Date/Time  : {date_display} {time_display}
  Location   : {scene}
  Suspect    : {suspect_desc}
  Severity   : {severity}

CCTV SCENE DESCRIPTION
  Setting  : {scene}
  Lighting : {day_desc}
  Action   : {action}
  Camera   : Static CCTV camera, wide-angle, 1080p, grainy texture,
              white timestamp overlay ({date_display} {time_display})

SUGGESTED VIDEO PROMPT (paste into Kling AI / Runway / Sora / Pika)
  "Security CCTV footage, 1080p, wide angle, grainy, {scene}, {day_desc},
  timestamp overlay {date_display} {time_display}. {action}
  Realistic, documentary style, no dramatic music."

NEGATIVE PROMPT
  "cartoon, anime, cinematic, dramatic, watermark, subtitle, text (except timestamp)"

VARIATIONS TO GENERATE
  1. [ESTABLISHING SHOT] Wide shot of {scene.split(',')[0]} — 10s
  2. [ACTION SHOT]       Close on the exchange/confrontation — 8s
  3. [TRACKING SHOT]     Suspect moving through the scene — 12s
  4. [NIGHT MODE]        Monochrome green CCTV night vision — 10s

TOOL-SPECIFIC TIPS
  Kling AI : Use above positive/negative prompts. Camera motion: Static.
  Runway   : Add "cinematic realism" motion brush on suspect area.
  Sora     : Works well with the exact prompt above as-is.
  Pika     : Set "Noir" or "Documentary" style preset.
"""

    return prompt


def main():
    parser = argparse.ArgumentParser(
        description="Generate video prompts for forensic cases (no API calls, no cost)")
    parser.add_argument("--case", help="One case (e.g. SC-2024-XXXXX)")
    parser.add_argument("--all",  action="store_true", help="All cases")
    parser.add_argument("--format", choices=["generic", "kling", "runway"],
                        default="generic",
                        help="Output format (default: generic with all variants)")
    args = parser.parse_args()

    if not args.case and not args.all:
        parser.print_help(); sys.exit(1)

    case_dirs = [CASES_DIR / args.case] if args.case else sorted(CASES_DIR.glob("SC-*/"))

    generated = 0
    for case_dir in case_dirs:
        if not case_dir.is_dir():
            print(f"WARNING: {case_dir} not found"); continue

        prompt = generate_prompt(case_dir, args.format)
        if not prompt:
            print(f"SKIP {case_dir.name}: metadata.json not found")
            continue

        out = case_dir / "video" / "video_prompt.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(prompt, encoding="utf-8")
        print(f"✓ {case_dir.name}/video/video_prompt.txt")
        generated += 1

    print(f"\n{generated} prompt(s) written.")
    print("Paste the prompt text into your video generation tool:")
    print("  Kling AI  → kling.ai  (good for CCTV-style, Singapore settings)")
    print("  Runway    → runwayml.com")
    print("  Sora      → sora.com")
    print("\nTip: use --format kling or --format runway for tool-specific output.")


if __name__ == "__main__":
    main()
