#!/usr/bin/env python
"""Measure real decode throughput on meeting-length audio.

Captures a short SAPI utterance through the loopback path, tiles it to the
requested duration, and times transcription. Tiling repeats content, which does
not affect decode throughput - the number we care about here.
"""

import argparse
import subprocess
import threading
import time

import numpy as np
import yaml

from livewhisper.audio import TARGET_RATE, Recorder
from livewhisper.transcribe import build_backend

from livewhisper.console import setup as _console

_console()

SENTENCE = (
    "The quarterly review is scheduled for Thursday afternoon. "
    "Priya will present the migration timeline. We still need a decision on the "
    "database vendor before the end of the month, and the security audit has "
    "not been scheduled yet. Marcus agreed to follow up with the vendor team."
)


def speak(text):
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Add-Type -AssemblyName System.Speech; "
         "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
         f"$s.Speak('{text}')"],
        check=True, capture_output=True,
    )


ap = argparse.ArgumentParser()
ap.add_argument("--minutes", type=float, default=10.0)
ap.add_argument("--batch", type=int, default=None)
args = ap.parse_args()

cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
if args.batch is not None:
    cfg["transcription"]["local"]["batch_size"] = args.batch

print("Capturing a sample utterance ...")
rec = Recorder(capture_system=True, capture_mic=False)
rec.start()
time.sleep(0.7)
threading.Thread(target=speak, args=(SENTENCE,), daemon=True).start()
time.sleep(22)
sample = rec.stop().audio

target = int(args.minutes * 60 * TARGET_RATE)
audio = np.tile(sample, int(np.ceil(target / len(sample))))[:target]
print(f"  sample {len(sample)/TARGET_RATE:.1f}s -> synthetic {args.minutes:.0f} min")

batch = cfg["transcription"]["local"].get("batch_size", 8)
print(f"Loading model (batch_size={batch}) ...")
backend = build_backend("local", cfg["transcription"])
backend.load()

t0 = time.time()
text = backend.transcribe(audio)
elapsed = time.time() - t0

audio_secs = len(audio) / TARGET_RATE
print(f"\n  audio      {audio_secs/60:.1f} min")
print(f"  decode     {elapsed:.1f}s  ({elapsed/60:.1f} min)")
print(f"  throughput {audio_secs/elapsed:.1f}x realtime")
print(f"  words      {len(text.split())}")
print(f"\n  => a 30 min meeting takes ~{30*60/(audio_secs/elapsed)/60:.1f} min")
