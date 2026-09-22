#!/usr/bin/env python
"""A model formatting romanized text must not turn every word into a name.

    python tests/test_title_case.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper.pipeline import _no_title_case  # noqa: E402

CASES = [
    ("names made of romanized words are undone",
     "polics adhikshak chandra shekhar yane sahitale", "Polics Adhikshak Chandra Shekhar Yane Sahitale.",
     "Polics adhikshak chandra shekhar yane sahitale."),
    ("sentence starts keep their capital; real names too",
     "kal main office jaunga. phir Priya se milunga", "Kal Main Office Jaunga. Phir Priya Se Milunga.",
     "Kal main office jaunga. Phir Priya se milunga."),
    ("a new paragraph starts a sentence", "pehla\n\ndoosra line", "Pehla\n\nDoosra Line.",
     "Pehla\n\nDoosra line."),
    ("acronyms stay", "API ka kaam kal", "API Ka Kaam Kal.", "API ka kaam kal."),
    ("punctuation the model added is kept", "haan theek hai kal milte hain",
     "Haan, Theek Hai. Kal Milte Hain!", "Haan, theek hai. Kal milte hain!"),
]


def main() -> int:
    fails = 0
    for name, before, after, want in CASES:
        got = _no_title_case(before, after)
        ok = got == want
        fails += not ok
        print(f"[{'  ok  ' if ok else ' FAIL '}] {name}" + ("" if ok else f"  {got!r}"))
    print(f"\n{'all passed' if not fails else f'{fails} FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
