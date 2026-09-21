#!/usr/bin/env python
"""The last resort: any word, in any supported script, comes out in Latin letters.

    python tests/test_letters.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper.console import setup as _console  # noqa: E402
from livewhisper.script.letters import spell, spell_text  # noqa: E402
from livewhisper.script.lexicon import get_lexicon  # noqa: E402
from livewhisper.script.languages import LANGUAGES  # noqa: E402

_console()
NATIVE = re.compile(r"[؀-ۿݐ-ݿऀ-෿]")
fails = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    fails += not ok
    print(f"[{'  ok  ' if ok else ' FAIL '}] {name}" + (f"  {detail}" if detail else ""))


def main() -> int:
    print("=== readable spellings ===")
    for native, want in (("करूंगा", "karoonga"), ("কাল", "kal"), ("ಕಚೇರಿಗೆ", "kacherige"),
                         ("ഓഫീസിൽ", "opheesil"), ("ज़रूर", "zaroor"), ("फ़ाइल", "faail"),
                         ("මම", "mam"), ("කරන්ට", "karant")):
        check(f"{native} -> {want}", spell(native) == want, spell(native))

    print("\n=== nothing native survives, in any language ===")
    for code in LANGUAGES:
        lex = get_lexicon(code)
        lex.load()
        words = list(lex._entries)[:3000]
        if not words:
            continue
        leaked = [w for w in words if NATIVE.search(spell(w)) or not spell(w).strip()]
        check(f"{code}: {len(words)} dictionary words spelled in Latin", not leaked,
              f"{len(leaked)} left, e.g. {leaked[:3]}")

    print("\n=== text around it is left alone ===")
    check("English and punctuation pass through",
          spell_text("Mininta කරන්ට api.") == "Mininta karant api.",
          spell_text("Mininta කරන්ට api."))
    check("text with no native script is untouched",
          spell_text("send it at 5, ok?") == "send it at 5, ok?")

    print(f"\n{'all passed' if not fails else f'{fails} FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
