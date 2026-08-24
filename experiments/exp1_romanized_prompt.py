#!/usr/bin/env python
"""Experiment 1: can a romanized initial_prompt make Whisper emit Latin-script Hinglish?

Whisper continues the pattern it is shown. If we prime it with romanized Hinglish,
it may transcribe Hindi in Latin script directly, which would remove the need for a
transliteration stage entirely.

    python experiments/exp1_romanized_prompt.py

Metrics
-------
latin_ratio alone is NOT sufficient: an English *translation* also scores 1.0.
So we also count Hindi function words appearing in Latin script, which separates:

    latin ~1.0  +  many hindi hits  ->  ROMANIZED HINGLISH   (the goal)
    latin ~1.0  +  ~zero hindi hits ->  ENGLISH TRANSLATION  (not what we want)
    latin ~0.6  +  n/a              ->  MIXED SCRIPT         (current default)
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper.transcribe import LocalBackend  # noqa: E402

OUT = Path("experiments/results")
WAV = Path("accuracy_runs/hinglish.wav")

# Hindi/Urdu function words as people actually romanize them. Function words are
# the right probe: they are unavoidable in Hindi speech and never appear in an
# English translation.
HINDI_ROMAN = {
    "hai", "hain", "tha", "thi", "the", "hoga", "hogi", "ho", "hu", "hun", "hoon",
    "ka", "ki", "ke", "ko", "se", "mein", "me", "par", "aur", "ya", "toh", "to",
    "nahi", "nahin", "nhi", "na", "kya", "kyu", "kyun", "kaise", "kaha", "kab",
    "ye", "yeh", "wo", "woh", "iska", "uska", "apna", "apne", "mera", "tera",
    "bhi", "hi", "bahut", "bohot", "thoda", "sab", "kuch", "koi", "jo", "jab",
    "abhi", "phir", "fir", "lekin", "magar", "agar", "matlab", "yaar", "bhai",
    "karna", "karta", "karte", "karti", "kar", "raha", "rahi", "rahe", "gaya",
    "diya", "liya", "dekho", "samjho", "chahiye", "sakta", "sakte", "wala", "wale",
}

PROMPTS = {
    "A. baseline (none)": "",

    "B. devanagari-mixed": (
        "यह एक business meeting है. हम Hindi और English दोनों use करते हैं. "
        "Startup, revenue, product, team."
    ),

    "C. romanized short": (
        "haan bhai, kya kar rahe ho? main abhi office se nikla hun."
    ),

    "D. romanized long": (
        "haan bhai kya kar rahe ho, main abhi office se nikla hun. "
        "aaj ka plan kya hai? mujhe lagta hai ki ye product bahut accha hai, "
        "lekin revenue ka model thoda clear nahi hai. dekho, agar hum ye "
        "approach lein toh customer ko value milegi."
    ),

    "E. romanized + label": (
        "Romanized Hinglish transcript. "
        "haan bhai kya kar rahe ho, main abhi office se nikla hun. "
        "mujhe lagta hai ki ye startup ka model bahut accha hai lekin "
        "revenue thoda clear nahi hai."
    ),
}


def latin_ratio(text: str) -> float:
    latin = sum(1 for c in text if "a" <= c.lower() <= "z")
    deva = sum(1 for c in text if "ऀ" <= c <= "ॿ")
    return latin / (latin + deva) if (latin + deva) else 0.0


def hindi_hits(text: str) -> int:
    words = re.findall(r"[a-zA-Z]+", text.lower())
    return sum(1 for w in words if w in HINDI_ROMAN)


def deva_tokens(text: str) -> int:
    return len(re.findall(r"[ऀ-ॿ]+", text))


def classify(lr: float, hits: int, words: int) -> str:
    density = hits / words if words else 0
    if lr > 0.95:
        return "ROMANIZED HINGLISH" if density > 0.06 else "ENGLISH TRANSLATION"
    if lr > 0.8:
        return "mostly latin, some devanagari"
    return "MIXED SCRIPT (devanagari for hindi)"


def main() -> int:
    if not WAV.exists():
        print(f"missing {WAV} - run test_accuracy.py to capture a sample first")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)

    audio, rate = sf.read(str(WAV), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    audio = np.ascontiguousarray(audio, dtype=np.float32)
    print(f"{WAV.name}: {len(audio)/rate:.0f}s\n")

    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    base = dict(cfg["transcription"]["local"])
    base["language"] = None                     # let it auto-detect

    lines = ["# Experiment 1 - romanized initial_prompt\n"]
    rows = []

    # Share one loaded model across all variants so timings are comparable.
    shared = LocalBackend(base)
    shared.load()

    for label, prompt in PROMPTS.items():
        shared.vocabulary = prompt.strip()
        t0 = time.time()
        text = shared.transcribe(audio)
        el = time.time() - t0

        lr = latin_ratio(text)
        hits = hindi_hits(text)
        words = len(text.split())
        verdict = classify(lr, hits, words)
        rows.append((label, lr, hits, words, verdict, el))

        print(f"{label:24} latin={lr:.2f}  hindi_words={hits:3d}  "
              f"deva_tokens={deva_tokens(text):3d}  {verdict}")
        lines.append(f"\n## {label}\n\nprompt: `{prompt or '(none)'}`\n\n"
                     f"latin_ratio {lr:.2f} - hindi_roman_words {hits} - "
                     f"{words} words - {el:.1f}s\n\n**{verdict}**\n\n{text}\n")

    lines.append("\n## summary\n\n"
                 "| variant | latin | hindi words | verdict |\n|---|---|---|---|\n")
    for label, lr, hits, words, verdict, el in rows:
        lines.append(f"| {label} | {lr:.2f} | {hits} | {verdict} |\n")

    path = OUT / "exp1_romanized_prompt.md"
    path.write_text("".join(lines), encoding="utf-8")
    print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
