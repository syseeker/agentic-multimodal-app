#!/usr/bin/env python3
"""
Generate a synthetic mono WAV test file for validating the Parakeet ASR pipeline.

The WAV contains a 440 Hz sine wave (1 second) followed by silence.
This will NOT produce meaningful transcription — it verifies the pipeline
plumbing (format normalization → gRPC call → response parsing → file write).

For real end-to-end testing, drop an actual speech WAV into:
  data/cases/<case_id>/audio/
and run process_audio.py.

Output: data/audio/test_audio.wav (mono, 16kHz, 16-bit PCM)
"""
import math
import struct
import wave
from pathlib import Path

TARGET_SR = 16000
DURATION_S = 3


def generate_test_wav(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    samples = []
    for i in range(TARGET_SR * DURATION_S):
        t = i / TARGET_SR
        # 440 Hz sine for 1 second, then silence
        val = int(32767 * math.sin(2 * math.pi * 440 * t)) if t < 1.0 else 0
        samples.append(val)

    with wave.open(str(output_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(TARGET_SR)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))

    print(f"Generated: {output_path}")
    print(f"  Duration: {DURATION_S}s | Sample rate: {TARGET_SR} Hz | Mono | 16-bit PCM")
    print("  NOTE: This is a synthetic tone — transcription output will be empty or noise.")


if __name__ == "__main__":
    out = Path(__file__).parent / "test_audio.wav"
    generate_test_wav(out)
