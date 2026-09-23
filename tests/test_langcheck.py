#!/usr/bin/env python
"""Second opinion on the language from the words written (script/langcheck.py).

A Marathi speaker's "tu AI system design kuthun shikla" was heard as Hindi on
every voice tried. These pin what the check must and must not do.

    python tests/test_langcheck.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from livewhisper.console import setup as _console  # noqa: E402
from livewhisper.script.langcheck import reconsider  # noqa: E402

_console()
fails = 0
SPEAKS = ["hi", "mr", "en"]


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    fails += not ok
    print(f"[{'  ok  ' if ok else ' FAIL '}] {name}" + (f"  {detail}" if detail else ""))


def main() -> int:
    print("=== Marathi heard as Hindi ===")
    got = reconsider("तू आई सिस्टम डिजाइन कुठून शिकला", "hi", SPEAKS)
    check("the sentence from the report is Marathi", got == "mr", str(got))
    got = reconsider("आज office मध्ये खूप काम आहे, lunch नंतर call करू", "hi", SPEAKS)
    check("code-switched Marathi is Marathi", got == "mr", str(got))
    # A limit, not a goal: मी, केला and आता are in the Hindi lexicon too, so
    # only आहे speaks for Marathi here, and one word is not enough.
    got = reconsider("मी pull request review केला आहे, आता merge कर", "hi", SPEAKS)
    check("too little Marathi to overrule Whisper", got is None, str(got))

    print("\n=== what it must leave alone ===")
    for text in ("मुझे लगता है कि यह feature next week तक deploy हो जाएगा",
                 "कल की meeting cancel हो गई है, client ने reschedule करने को बोला",
                 "भाई laptop hang हो गया है, restart करके देखता हूँ"):
        got = reconsider(text, "hi", SPEAKS)
        check(f"Hindi stays Hindi: {text[:24]}", got is None, str(got))
    got = reconsider("मी pull request review केला आहे", "mr", SPEAKS)
    check("Marathi heard as Marathi is left alone", got is None, str(got))
    got = reconsider("तू आई सिस्टम डिजाइन कुठून शिकला", "hi", ["hi", "en"])
    check("only languages the speaker uses", got is None, str(got))
    got = reconsider("तू सिस्टम कुठून", "hi", SPEAKS)
    check("one Marathi word is not enough", got is None, str(got))
    check("Latin text says nothing", reconsider("tu kuthun shikla", "hi", SPEAKS) is None)
    check("no language, no opinion", reconsider("कुठून शिकला", None, SPEAKS) is None)

    print("\n=== detection: Marathi that Whisper ranks just under Hindi ===")
    from livewhisper.transcribe import LocalBackend
    b = object.__new__(LocalBackend)
    # Probabilities as large-v3 gave them for clips of this set.
    check("Marathi clip, mr at 1/10 of hi -> Marathi",
          b._second_guess_hindi("hi", [("hi", 0.80), ("mr", 0.08), ("en", 0.01)]) == "mr")
    check("Hindi clip, mr at 1/10,000 of hi -> Hindi",
          b._second_guess_hindi("hi", [("hi", 0.90), ("mr", 0.00009), ("en", 0.01)]) == "hi")
    check("Hindi at the measured edge (-2.05) stays Hindi",
          b._second_guess_hindi("hi", [("hi", 0.5), ("mr", 0.5 * 10 ** -2.05)]) == "hi")
    check("only when the speaker uses Marathi",
          b._second_guess_hindi("hi", [("hi", 0.8), ("en", 0.1)]) == "hi")
    check("other languages untouched",
          b._second_guess_hindi("en", [("en", 0.8), ("mr", 0.2), ("hi", 0.01)]) == "en")

    print("\n=== FLEURS references (dev), both directions ===")
    rows = json.loads((ROOT / "build/fleurs-dev/manifest.json").read_text(encoding="utf-8")) \
        if (ROOT / "build/fleurs-dev/manifest.json").exists() else []
    other = {"hi": "mr", "mr": "hi", "ur": "sd", "sd": "ur"}
    flips = wrong = recovered = 0
    for r in rows:
        lang = r["lang"]
        if lang not in other:
            continue
        both = [lang, other[lang]]
        flips += reconsider(r["reference"], lang, both) is not None
        recovered += reconsider(r["reference"], other[lang], both) == lang
        wrong += 1
    if rows:
        check("no correct Hindi, Marathi, Urdu or Sindhi sentence flipped", flips == 0,
              f"{flips} of {wrong}")
        check("most sentences heard as the sibling recovered", recovered >= 0.9 * wrong,
              f"{recovered} of {wrong}")
    else:
        print("(FLEURS not fetched; scripts/fetch_fleurs.py)")

    print(f"\n{'all passed' if not fails else f'{fails} FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
