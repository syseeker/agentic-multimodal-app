#!/usr/bin/env python3
# /// script
# dependencies = ["nvidia-riva-client", "soundfile", "numpy", "scipy", "requests", "omnivoice"]
# ///
"""
Forensic Case Audio Sample Generator
=====================================
Generates synthetic audio evidence WAV files for forensic cases using TTS.
Two modes:
  1) Magpie TTS  — NVIDIA hosted (NVCF cloud gRPC, no GPU needed)
  2) MERaLiON Hokkien TTS — self-hosted on GPU (Hokkien / Southern Min audio)

Case mode (--case / --all):
  Reads witness_statement.txt → audio/witness_interview.wav
       whatsapp_chat.txt      → audio/phone_call_recording.wav

Single-file mode (--file):
  Synthesizes any text file to a WAV at --output (or <case>/audio/<stem>.wav)

Usage:
  uv run data/sim/generate_audio_samples.py --case SC-2024-XXXXX --tts magpie
  uv run data/sim/generate_audio_samples.py --all --tts magpie
  uv run data/sim/generate_audio_samples.py --case SC-2024-XXXXX --tts hokkien
  uv run data/sim/generate_audio_samples.py --file interview.txt --case SC-2024-XXXXX --tts magpie --voice suspect
  uv run data/sim/generate_audio_samples.py --file dialogue.txt --output out.wav --tts hokkien

Magpie configurability:
  --magpie-model   NVCF model name  (default: ai-magpie-tts-multilingual)
                   Also readable from env var MAGPIE_MODEL.
  --voice          Role alias (witness/suspect/officer/default) OR a full Magpie
                   voice name (e.g. Magpie-Multilingual.EN-US.Ryan).
                   See MAGPIE_VOICES below for the alias→name mapping.

Notes:
  - Magpie TTS requires NVIDIA_API_KEY (NVCF cloud, no GPU)
  - MERaLiON Hokkien TTS requires GPU + HF_TOKEN + omnivoice library
  - Hokkien text input must be Chinese hanzi (Southern Min); romanisation not supported
  - These are SIMULATED recordings; Phase 4 will ASR-transcribe them for RAG
"""
import argparse, json, os, re, struct, sys, wave
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
CASES_DIR = REPO_ROOT / "data" / "cases"

# Magpie TTS voice table — format: Magpie-Multilingual.{LOCALE}.{Speaker}
# Each entry: (voice_name, language_code) — both must be passed to tts.synthesize().
# Source: https://docs.nvidia.com/nim/speech/latest/reference/support-matrix/tts.html
# Supported locales on ai-magpie-tts-multilingual: en-US, zh-CN, vi-VN, hi-IN,
#   es-US, fr-FR, de-DE, it-IT, ja-JP. Malay (ms-MY) is NOT supported.
MAGPIE_VOICES = {
    # Singapore English — SPF forensic roles
    "witness":       ("Magpie-Multilingual.EN-US.Sofia",    "en-US"),  # female witness
    "suspect":       ("Magpie-Multilingual.EN-US.Jason",    "en-US"),  # male suspect
    "officer":       ("Magpie-Multilingual.EN-US.Ray",      "en-US"),  # male SPF officer
    "default":       ("Magpie-Multilingual.EN-US.Sofia",    "en-US"),
    # Multilingual — Singapore demographic mix
    "mandarin":      ("Magpie-Multilingual.ZH-CN.HouZhen",  "zh-CN"),  # Mandarin speaker
    "vietnamese-m":  ("Magpie-Multilingual.VI-VN.Long",     "vi-VN"),  # Vietnamese male
    "vietnamese-f":  ("Magpie-Multilingual.VI-VN.Louise",   "vi-VN"),  # Vietnamese female
    "hindi-f":       ("Magpie-Multilingual.HI-IN.Sofia",    "hi-IN"),
    "hindi-m":       ("Magpie-Multilingual.HI-IN.Leo",      "hi-IN"),
    # Note: Malay (ms-MY) not available on Magpie — use en-US fallback for Malay chars.
    # For Malay TTS, Chatterbox TTS Multilingual supports ms-MY but is male-only + 52 GB GPU.
}

