#!/usr/bin/env python
"""Regression test for the wizard alignment bug found in real profile data.

A user typed the onboarding sentences merging some words ("aa raha" as "araha").
Word counts still matched in places, so the old code zipped by position without
checking, and every pair after the merge was wrong:

    आ   -> "araha"
    रहा -> "hai"
    से  -> "agaya"
    आया -> "jyada"

Those nonsense pairs became permanent per-word overrides. This test pins the
behaviour so it cannot come back.

    python test_alignment.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from livewhisper.onboarding import Onboarding  # noqa: E402

from livewhisper.console import setup as _console

_console()

failures: list = []


def check(name, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {name}" + (f"  {detail}" if detail else ""))
    if not cond:
        failures.append(name)


def main() -> int:
    o = Onboarding("hi")
    s1 = "मुझे कल ऑफिस जाना है, तू आ रहा है क्या?"

    print("=== 1. clean input aligns fully ===")
    pairs = dict(o.align(s1, "muze kal office jana hai tu aa raha hai kya"))
    check("मुझे pairs correctly", pairs.get("मुझे") == "muze", str(pairs.get("मुझे")))
    check("तू pairs correctly", pairs.get("तू") == "tu", str(pairs.get("तू")))

    print("\n=== 2. merged words do not poison the rest ===")
    # "aa raha" typed as one word - the case that broke the real profile
    pairs = dict(o.align(s1, "muze kal office jana hai tu araha hai kya extra"))
    bad = {k: v for k, v in pairs.items()
           if k in ("आ", "रहा") and v in ("araha", "hai")}
    check("no nonsense pair for आ/रहा", not bad, str(bad) if bad else "none")
    check("earlier words still correct", pairs.get("मुझे") == "muze",
          str(pairs.get("मुझे")))

    print("\n=== 3. the exact failure from the real profile ===")
    result = o.process([(s1, "Muze kal office jana hai, tu araha hai kya")])
    overrides = result.conventions.overrides
    poison = {k: v for k, v in overrides.items()
              if v in ("araha", "hai", "agaya", "jyada", "phirse")}
    check("no poisoned overrides", not poison, str(poison) if poison else "none")
    for word, spelling in overrides.items():
        plausible = o._plausible(word, spelling)
        check(f"override {word} -> {spelling} is plausible", plausible)

    print("\n=== 4. skipped and short answers are safe ===")
    check("empty answer ignored", not o.process([(s1, "")]).conventions.overrides)
    check("one-word answer does not explode",
          isinstance(o.process([(s1, "muze")]).conventions.overrides, dict))

    print()
    if failures:
        print(f"{len(failures)} FAILED: {', '.join(failures)}")
        return 1
    print("alignment is safe against merged and mismatched input")
    return 0


if __name__ == "__main__":
    sys.exit(main())
