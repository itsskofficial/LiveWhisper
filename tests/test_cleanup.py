#!/usr/bin/env python
"""Filler removal: strips hesitation sounds without touching real words.

The dangerous direction is removing too much, so most cases here are things that
must survive: Hindi reduplication, words that merely contain "um", URLs, and
the hesitation words people type deliberately.

    python tests/test_cleanup.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper.cleanup import remove_fillers  # noqa: E402
from livewhisper.console import setup as _console  # noqa: E402

_console()

REMOVE = [
    ("Um, let's ship it.", "Let's ship it."),
    ("So, um, I think we should go.", "So, I think we should go."),
    ("I think uh we should go.", "I think we should go."),
    ("we should go um.", "we should go."),
    ("Uhh... okay then", "Okay then"),
    ("kal main uh office jaunga", "kal main office jaunga"),
    ("Ummm, erm, the build failed", "The build failed"),
    ("It works. Uh, mostly.", "It works. Mostly."),
    ("um", ""),
    ("first line uh\nsecond um line", "first line\nsecond line"),
]

KEEP = [
    "dheere dheere chalo",                  # reduplication is grammar
    "kya kya hua, alag alag log",
    "the the",                              # a real stutter, but see module doc
    "hmm okay",                             # typed on purpose
    "oh no, ah well",
    "haan matlab toh theek hai",
    "bring an umbrella to the summit",      # contains "um"
    "uhuru and humming",
    "see https://um.example.com/uh/path",   # URLs
    "ping @um on slack about #uh",
    "Mumbai is humid",
    "",
    "   ",
    "कल मैं office जाऊंगा",
]


def main() -> int:
    failures = 0
    for text, want in REMOVE:
        got = remove_fillers(text)
        ok = got == want
        failures += not ok
        print(f"[{'  ok  ' if ok else ' FAIL '}] {text!r} -> {got!r}"
              + ("" if ok else f"   wanted {want!r}"))
    for text in KEEP:
        got = remove_fillers(text)
        ok = got == text
        failures += not ok
        print(f"[{'  ok  ' if ok else ' FAIL '}] kept {text!r}"
              + ("" if ok else f"   became {got!r}"))
    print(f"\n{len(REMOVE) + len(KEEP) - failures}/{len(REMOVE) + len(KEEP)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
