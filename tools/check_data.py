#!/usr/bin/env python
"""Verify the shipped lexicons are present and well formed.

Runs in CI, which has no sound card, no GPU and no models - so this checks only
the data, which is the part most likely to be corrupted by a bad build.

    python -m tools.check_data
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper.script.languages import CODES, LANGUAGES, run_pattern  # noqa: E402
from livewhisper.script.lexicon import get_lexicon  # noqa: E402

MIN_WORDS = 15_000
failures: list = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'  ok  ' if ok else ' FAIL '}] {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def main() -> int:
    print(f"checking {len(CODES)} lexicons\n")
    total = 0
    for code in CODES:
        lang = LANGUAGES[code]
        lex = get_lexicon(code)
        n = len(lex)
        total += n
        if n < MIN_WORDS:
            check(f"{lang.name} lexicon", False, f"only {n:,} words")
            continue

        # Every key must actually be in that language's script, and every
        # value must be Latin - a mixed-up build would silently produce
        # nonsense at runtime rather than crashing.
        pattern = run_pattern(code)
        sample = list(lex._entries.items())[:400]
        bad_native = [w for w, _ in sample if not pattern.fullmatch(w)]
        bad_latin = [f for _, forms in sample for f in forms
                     if not all(c.isascii() for c in f)]
        check(f"{lang.name} lexicon", not bad_native and not bad_latin,
              f"{n:,} words" +
              (f", {len(bad_native)} wrong-script keys" if bad_native else "") +
              (f", {len(bad_latin)} non-Latin values" if bad_latin else ""))

    print()
    check("combined vocabulary", total > 300_000, f"{total:,} words")
    reach = sum(LANGUAGES[c].speakers_m for c in CODES)
    check("speaker reach recorded", reach > 1_000, f"~{reach/1000:.2f}B speakers")

    print()
    if failures:
        print(f"{len(failures)} FAILED: {', '.join(failures)}")
        return 1
    print("data looks good")
    return 0


if __name__ == "__main__":
    sys.exit(main())
