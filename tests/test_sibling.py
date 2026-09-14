#!/usr/bin/env python
"""Sibling-script remapping moves only true twins between Unicode blocks.

    python tests/test_sibling.py
"""

from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper.console import setup as _console  # noqa: E402
from livewhisper.script.sibling import BLOCK, remap, untwinned  # noqa: E402

_console()
fails = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    fails += not ok
    print(f"[{'  ok  ' if ok else ' FAIL '}] {name}" + (f"  {detail}" if detail else ""))


def main() -> int:
    print("=== the case that motivated it ===")
    written = "ఇనగరం"          # ఇనగరం, Telugu script
    want = "ഇനഗരം"             # ഇനഗരം, Malayalam script
    got = remap(written, "te", "ml")
    check("Telugu-script Malayalam becomes Malayalam script", got == want, got)
    check("every mapped character keeps its role",
          all(unicodedata.name(a).split(" ", 1)[1] == unicodedata.name(b).split(" ", 1)[1]
              for a, b in zip(written, got)))

    print("\n=== nothing else moves ===")
    mixed = "office ఇన 2024, ok!"
    out = remap(mixed, "te", "ml")
    check("Latin, digits and punctuation untouched",
          out.startswith("office ") and out.endswith(" 2024, ok!"), out)
    check("text in a third script untouched",
          remap("कल", "te", "ml") == "कल")
    check("same block is a no-op (Hindi and Marathi share Devanagari)",
          remap("कल", "hi", "mr") == "कल")
    check("unaligned scripts are refused",
          remap("අ", "si", "ta") == "අ" and "si" not in BLOCK)
    check("empty text", remap("", "te", "ml") == "")

    print("\n=== letters without a twin are left alone ===")
    # Devanagari KHA has no Tamil counterpart: Tamil has no aspirated consonants.
    kha = "ख"
    check("Devanagari KHA stays put when mapping to Tamil",
          remap(kha, "hi", "ta") == kha, repr(remap(kha, "hi", "ta")))
    check("untwinned() reports it", untwinned(kha, "hi", "ta") == {kha})
    check("a fully twinned word reports nothing", not untwinned(written, "te", "ml"))

    print("\n=== round trip ===")
    word = "నగరం"
    check("te -> ml -> te restores the word", remap(remap(word, "te", "ml"), "ml", "te") == word)
    check("Devanagari -> Bengali maps KA LA",
          remap("कल", "hi", "bn") == "কল")

    print(f"\n{'all passed' if not fails else f'{fails} FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