# Voice pool for multi-speaker chat assignment — rotated per unique speaker.
# All voices confirmed on ai-magpie-tts-multilingual (support matrix 2026-07).
# Format: (voice_name, language_code, gender)
_VOICE_POOL_EN = [
    ("Magpie-Multilingual.EN-US.Jason", "en-US", "M"),
    ("Magpie-Multilingual.EN-US.Sofia", "en-US", "F"),
    ("Magpie-Multilingual.EN-US.Ray",   "en-US", "M"),
    ("Magpie-Multilingual.EN-US.Leo",   "en-US", "M"),
    ("Magpie-Multilingual.EN-US.Mia",   "en-US", "F"),
    ("Magpie-Multilingual.EN-US.Aria",  "en-US", "F"),
]
_VOICE_POOL_ZH = [
    ("Magpie-Multilingual.ZH-CN.HouZhen", "zh-CN", "M"),
    ("Magpie-Multilingual.ZH-CN.Siwei",   "zh-CN", "F"),
]
_VOICE_POOL_VI = [
    ("Magpie-Multilingual.VI-VN.Long",    "vi-VN", "M"),
    ("Magpie-Multilingual.VI-VN.Louise",  "vi-VN", "F"),
    ("Magpie-Multilingual.VI-VN.Jason",   "vi-VN", "M"),
    ("Magpie-Multilingual.VI-VN.Isabela", "vi-VN", "F"),
]
_VOICE_POOL_HI = [
    ("Magpie-Multilingual.HI-IN.Leo",   "hi-IN", "M"),
    ("Magpie-Multilingual.HI-IN.Sofia", "hi-IN", "F"),
]


def infer_voice_from_name(name: str) -> tuple:
    """Infer (voice_name, language_code) from a speaker's display name.
    Detects language family and gender from name patterns common in Singapore forensic cases.
    Falls back to en-US when ambiguous. Malay (ms-MY) not supported by Magpie → en-US.
    """
    n = name.strip().lower()
    tokens = n.split()

    # ── Vietnamese: surnames Nguyen/Tran/Le/Pham/Bui/Hoang/Vo/Ngo/Duong/Do
    viet_surnames = {"nguyen","tran","le","pham","bui","hoang","vo","ngo","duong","do","doan","ly","huynh","dinh","dang"}
    if any(t in viet_surnames for t in tokens):
        # Van/Huu/Duc/Quang/Minh/Thanh/Hung/Tuan/Bao = male; Thi/Ngoc/Lan/Huong = female
        male_tokens = {"van","huu","duc","quang","minh","hung","tuan","bao","thanh","manh","cuong","khanh"}
        female_tokens = {"thi","ngoc","lan","huong","linh","mai","yen","thu","tuyen"}
        gender = "F" if any(t in female_tokens for t in tokens) else "M"
        pool = [v for v in _VOICE_POOL_VI if v[2] == gender]
        return pool[0][:2]  # (voice_name, language_code)

    # ── Mandarin/Chinese: surnames Tan/Lim/Wong/Chan/Chen/Lee/Ng/Goh/Ong/Sim/Chua/Yeo/Ho
    zh_surnames = {"tan","lim","wong","chan","chen","lee","ng","goh","ong","sim","chua","yeo","ho","zhang","wang","liu","yang","xu","huang","wu","lin"}
    if any(t in zh_surnames for t in tokens):
        # Common female Chinese given names ending in common patterns
        # Mandarin pinyin + common Hokkien/Cantonese female syllables (bee, mui, poh, kim, choo, ah)
        female_given = {"mei","ying","hui","xian","ling","fang","yun","qin","zhen","jing","yan","li","na","xia","hua",
                        "bee","mui","poh","kim","choo","eng","geok","lian","noi","siew","swee","wah","lay","ley"}
        gender = "F" if any(t in female_given for t in tokens) else "M"
        pool = [v for v in _VOICE_POOL_ZH if v[2] == gender]
        return (pool or _VOICE_POOL_ZH)[0][:2]

    # ── Indian (South Asian): surnames Singh/Kumar/Raj/Patel/Nair/Pillai/Krishnan/Murugan
    indian_surnames = {"singh","kumar","raj","patel","nair","pillai","krishnan","murugan","rajan","suresh","ramesh","arumugam","shankar","gopal","venkat"}
    indian_female = {"priya","anitha","kavitha","sridevi","meenakshi","lakshmi","radha","devi","sundari","malathi","nirmala","uma"}
    if any(t in indian_surnames for t in tokens) or any(t in indian_female for t in tokens):
        gender = "F" if any(t in indian_female for t in tokens) else "M"
        pool = [v for v in _VOICE_POOL_HI if v[2] == gender]
        return (pool or _VOICE_POOL_HI)[0][:2]

    # ── Malay: bin/binte markers or common Malay names
    # ms-MY not supported — fall through to en-US with gender detection
    malay_male = {"bin","ahmad","mohamed","hassan","ibrahim","yusof","ali","razak","aziz","zainal","ismail","halim","fadzil","nazri"}
    malay_female = {"binte","bte","nur","nurul","siti","aishah","faridah","zainab","rohana","hamidah","norzahra","azizah"}
    if any(t in malay_male for t in tokens):
        return ("Magpie-Multilingual.EN-US.Jason", "en-US")
    if any(t in malay_female for t in tokens):
        return ("Magpie-Multilingual.EN-US.Sofia", "en-US")

    # ── Fallback: en-US, naive gender from common English female names
    female_en = {"mary","jane","lisa","emily","jessica","sarah","jennifer","linda","susan","karen","patricia","jessica","anna","emma","olivia","jenny","amy","alice","helen","grace"}
    gender = "F" if any(t in female_en for t in tokens) else "M"
    pool = [v for v in _VOICE_POOL_EN if v[2] == gender]
    return (pool or _VOICE_POOL_EN)[0][:2]


