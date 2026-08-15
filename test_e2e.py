#!/usr/bin/env python
"""End-to-end test: speak through the speakers, capture via loopback, transcribe.

Uses Windows SAPI to play real speech out of the default output device, so this
exercises the actual loopback path rather than a synthetic buffer.

    python test_e2e.py [--model tiny]
"""

import argparse
import subprocess
import sys
import threading
import time

import yaml

from livewhisper import output
from livewhisper.audio import Recorder
from livewhisper.transcribe import build_backend

SENTENCE = (
    "The quarterly review is scheduled for Thursday afternoon. "
    "Priya will present the migration timeline, and we still need a decision "
    "on the database vendor before the end of the month."
)


def speak(text: str) -> None:
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Add-Type -AssemblyName System.Speech; "
         "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
         f"$s.Speak('{text}')"],
        check=True, capture_output=True,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None, help="override the configured model")
    ap.add_argument("--vocab", default=None, help="override transcription.vocabulary")
    args = ap.parse_args()

    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    if args.model:
        cfg["transcription"]["local"]["model"] = args.model
    if args.vocab is not None:
        cfg["transcription"]["vocabulary"] = args.vocab

    print(f"Loading {cfg['transcription']['local']['model']} ...")
    backend = build_backend("local", cfg["transcription"])
    backend.load()

    print("Recording. Speaking through the speakers now ...")
    rec = Recorder(capture_system=True, capture_mic=True)
    rec.start()
    time.sleep(0.7)  # let the streams settle before audio starts
    threading.Thread(target=speak, args=(SENTENCE,), daemon=True).start()
    time.sleep(16)
    recording = rec.stop()

    print(f"  captured {recording.seconds:.1f}s  "
          f"system_peak={recording.system_peak:.3f}  mic_peak={recording.mic_peak:.3f}")
    if recording.system_peak < 1e-4:
        print("\nFAIL: loopback captured pure silence.")
        print("Check that system volume is up and not muted - loopback capture is")
        print("taken after the master volume stage, so a muted device yields nothing.")
        return 1

    t0 = time.time()
    transcript = backend.transcribe(recording.audio)
    print(f"  transcribed in {time.time() - t0:.1f}s\n")
    print(f"  spoken: {SENTENCE}")
    print(f"  heard : {transcript}\n")

    if not transcript:
        print("FAIL: no text produced.")
        return 1

    # Prompt-prepend path, exactly as the app composes it.
    profile = next(p for p in cfg["profiles"] if p["name"] == "Summarise")
    composed = output.compose(profile["prompt"], transcript)
    assert composed.startswith("Summarise the key points"), "prompt not prepended"
    assert transcript in composed, "transcript missing from composed output"

    import pyperclip
    pyperclip.copy(composed)
    assert pyperclip.paste() == composed, "clipboard round-trip failed"

    print("--- composed output (first 200 chars) ---")
    print(composed[:200] + " ...")
    print("\nPASS: capture -> transcribe -> prompt-prepend -> clipboard all working.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
