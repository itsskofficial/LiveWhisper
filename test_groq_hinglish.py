#!/usr/bin/env python
"""Can Groq be made to handle Hindi/English code-switching?

Groq's hosted whisper-large-v3 transliterates English into Devanagari on
code-switched audio ("that's your take" -> "देट्स यॉर टेक") while the same model
run locally does not. This tries the levers the API exposes.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import yaml

from livewhisper.transcribe import GroqBackend, LocalBackend

from livewhisper.console import setup as _console

_console()

OUT = Path("accuracy_runs/groq_hinglish.md")

HINGLISH_PROMPT = (
    "यह एक business meeting है. हम Hindi और English दोनों use करते हैं. "
    "Startup, revenue, product, team, customer, growth, market."
)


def latin_ratio(text: str) -> float:
    latin = sum(1 for c in text if "a" <= c.lower() <= "z")
    deva = sum(1 for c in text if "ऀ" <= c <= "ॿ")
    return latin / (latin + deva) if (latin + deva) else 0.0


def main() -> int:
    wav = Path("accuracy_runs/hinglish.wav")
    audio, rate = sf.read(str(wav), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    audio = np.ascontiguousarray(audio, dtype=np.float32)

    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    gcfg = dict(cfg["transcription"]["groq"])

    variants = [
        ("groq large-v3, no hint", {"model": "whisper-large-v3"}, ""),
        ("groq large-v3, language=hi", {"model": "whisper-large-v3", "language": "hi"}, ""),
        ("groq large-v3, language=en", {"model": "whisper-large-v3", "language": "en"}, ""),
        ("groq large-v3, Hinglish prompt", {"model": "whisper-large-v3"}, HINGLISH_PROMPT),
        ("groq turbo, no hint", {"model": "whisper-large-v3-turbo"}, ""),
    ]

    lines = ["# Groq on Hinglish audio\n"]
    rows = []
    for label, over, prompt in variants:
        c = dict(gcfg)
        c.update(over)
        b = GroqBackend(c, vocabulary=prompt)
        try:
            t0 = time.time()
            text = b.transcribe(audio)
            el = time.time() - t0
        except Exception as e:
            print(f"{label:34} FAILED: {e}")
            lines.append(f"\n## {label}\n\nFAILED: {e}\n")
            continue
        r = latin_ratio(text)
        rows.append((label, r, len(text.split()), el))
        print(f"{label:34} latin={r:.2f}  {len(text.split()):4d} words  {el:5.1f}s")
        lines.append(f"\n## {label}\n\nlatin ratio {r:.2f} · {len(text.split())} words "
                     f"· {el:.1f}s\n\n{text}\n")

    # Local reference, for contrast.
    lb = LocalBackend(cfg["transcription"]["local"])
    t0 = time.time()
    ltext = lb.transcribe(audio)
    el = time.time() - t0
    lr = latin_ratio(ltext)
    rows.append(("LOCAL large-v3 (reference)", lr, len(ltext.split()), el))
    print(f"{'LOCAL large-v3 (reference)':34} latin={lr:.2f}  "
          f"{len(ltext.split()):4d} words  {el:5.1f}s")
    lines.append(f"\n## LOCAL large-v3 (reference)\n\nlatin ratio {lr:.2f} · "
                 f"{len(ltext.split())} words · {el:.1f}s\n\n{ltext}\n")

    lines.append("\n## summary\n\n| variant | latin ratio | words | secs |\n|---|---|---|---|\n")
    for label, r, w, el in rows:
        lines.append(f"| {label} | {r:.2f} | {w} | {el:.1f} |\n")
    OUT.write_text("".join(lines), encoding="utf-8")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