def assign_chat_voices(speakers: list, primary_voice_arg: str) -> dict:
    """Assign a unique (voice_name, language_code) to each speaker in a chat.
    Primary/first speaker uses the --voice arg. Others are inferred from their name.
    Guarantees no two speakers share the same voice_name.
    """
    voice_map = {}
    used_voices = set()

    # First speaker: respect --voice flag
    primary_vn, primary_lc = resolve_voice(primary_voice_arg)
    voice_map[speakers[0]] = (primary_vn, primary_lc)
    used_voices.add(primary_vn)

    # Remaining speakers: infer from name, avoid duplicates
    for sp in speakers[1:]:
        inferred_vn, inferred_lc = infer_voice_from_name(sp)
        if inferred_vn not in used_voices:
            voice_map[sp] = (inferred_vn, inferred_lc)
            used_voices.add(inferred_vn)
        else:
            # Collision — pick the next unused voice from the full en-US pool
            for vn, lc, _ in _VOICE_POOL_EN:
                if vn not in used_voices:
                    voice_map[sp] = (vn, lc)
                    used_voices.add(vn)
                    break
            else:
                # Exhausted all unique voices (>6 speakers) — reuse en-US default
                voice_map[sp] = (_VOICE_POOL_EN[0][0], _VOICE_POOL_EN[0][1])

    return voice_map


# Magpie NVCF model name — override via --magpie-model flag or MAGPIE_MODEL env var
DEFAULT_MAGPIE_MODEL = os.environ.get("MAGPIE_MODEL", "ai-magpie-tts-multilingual")
NVCF_GRPC = "grpc.nvcf.nvidia.com:443"
TARGET_SR = 44100   # Magpie native rate (skill tts.md Quick path uses 44100 Hz)


def resolve_voice(voice_arg: str) -> tuple:
    """Return (voice_name, language_code) for a role alias or a literal voice name.
    For a literal full voice name (e.g. Magpie-Multilingual.ZH-CN.Siwei), derives
    the language_code from the locale segment (ZH-CN → zh-CN).
    """
    if voice_arg in MAGPIE_VOICES:
        return MAGPIE_VOICES[voice_arg]
    # Treat as a full voice name — derive language_code from the locale segment
    parts = voice_arg.split(".")
    if len(parts) >= 2:
        lang = parts[1].lower().replace("_", "-")  # ZH-CN → zh-cn, keep BCP-47 form
        # Normalise: zh-cn → zh-CN etc.
        lang_map = {"en-us": "en-US", "zh-cn": "zh-CN", "vi-vn": "vi-VN",
                    "hi-in": "hi-IN", "es-us": "es-US", "fr-fr": "fr-FR",
                    "de-de": "de-DE", "it-it": "it-IT", "ja-jp": "ja-JP"}
        return (voice_arg, lang_map.get(lang, lang))
    return (voice_arg, "en-US")


