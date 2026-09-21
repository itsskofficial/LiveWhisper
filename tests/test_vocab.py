#!/usr/bin/env python
"""Words to know correct near misses - and leave ordinary words alone.

    python tests/test_vocab.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper import vocab  # noqa: E402

V = "pull request, Kubernetes, Priyanka, LiveWhisper, CI"
CASES = [
    ("a phrase one letter off", "Mainne full request review kar liya", "Mainne pull request review kar liya"),
    ("a long word one letter off", "deploy on kubernetis today", "deploy on Kubernetes today"),
    ("a name gets its capitals", "priyanka said hi", "Priyanka said hi"),
    ("an extra letter", "Priyankaa said", "Priyanka said"),
    ("two letters off is left alone", "deploy on kubernitis", "deploy on kubernitis"),
    ("words apart are not a phrase", "a full review of the request", "a full review of the request"),
    ("a common word near a phrase word", "I am full of it", "I am full of it"),
    ("short entries only match exactly", "the CJ is green, ci too", "the CJ is green, CI too"),
    ("punctuation around a match survives", "(kubernetis), then", "(Kubernetes), then"),
    ("no vocabulary, no change", "full request", "full request"),
]


def main() -> int:
    fails = 0
    for name, text, want in CASES:
        got = vocab.apply(text, "" if name.startswith("no vocabulary") else V)
        ok = got == want
        fails += not ok
        print(f"[{'  ok  ' if ok else ' FAIL '}] {name}" + ("" if ok else f"  {got!r}"))
    print(f"\n{'all passed' if not fails else f'{fails} FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
