#!/usr/bin/env python
"""Transcribe one captured WAV with both engines and measure their agreement.

Without human ground truth, cross-engine agreement is the honest metric: two
independently-trained systems converging on the same words is strong evidence
both are right, and the places they diverge are exactly where the audio is hard.

    python compare_engines.py accuracy_runs/gitlab_meeting.wav
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import yaml

from livewhisper.transcribe import build_backend
from test_accuracy import normalise, wer

from livewhisper.console import setup as _console

_console()


def main() -> int:
    wav = Path(sys.argv[1] if len(sys.argv) > 1
               else "accuracy_runs/gitlab_meeting.wav")
    if not wav.exists():
        print(f"missing {wav}")
        return 1

    audio, rate = sf.read(str(wav), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    audio = np.ascontiguousarray(audio, dtype=np.float32)
    print(f"{wav.name}: {len(audio)/rate:.1f}s @ {rate} Hz\n")

    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    results = {}
    for name in ("groq", "local"):
        backend = build_backend(name, cfg["transcription"])
        t0 = time.time()
        text = backend.transcribe(audio)
        elapsed = time.time() - t0
        results[name] = text
        Path(f"accuracy_runs/{wav.stem}.{name}.txt").write_text(text, encoding="utf-8")
        print(f"{name:6} {elapsed:6.1f}s  {len(text.split()):4d} words")

    a, b = normalise(results["groq"]), normalise(results["local"])
    rate_, sub, dele, ins = wer(a, b)
    print(f"\ndisagreement (local vs groq): {rate_*100:.1f}%")
    print(f"  substitutions {sub}   deletions {dele}   insertions {ins}")
    print(f"  word-level agreement: {(1-rate_)*100:.1f}%")

    # Show where they diverge - that is where the audio is genuinely hard.
    # SequenceMatcher aligns properly; a naive side-by-side walk reports every
    # word after a single deletion as a mismatch.
    import difflib

    print("\ndivergences:")
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    shown = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal" or shown >= 10:
            continue
        ctx = " ".join(a[max(0, i1 - 5):i1])
        print(f"  ...{ctx}")
        print(f"       groq : {' '.join(a[i1:i2]) or '-'}")
        print(f"       local: {' '.join(b[j1:j2]) or '-'}")
        shown += 1
    if not shown:
        print("  none - the two engines produced identical words")
    return 0


if __name__ == "__main__":
    sys.exit(main())