# ── helpers ───────────────────────────────────────────────────────────────────

def load_api_key() -> str:
    key = os.environ.get("NVIDIA_API_KEY", "")
    if not key:
        env = REPO_ROOT / ".env"
        for line in env.read_text().splitlines():
            if line.startswith("NVIDIA_API_KEY="):
                key = line.split("=", 1)[1].strip().split("#")[0].strip()
                break
    if not key:
        print("ERROR: NVIDIA_API_KEY not set. Export it or add to .env", file=sys.stderr)
        sys.exit(1)
    return key


def discover_magpie_fid(api_key: str, model_name: str) -> str:
    import urllib.request
    url = "https://api.nvcf.nvidia.com/v2/nvcf/functions?visibility=public,authorized"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    import json as _json
    with urllib.request.urlopen(req, timeout=10) as r:
        data = _json.loads(r.read())
    for fn in data.get("functions", []):
        if fn.get("status") == "ACTIVE" and fn.get("name", "") == model_name:
            return fn["id"]
    print(f"ERROR: {model_name} not found in NVCF. Check NGC entitlements.", file=sys.stderr)
    sys.exit(1)


def write_wav(path: Path, pcm_bytes: bytes, sample_rate: int = TARGET_SR):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)   # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    duration = len(pcm_bytes) // 2 / sample_rate
    print(f"  ✓ {path}  ({duration:.1f}s, {sample_rate} Hz, mono 16-bit PCM)")
    return path


# ── Magpie TTS ────────────────────────────────────────────────────────────────

def magpie_synthesize(text: str, voice_name: str, language_code: str, api_key: str, fid: str) -> bytes:
    """Call Magpie TTS via NVCF gRPC.
    voice_name:    full dot-notation name e.g. Magpie-Multilingual.EN-US.Sofia
    language_code: BCP-47 code matching the locale in voice_name e.g. en-US
    API: nvidia-riva-client 2.x — synthesize() takes kwargs directly (no SynthesizeSpeechRequest).
    """
    import riva.client
    md   = [["function-id", fid], ["authorization", f"Bearer {api_key}"]]
    auth = riva.client.Auth(uri=NVCF_GRPC, use_ssl=True, metadata_args=md)
    tts  = riva.client.SpeechSynthesisService(auth)
    resp = tts.synthesize(
        text,
        voice_name=voice_name,
        language_code=language_code,
        encoding=riva.client.AudioEncoding.LINEAR_PCM,
        sample_rate_hz=TARGET_SR,
    )
    return resp.audio   # raw PCM bytes


def generate_witness_audio_magpie(
    case_dir: Path, api_key: str, fid: str, lang: str = "witness"
) -> Path:
    stmt_file = case_dir / "witness_statement.txt"
    if not stmt_file.exists():
        print(f"  SKIP: witness_statement.txt not found in {case_dir.name}")
        return None

    text = stmt_file.read_text(encoding="utf-8")
    # Strip SPF header block, keep the actual testimony
    lines = [l for l in text.splitlines() if l.strip() and not l.startswith("=")]
    testimony = []
    in_testimony = False
    for line in lines:
        if line.startswith("WITNESS STATEMENT") or line.startswith("SINGAPORE POLICE"):
            continue
        if line.startswith("Case Reference:") or line.startswith("Date Recorded:") \
           or line.startswith("Witness Name:") or line.startswith("Recording Officer:"):
            continue
        in_testimony = True
        if in_testimony and line.strip():
            testimony.append(line.strip())

    # Truncate to ~800 chars to keep audio under 60s / gRPC 4 MB limit
    script = " ".join(testimony)[:800]
    if not script:
        script = text[:800]

    voice_name, language_code = resolve_voice(lang)
    print(f"  Witness interview ({len(script)} chars, voice={voice_name}, lang={language_code}) ...")
    pcm = magpie_synthesize(script, voice_name, language_code, api_key, fid)
    out = case_dir / "audio" / "witness_interview.wav"
    write_wav(out, pcm)
    return out


