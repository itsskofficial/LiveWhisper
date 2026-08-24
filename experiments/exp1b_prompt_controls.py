#!/usr/bin/env python
"""Experiment 1b: is batching suppressing initial_prompt?

exp1 found a romanized initial_prompt had zero effect, but it ran through
BatchedInferencePipeline. Batched decoding splits on VAD and does not condition
across segments, so the prompt may simply never reach most of the audio.

This controls for that by driving WhisperModel.transcribe directly, and also
tries `prefix`, which forces the literal opening tokens of the transcript and is
a much stronger intervention than a prompt.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from exp1_romanized_prompt import (  # noqa: E402
    classify, deva_tokens, hindi_hits, latin_ratio,
)

OUT = Path("experiments/results")
WAV = Path("accuracy_runs/hinglish.wav")

ROMAN = (
    "haan bhai kya kar rahe ho, main abhi office se nikla hun. "
    "mujhe lagta hai ki ye startup ka model bahut accha hai lekin "
    "revenue thoda clear nahi hai."
)
PREFIX = "haan toh main ye keh raha tha ki"


def main() -> int:
    audio, rate = sf.read(str(WAV), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    audio = np.ascontiguousarray(audio, dtype=np.float32)

    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    loc = cfg["transcription"]["local"]

    from faster_whisper import WhisperModel

    print(f"loading {loc['model']} (sequential, no batching)...")
    model = WhisperModel(loc["model"], device=loc.get("device", "cuda"),
                         compute_type=loc.get("compute_type", "int8_float16"))

    variants = [
        ("1. sequential, no prompt",      dict()),
        ("2. sequential + roman prompt",  dict(initial_prompt=ROMAN)),
        ("3. sequential + prefix",        dict(prefix=PREFIX)),
        ("4. seq + prompt + prefix",      dict(initial_prompt=ROMAN, prefix=PREFIX)),
        ("5. seq + roman prompt, cond=on",
         dict(initial_prompt=ROMAN, condition_on_previous_text=True)),
    ]

    lines = ["# Experiment 1b - prompt controls (no batching)\n"]
    rows = []

    for label, kw in variants:
        opts = dict(
            language=None,
            beam_size=int(loc.get("beam_size", 5)),
            vad_filter=True,
            condition_on_previous_text=False,
        )
        opts.update(kw)
        t0 = time.time()
        segments, info = model.transcribe(audio, **opts)
        text = " ".join(s.text.strip() for s in segments).strip()
        el = time.time() - t0

        lr = latin_ratio(text)
        hits = hindi_hits(text)
        words = len(text.split())
        verdict = classify(lr, hits, words)
        rows.append((label, lr, hits, verdict))

        print(f"{label:32} lang={info.language} latin={lr:.2f} "
              f"hindi={hits:3d} deva={deva_tokens(text):3d} {verdict}")
        lines.append(f"\n## {label}\n\ndetected language: {info.language} "
                     f"({info.language_probability:.2f}) - latin {lr:.2f} - "
                     f"hindi words {hits} - {el:.1f}s\n\n**{verdict}**\n\n{text}\n")

    lines.append("\n## summary\n\n| variant | latin | hindi words | verdict |\n|---|---|---|---|\n")
    for label, lr, hits, verdict in rows:
        lines.append(f"| {label} | {lr:.2f} | {hits} | {verdict} |\n")

    path = OUT / "exp1b_prompt_controls.md"
    path.write_text("".join(lines), encoding="utf-8")
    print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
