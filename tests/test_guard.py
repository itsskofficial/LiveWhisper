#!/usr/bin/env python
"""Words nobody said are never pasted - and real dictation always is.

    python tests/test_guard.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper import guard  # noqa: E402

rng = np.random.default_rng(7)
QUIET = rng.normal(0, 0.004, 16000 * 4).astype("float32")            # room noise
SPEECH = (np.sin(np.linspace(0, 2000, 16000 * 4)) * 0.2).astype("float32")

CASES = [
    # (name, text, audio, should drop)
    ("the incident: a phrase looping on noise", "Aapke liye aapke liye aapke liye aapke liye.", QUIET, True),
    ("a loop is dropped even when loud", "the the the the the the", SPEECH, True),
    ("stock phrase on silence", "Thank you for watching!", QUIET, True),
    ("Devanagari stock phrase on silence", "धन्यवाद।", QUIET, True),
    ("stock phrase said out loud is kept", "Thank you so much!", SPEECH, False),
    ("a quiet mic with a real sentence is kept", "Can you send me the numbers by Friday?", QUIET, False),
    ("real Hinglish is kept", "Kal main office jaunga aur meeting attend karunga.", SPEECH, False),
    ("a word said twice is not a loop", "very very good, see you soon", SPEECH, False),
    ("a list with a repeated word is kept", "buy milk, buy eggs, buy bread and butter for the week", SPEECH, False),
    ("empty text is not 'invented'", "", QUIET, False),
]


def main() -> int:
    fails = 0
    for name, text, audio, drop in CASES:
        got = guard.invented(text, audio)
        ok = got == drop
        fails += not ok
        print(f"[{'  ok  ' if ok else ' FAIL '}] {name}")
    print(f"\nnoise level {guard.loudness(QUIET):.4f}, speech {guard.loudness(SPEECH):.4f}"
          f" (quiet below {guard.QUIET_P95})")
    print(f"\n{'all passed' if not fails else f'{fails} FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