def generate_phone_call_magpie(
    case_dir: Path, api_key: str, fid: str, lang: str = "suspect"
) -> Path:
    chat_file = case_dir / "whatsapp_chat.txt"
    if not chat_file.exists():
        print(f"  SKIP: whatsapp_chat.txt not found in {case_dir.name}")
        return None

    text = chat_file.read_text(encoding="utf-8")

    # Parse [HH:MM] Speaker: message lines
    pattern = re.compile(r'^\[(\d{2}:\d{2})\]\s+([^:]+):\s+(.+)$')
    messages = []
    for line in text.splitlines():
        m = pattern.match(line.strip())
        if m:
            messages.append({"time": m.group(1), "speaker": m.group(2).strip(), "text": m.group(3).strip()})

    if not messages:
        print(f"  SKIP: no parseable messages in whatsapp_chat.txt")
        return None

    # Assign a unique voice to each unique speaker in the chat.
    # First speaker uses --voice flag; others are inferred from their display name
    # (Vietnamese/Chinese/Indian/Malay/English name patterns → matching language + gender).
    speakers = list(dict.fromkeys(msg["speaker"] for msg in messages))
    voice_map = assign_chat_voices(speakers, lang)
    print(f"  Speaker assignments:")
    for sp, (vn, lc) in voice_map.items():
        print(f"    {sp:20s} → {vn} [{lc}]")

    # Synthesize each turn and concatenate PCM (cap 12 turns; gRPC 4 MB limit)
    all_pcm = b""
    silence_frames = b"\x00\x00" * int(TARGET_SR * 0.5)  # 0.5s gap between turns

    for msg in messages[:12]:
        vn, lc = voice_map[msg["speaker"]]
        phrase = msg["text"][:150]
        print(f"    [{msg['speaker']}] {phrase[:50]}...")
        pcm = magpie_synthesize(phrase, vn, lc, api_key, fid)
        all_pcm += pcm + silence_frames

    out = case_dir / "audio" / "phone_call_recording.wav"
    write_wav(out, all_pcm)
    return out


# ── Pipeline smoke-test tone ──────────────────────────────────────────────────

def generate_test_tone(case_dir: Path, duration_s: int = 3) -> Path:
    """Generate a 440 Hz sine wave WAV for pipeline testing without any TTS API.
    No NVIDIA_API_KEY needed. Transcription will return 0 words — expected for a tone.
    Use to verify: format normalization → Parakeet gRPC → response parsing → RAG ingest.
    Output: <case_dir>/audio/test_tone.wav (mono, 16 kHz, 16-bit PCM)
    """
    import math
    SR = 16000
    samples = []
    for i in range(SR * duration_s):
        t = i / SR
        val = int(32767 * math.sin(2 * math.pi * 440 * t)) if t < 1.0 else 0
        samples.append(val)
    out = case_dir / "audio" / "test_tone.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(SR)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    print(f"  ✓ {out}  ({duration_s}s, {SR} Hz, mono 16-bit PCM — 440 Hz tone, not speech)")
    print("    Use this to test the Phase 4 ASR pipeline. Transcription will be empty — expected.")
    return out


# ── MERaLiON Hokkien TTS ──────────────────────────────────────────────────────

# Default model — override via --hokkien-model or HOKKIEN_MODEL env var.
DEFAULT_HOKKIEN_MODEL = os.environ.get("HOKKIEN_MODEL", "MERaLiON/MERaLiON-OmniVoice-Hokkien-TTS")


