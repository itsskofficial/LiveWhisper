#!/usr/bin/env python
"""Verify the logic that has no hardware dependency.

Romanization, the rules that decide what may be learned, and the profile store
are all pure Python, so they can be tested on any machine - including CI, which
has no microphone, no GPU and no Whisper.

    python -m tools.check_core
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper.profile import Habits, ProfileStore  # noqa: E402
from livewhisper.script.conventions import Conventions, validate_rule  # noqa: E402
from livewhisper.script.languages import (CODES, LANGUAGES,  # noqa: E402
                                          detect_script, has_indic)
from livewhisper.script.romanize import Romanizer  # noqa: E402

from livewhisper.console import setup as _console

_console()

failures: list = []

# One sentence per language, with a word we know the lexicon contains.
SAMPLES = {
    "hi": "मुझे कल ऑफिस जाना है",
    "mr": "मी उद्या येईन",
    "bn": "আমি কাল আসব",
    "ta": "நான் நாளைக்கு வருவேன்",
    "te": "నేను రేపు వస్తాను",
    "kn": "ನಾನು ನಾಳೆ ಬರುತ್ತೇನೆ",
    "ml": "ഞാൻ നാളെ വരും",
    "gu": "હું કાલે આવીશ",
    "pa": "ਮੈਂ ਕੱਲ ਆਵਾਂਗਾ",
    "ur": "میں کل آؤں گا",
    "si": "මම හෙට එනවා",
    "sd": "مان سڀاڻي ايندس",
}


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'  ok  ' if ok else ' FAIL '}] {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def main() -> int:
    print("=== romanization, every language ===")
    for code in CODES:
        text = SAMPLES.get(code)
        if not text:
            continue
        out = Romanizer(code).text(text)
        # At least something must have been converted to Latin.
        converted = any(c.isascii() and c.isalpha() for c in out)
        check(f"{LANGUAGES[code].name}", converted, f"{text} -> {out}")

    print("\n=== english is never touched ===")
    for code in ("hi", "ta", "bn"):
        src = "I will be there at five"
        check(f"{code}: english untouched", Romanizer(code).text(src) == src)

    print("\n=== script detection ===")
    for code in ("hi", "ta", "bn", "ur", "si"):
        check(f"detects {code}", detect_script(SAMPLES[code]) is not None,
              str(detect_script(SAMPLES[code])))
    check("plain english has no indic", not has_indic("hello there"))

    print("\n=== learning rules ===")
    c = Conventions()
    c.learn("मुझे", "mujhe", "muze")
    check("one correction does not generalise", not c.rules, str(c.rules))
    c.learn("समझो", "samjho", "samzo")
    check("two corrections promote a rule", c.rules.get("jh") == "z", str(c.rules))
    check("safe consonant rule allowed", validate_rule("jh", "z")[0])
    check("unsafe vowel rule refused", not validate_rule("u", "oo")[0])
    check("applies to new words", c.apply("samjhauta").startswith("samz"))

    print("\n=== habits ===")
    h = Habits()
    check("untrusted before evidence", not h.trusted)
    for _ in range(4):
        h.observe("haan bhai kal milte hain")
    check("trusted after evidence", h.trusted, f"{h.samples} samples")
    check("lowercase learned", h.apply("Yes I Will. Thanks.") == "yes i will. thanks",
          h.apply("Yes I Will. Thanks."))

    print("\n=== profile persistence ===")
    tmp = Path(tempfile.mkdtemp()) / "p.json"
    store = ProfileStore(path=tmp)
    store.get(ProfileStore.GLOBAL).conventions.rules["jh"] = "z"
    store.observe_text("whatsapp.exe", "haan bhai")
    store.save()
    again = ProfileStore(path=tmp)
    check("survives a restart",
          again.get(ProfileStore.GLOBAL).conventions.rules.get("jh") == "z")

    print()
    if failures:
        print(f"{len(failures)} FAILED: {', '.join(failures)}")
        return 1
    print("core logic is sound")
    return 0


if __name__ == "__main__":
    sys.exit(main())
