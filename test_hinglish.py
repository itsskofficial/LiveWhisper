#!/usr/bin/env python
"""Find the best setting for Hindi/English code-switched audio.

Whisper detects one language for the clip and then renders everything in that
language's script, so Hinglish audio often comes back with English words
transliterated into Devanagari ("that's your take" -> "देट्स यॉर टेक"). This
compares the fixes.

Writes UTF-8 to a file because Windows consoles mangle Devanagari.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import yaml

from livewhisper.transcribe import build_backend

OUT = Path("accuracy_runs/hinglish_variants.md")

# An initial_prompt written in the target style is the standard trick: Whisper
# continues the pattern it is shown, so a mixed-script prompt encourages
# mixed-script output instead of wholesale transliteration.
HINGLISH_PROMPT = (
    "यह एक business meeting है. हम Hindi और English दोनों use करते हैं. "
    "Startup, revenue, product, team, customer, growth, market."
)

VARIANTS = [
    ("baseline (auto-detect, no prompt)", {"language": None, "vocabulary": ""}),
    ("forced language=hi", {"language": "hi", "vocabulary": ""}),
    ("forced language=en", {"language": "en", "vocabulary": ""}),
    ("auto + Hinglish initial_prompt", {"language": None, "vocabulary": HINGLISH_PROMPT}),
    ("hi + Hinglish initial_prompt", {"language": "hi", "vocabulary": HINGLISH_PROMPT}),
]


def latin_ratio(text: str) -> float:
    """Share of alphabetic characters written in Latin rather than Devanagari.

    The audio is roughly half English, so a ratio near 0 means English words are
    being transliterated into Devanagari - the failure we are hunting.
    """
    latin = sum(1 for c in text if "a" <= c.lower() <= "z")
    deva = sum(1 for c in text if "ऀ" <= c <= "ॿ")
    total = latin + deva
    return latin / total if total else 0.0


def main() -> int:
    wav = Path(sys.argv[1] if len(sys.argv) > 1 else "accuracy_runs/hinglish.wav")
    audio, rate = sf.read(str(wav), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    audio = np.ascontiguousarray(audio, dtype=np.float32)

    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    lines = [f"# Hinglish variants - {wav.name} ({len(audio)/rate:.0f}s)\n"]
    summary = []

    for label, over in VARIANTS:
        t = dict(cfg["transcription"])
        t["local"] = dict(t["local"])
        t["local"]["language"] = over["language"]
        t["vocabulary"] = over["vocabulary"]
        backend = build_backend("local", t)
        t0 = time.time()
        text = backend.transcribe(audio)
        el = time.time() - t0
        ratio = latin_ratio(text)
        summary.append((label, ratio, len(text.split()), el))
        lines.append(f"\n## {label}\n")
        lines.append(f"latin script ratio: {ratio:.2f}  ·  {len(text.split())} words  "
                     f"·  {el:.1f}s\n")
        lines.append(f"\n{text}\n")
        print(f"{label:38} latin={ratio:.2f}  {len(text.split()):4d} words  {el:5.1f}s")

    lines.append("\n## summary\n\n| variant | latin ratio | words | secs |\n|---|---|---|---|\n")
    for label, ratio, words, el in summary:
        lines.append(f"| {label} | {ratio:.2f} | {words} | {el:.1f} |\n")

    OUT.write_text("".join(lines), encoding="utf-8")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