def _hokkien_synthesize(text: str, out_path: Path, model_name: str) -> Path:
    """
    Core Hokkien synthesis using the omnivoice library.

    Bug note: MERaLiON-OmniVoice-Hokkien-TTS is NOT a standard HuggingFace
    transformers model — it uses a custom omnivoice library. Calling
    transformers.pipeline("text-to-speech", ...) on it fails because transformers
    does not know how to load or run this model type. Always use OmniVoice directly.

    Requires: GPU + HF_TOKEN + omnivoice (in PEP 723 deps → uv installs it)
    Input: Chinese hanzi (Southern Min / 闽南语); romanisation not supported.
    """
    try:
        import torch
        from omnivoice.models.omnivoice import OmniVoice
        import numpy as np
    except ImportError as e:
        print(f"  ERROR: {e}. omnivoice not installed — add to deps or run: pip install omnivoice")
        return None

    if not torch.cuda.is_available():
        print("  ERROR: Hokkien TTS requires a CUDA GPU.")
        return None

    hf_token = os.environ.get("HF_TOKEN", "")
    if not hf_token:
        print("  ERROR: HF_TOKEN not set.")
        return None

    print(f"  Loading {model_name} ...")
    model = OmniVoice.from_pretrained(
        model_name,
        device_map="cuda:0",
        dtype=torch.float16,
        token=hf_token,
    )

    print(f"  Synthesizing: {text[:60]}...")
    audios = model.generate(text=text, language="nan")   # "nan" = Min Nan / Hokkien

    audio_array = np.array(audios[0])
    audio_int16 = (audio_array * 32767).astype(np.int16)
    pcm = struct.pack(f"<{len(audio_int16)}h", *audio_int16)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_wav(out_path, pcm, model.sampling_rate)
    return out_path


def generate_hokkien_audio(case_dir: Path, text: str = "", model_name: str = "") -> Path:
    """
    Synthesize Hokkien audio for a case.
    If text is provided, use it directly.
    Otherwise derive a short contextual phrase from the case metadata.json.
    """
    model_name = model_name or DEFAULT_HOKKIEN_MODEL

    if not text:
        # Derive a short contextual Hokkien phrase from case metadata
        meta_file = case_dir / "metadata.json"
        case_type = "案件"
        if meta_file.exists():
            meta = json.loads(meta_file.read_text())
            case_type_map = {
                "drug_trafficking": "毒品交易",
                "homicide": "谋杀案",
                "cybercrime": "网络犯罪",
                "robbery": "抢劫案",
                "financial_fraud": "金融诈骗",
                "assault": "袭击案",
            }
            case_type = case_type_map.get(meta.get("case_type", ""), "案件")
        # "I don't know anything about this case / I haven't done anything like this"
        text = f"这个{case_type}，我真的不知影啥物事。我无做过这款代志。"

    out = case_dir / "audio" / "hokkien_suspect_statement.wav"
    return _hokkien_synthesize(text, out, model_name)


# ── Single-file synthesis ─────────────────────────────────────────────────────

def generate_from_file_magpie(
    text_path: Path, out_path: Path, api_key: str, fid: str,
    lang: str = "default", max_chars: int = 1500,
) -> Path:
    """Synthesize any text file to WAV via Magpie TTS.
    lang: role alias (witness/suspect/mandarin/vietnamese…) or BCP-47 code (en-US, zh-CN…).
    """
    text = text_path.read_text(encoding="utf-8")[:max_chars]
    voice_name, language_code = resolve_voice(lang)
    print(f"  Magpie [{voice_name}|{language_code}]: {text_path.name} ({len(text)} chars) → {out_path.name}")
    pcm = magpie_synthesize(text, voice_name, language_code, api_key, fid)
    write_wav(out_path, pcm)
    return out_path


def generate_from_file_hokkien(
    text_path: Path, out_path: Path, model_name: str = "",
) -> Path:
    """Synthesize any Hokkien text file to WAV via OmniVoice.
    Input must be Chinese hanzi (Southern Min); romanisation not supported.
    """
    text = text_path.read_text(encoding="utf-8").strip()
    print(f"  Hokkien TTS: {text_path.name} → {out_path.name}")
    return _hokkien_synthesize(text, out_path, model_name or DEFAULT_HOKKIEN_MODEL)


# ── main ──────────────────────────────────────────────────────────────────────

