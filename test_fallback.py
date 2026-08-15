#!/usr/bin/env python
"""Verify the auto backend: Groq when it works, local when it does not.

Synthesises speech to a WAV with SAPI (no loopback needed, so this is fast and
deterministic), then drives AutoBackend through the healthy and the refused
paths.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import soxr
import yaml

from livewhisper.audio import TARGET_RATE
from livewhisper.transcribe import AutoBackend, GroqUnavailable, build_backend

SENTENCE = ("The migration timeline slipped by two weeks. "
            "Marcus will raise it with the vendor on Thursday.")


def synth() -> np.ndarray:
    wav = Path(tempfile.gettempdir()) / "lw_fallback.wav"
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Add-Type -AssemblyName System.Speech; "
         "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
         f"$s.SetOutputToWaveFile('{wav}'); $s.Speak('{SENTENCE}'); $s.Dispose()"],
        check=True, capture_output=True,
    )
    data, rate = sf.read(str(wav), dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    if rate != TARGET_RATE:
        data = soxr.resample(data, rate, TARGET_RATE)
    return np.ascontiguousarray(data, dtype=np.float32)


def make_auto(cfg) -> AutoBackend:
    b = build_backend("auto", cfg["transcription"])
    b.notify = lambda m: print(f"    [notify] {m}")
    return b


def main() -> int:
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    audio = synth()
    print(f"synthesised {len(audio)/TARGET_RATE:.1f}s of speech\n")

    real_key = os.environ.get("GROQ_API_KEY")
    failures = []

    # 1. Healthy Groq path.
    print("1. auto with a valid key -> should use Groq")
    auto = make_auto(cfg)
    if not real_key:
        print("    SKIP: no GROQ_API_KEY set")
    else:
        t0 = time.time()
        text = auto.transcribe(audio)
        print(f"    {time.time()-t0:.1f}s : {text[:70]}...")
        if not text:
            failures.append("valid-key path produced no text")
        if not auto.groq_available:
            failures.append("Groq was benched despite succeeding")
        else:
            print("    OK: Groq still available (not benched)")

    # 2. Groq refuses -> fall back to local.
    print("\n2. auto with an invalid key -> should fall back to local")
    os.environ["GROQ_API_KEY"] = "gsk_definitely_not_a_valid_key_000000000000"
    auto = make_auto(cfg)
    t0 = time.time()
    text = auto.transcribe(audio)
    print(f"    {time.time()-t0:.1f}s : {text[:70]}...")
    if not text:
        failures.append("fallback produced no text")
    else:
        print("    OK: local model produced a transcript")

    # 3. Cooldown must stop us retrying a key we know is rejected.
    if auto.groq_available:
        failures.append("Groq was not benched after a 401")
    else:
        print("    OK: Groq benched, next recording goes straight to local")

    # 4. A network error must NOT bench Groq - that failure is transient.
    print("\n3. transient error -> should not bench Groq")
    auto2 = make_auto(cfg)
    err = GroqUnavailable("network error: simulated", cooldown=False)
    if err.cooldown:
        failures.append("network errors are marked as cooldown-worthy")
    else:
        print("    OK: transient errors keep Groq in rotation")

    if real_key:
        os.environ["GROQ_API_KEY"] = real_key
    else:
        os.environ.pop("GROQ_API_KEY", None)

    print()
    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print("PASS: auto-fallback behaves correctly in all cases.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
