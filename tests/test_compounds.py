#!/usr/bin/env python
"""Compound splitting: only between whole letters, only into known words.

    python tests/test_compounds.py
"""

from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper.console import setup as _console  # noqa: E402
from livewhisper.script.lexicon import _boundary, get_lexicon  # noqa: E402
from livewhisper.script.romanize import Romanizer  # noqa: E402

_console()
fails = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    fails += not ok
    print(f"[{'  ok  ' if ok else ' FAIL '}] {name}" + (f"  {detail}" if detail else ""))


def cuts_are_safe(word: str, parts: list) -> bool:
    """No piece may start with a vowel sign or joiner, or follow a virama."""
    pos = 0
    for p in parts[:-1]:
        pos += len(p)
        here, prev = word[pos], word[pos - 1]
        if unicodedata.category(here).startswith("M") or here in "‌‍":
            return False
        if "VIRAMA" in unicodedata.name(prev, ""):
            return False
    return "".join(parts) == word


def main() -> int:
    ml = get_lexicon("ml")

    print("=== boundaries ===")
    # अध्यापक: cutting after the virama would orphan the conjunct ध्य
    word = "अध्यापक"
    check("never cut after a virama", not _boundary(word, 3))
    check("never cut before a vowel sign", not _boundary(word, 4))
    check("a clean consonant boundary is allowed", _boundary(word, 6))

    print("\n=== segmentation ===")
    compound = ("അധ്യാപക"
                "സംഘടനകളും")
    parts = ml.segment(compound)
    check("Malayalam compound splits into known words", bool(parts), str(parts))
    if parts:
        check("every piece is a lexicon word",
              all(ml.lookup(p) for p in parts))
        check("pieces rejoin to the word, cut only at letter boundaries",
              cuts_are_safe(compound, parts))
        check("fewest pieces preferred", len(parts) == 2, str(len(parts)))
    check("short words are never split", ml.segment("അധ്യ") is None)
    check("a word with no known pieces is left alone",
          ml.segment("ൺൻർൽൾൿ") is None)
    known = next(w for w in list(ml._entries)[:2000] if len(w) >= 8)
    check("a word already in the lexicon is not consulted for splitting",
          Romanizer("ml").word(known)[1] == "lexicon")

    print("\n=== per-language policy ===")
    saved = (dict(Romanizer.COMPOUND_POLICY), Romanizer.COMPOUNDS)
    try:
        Romanizer.COMPOUNDS = None
        Romanizer.COMPOUND_POLICY = {"default": "off", "ml": "first"}
        check("policy applies to its language", Romanizer("ml").compound_mode == "first")
        check("other languages use the default", Romanizer("hi").compound_mode == "off")
        check("splitting happens where the policy allows it",
              Romanizer("ml").word(compound)[0].isascii())
        Romanizer.COMPOUNDS = "off"
        check("a global override beats the policy (the benchmark relies on this)",
              Romanizer("ml").compound_mode == "off")
    finally:
        Romanizer.COMPOUND_POLICY, Romanizer.COMPOUNDS = saved

    print(f"\n{'all passed' if not fails else f'{fails} FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