def process_case(
    case_dir: Path, tts_mode: str,
    api_key: str = "", fid: str = "",
    hokkien_model: str = "", voice: str = "default",
):
    case_id = case_dir.name
    audio_dir = case_dir / "audio"

    # Skip if audio already exists (idempotent)
    existing = [f for f in audio_dir.iterdir()
                if f.suffix == ".wav" and not f.name.startswith(".")] \
               if audio_dir.exists() else []
    if existing:
        print(f"  {case_id}: audio already exists ({len(existing)} files) — skipping")
        print(f"    Delete {audio_dir}/*.wav to regenerate")
        return []

    print(f"\nCase {case_id}:")

    generated = []
    if tts_mode in ("magpie", "1"):
        # witness_interview: always reads witness_statement.txt → always "witness" voice (Sofia en-US)
        # phone_call:        reads whatsapp_chat.txt → primary/first speaker uses --voice flag
        r = generate_witness_audio_magpie(case_dir, api_key, fid, lang="witness")
        if r: generated.append(r)
        r = generate_phone_call_magpie(case_dir, api_key, fid, lang=voice)
        if r: generated.append(r)
    elif tts_mode in ("hokkien", "2"):
        r = generate_hokkien_audio(case_dir, model_name=hokkien_model)
        if r: generated.append(r)
    else:
        print(f"  ERROR: unknown TTS mode '{tts_mode}'")
    return generated


def main():
    parser = argparse.ArgumentParser(
        description="Generate synthetic forensic audio samples",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Model configuration (all have defaults; override via flag or env var):
  --magpie-model   NVCF model name         env: MAGPIE_MODEL
  --hokkien-model  HuggingFace model path  env: HOKKIEN_MODEL
  --voice          Magpie voice alias or full voice name

Voice aliases: witness, suspect, officer, default
Full voice name example: Magpie-Multilingual.EN-US.Ryan

Examples:
  uv run data/sim/generate_audio_samples.py --all --tts magpie
  uv run data/sim/generate_audio_samples.py --case SC-2024-XXXXX --tts magpie --voice suspect
  uv run data/sim/generate_audio_samples.py --case SC-2024-XXXXX --tts magpie \\
      --magpie-model ai-magpie-tts-multilingual --voice Magpie-Multilingual.EN-US.James
  uv run data/sim/generate_audio_samples.py --case SC-2024-XXXXX --tts hokkien \\
      --hokkien-model MERaLiON/MERaLiON-OmniVoice-Hokkien-TTS
  uv run data/sim/generate_audio_samples.py --file interview.txt --case SC-2024-XXXXX \\
      --tts magpie --voice witness
  uv run data/sim/generate_audio_samples.py --file dialogue.txt --output out.wav --tts hokkien
""",
    )
    parser.add_argument("--case", help="Process one case (e.g. SC-2024-XXXXX)")
    parser.add_argument("--all", action="store_true", help="Process all cases")
    parser.add_argument("--file", metavar="PATH",
                        help="Synthesize a single text file (bypasses witness_statement/whatsapp)")
    parser.add_argument("--output", metavar="PATH",
                        help="Output WAV for --file mode (default: <case>/audio/<stem>.wav)")
    parser.add_argument("--tts", choices=["magpie", "hokkien", "1", "2"],
                        help="TTS engine: magpie (Singlish, cloud) or hokkien (Hokkien, GPU)")
    parser.add_argument("--test-tone", action="store_true",
                        help=(
                            "Generate a 440 Hz sine tone WAV for pipeline testing — no TTS API or "
                            "NVIDIA_API_KEY needed. Use with --case to write test_tone.wav into a "
                            "case audio dir, then run phase4_audio.sh to verify ASR pipeline plumbing. "
                            "Transcription will return 0 words — that is expected for a tone."
                        ))

    # Model configuration
    parser.add_argument("--magpie-model", default=DEFAULT_MAGPIE_MODEL,
                        help=f"Magpie NVCF model name (default: {DEFAULT_MAGPIE_MODEL}, env: MAGPIE_MODEL)")
    parser.add_argument("--hokkien-model", default=DEFAULT_HOKKIEN_MODEL,
                        help=f"Hokkien TTS HF model (default: {DEFAULT_HOKKIEN_MODEL}, env: HOKKIEN_MODEL)")
    parser.add_argument("--voice", default="suspect",
                        help=(
                            "Voice for the PRIMARY SPEAKER in phone_call_recording.wav (WhatsApp chat). "
                            "witness_interview.wav always uses the 'witness' voice (Sofia en-US). "
                            "Aliases: witness, suspect, officer, mandarin, vietnamese-m, vietnamese-f, "
                            "hindi-m, hindi-f. Or pass a full voice name e.g. Magpie-Multilingual.ZH-CN.Siwei"
                        ))
    args = parser.parse_args()

    # ── Test-tone mode (no TTS API needed) ───────────────────────────────────────
    if args.test_tone:
        if not args.case:
            parser.error("--test-tone requires --case")
        out = generate_test_tone(CASES_DIR / args.case)
        print(f"\nNext: bash deploy/phase4_audio.sh   # verify ASR pipeline picks up {out.name}")
        return

    file_mode = args.file is not None
    if not file_mode and not args.case and not args.all:
        parser.print_help()
        sys.exit(1)
    if file_mode and not args.case and not args.output:
        parser.error("--file requires --case or --output to know where to write the WAV")

    # Prompt for TTS mode if not specified
    tts_mode = args.tts
    if not tts_mode:
        print("\nSelect TTS engine:")
        print("  1) Magpie TTS — Singlish/Singapore English (cloud, no GPU needed)")
        print("  2) MERaLiON Hokkien TTS — Hokkien/Southern Min (GPU + HF_TOKEN required)")
        tts_mode = input("Choice [1/2]: ").strip()

    # Load API key and resolve FID for Magpie
    api_key = fid = ""
    if tts_mode in ("magpie", "1"):
        api_key = load_api_key()
        vn, lc = resolve_voice(args.voice)
        print(f"Magpie model : {args.magpie_model}")
        print(f"Voice        : {args.voice} → {vn} [{lc}]")
        print(f"Discovering NVCF function-id for {args.magpie_model} ...")
        fid = discover_magpie_fid(api_key, args.magpie_model)
        print("✓ FID resolved (not printed)")

    if tts_mode in ("hokkien", "2"):
        print(f"Hokkien model: {args.hokkien_model}")

    # ── Single-file mode ──────────────────────────────────────────────────────
    if file_mode:
        text_path = Path(args.file)
        if not text_path.exists():
            print(f"ERROR: {text_path} not found", file=sys.stderr)
            sys.exit(1)

        out_path = Path(args.output) if args.output \
            else CASES_DIR / args.case / "audio" / f"{text_path.stem}.wav"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if tts_mode in ("magpie", "1"):
            generate_from_file_magpie(text_path, out_path, api_key, fid, voice=args.voice)
        elif tts_mode in ("hokkien", "2"):
            generate_from_file_hokkien(text_path, out_path, model_name=args.hokkien_model)
        else:
            print(f"ERROR: unknown TTS mode '{tts_mode}'", file=sys.stderr)
            sys.exit(1)

        print(f"\nDone. WAV written to: {out_path}")
        print("Run Phase 4 to ASR-transcribe and ingest into RAG:")
        print("  bash deploy/phase4_audio.sh")
        return

    # ── Case / --all mode ─────────────────────────────────────────────────────
    case_dirs = [CASES_DIR / args.case] if args.case else sorted(CASES_DIR.glob("SC-*/"))

    all_generated = []
    for case_dir in case_dirs:
        if not case_dir.is_dir():
            print(f"WARNING: {case_dir} not found", file=sys.stderr)
            continue
        generated = process_case(case_dir, tts_mode, api_key, fid,
                                   hokkien_model=args.hokkien_model, voice=args.voice)
        if generated:
            all_generated.extend(generated)

    print(f"\n{'='*60}")
    print(f"Audio generation complete — {len(all_generated)} file(s) written")
    for p in all_generated:
        print(f"  {p}")
    if all_generated:
        print(f"\nNext step — ASR-transcribe and ingest into RAG:")
        print(f"  bash deploy/phase4_audio.sh")


if __name__ == "__main__":
    main()
