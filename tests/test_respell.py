#!/usr/bin/env python
"""Respelling a Hinglish model's output: fixes long vowels, touches nothing else.

    python tests/test_respell.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper.console import setup as _console  # noqa: E402
from livewhisper.context import ScreenContext  # noqa: E402
from livewhisper.pipeline import Pipeline  # noqa: E402
from livewhisper.profile import ProfileStore  # noqa: E402
from livewhisper.script.respell import attested, respell, respell_word  # noqa: E402

_console()

failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    failures += not ok
    print(f"[{'  ok  ' if ok else ' FAIL '}] {name}" + (f"  {detail}" if detail else ""))


def main() -> int:
    known = attested("hi")
    check("attested spellings loaded", len(known) > 30000, f"{len(known):,}")

    print("\n=== long vowels become the spelling people use ===")
    for model, want in (("saamaan", {"samaan", "saman"}), ("basaaya", {"basaya"}),
                        ("vaala", {"vala", "wala"}), ("dikhaaya", {"dikhaya"}),
                        ("paribhaasha", {"paribhasha"})):
        got = respell_word(model, "hi")
        check(f"{model} -> {got}", got in want, f"wanted one of {sorted(want)}")
    got = respell_word("Saamaan", "hi")
    check("capital kept on a respelled word", got[:1] == "S" and got.lower() in known, got)

    print("\n=== everything else survives ===")
    for word in ("hai", "kya", "mein", "report", "xyzzy", "नमस्ते", ""):
        check(f"untouched: {word!r}", respell_word(word, "hi") == word)
    text = "Maine Television report dekha aur Greenland ke baare mein padha"
    out = respell(text, "hi")
    check("mid-sentence capitals are left alone",
          "Television" in out and "Greenland" in out, out)
    check("empty text", respell("", "hi") == "")
    check("punctuation and spacing preserved",
          respell("saamaan, vaala!  theek hai.", "hi").count(",") == 1
          and "  " in respell("saamaan, vaala!  theek hai.", "hi"))

    print("\n=== the pipeline only respells a Hinglish model's output ===")
    with tempfile.TemporaryDirectory() as td:
        pipe = Pipeline({"script": {"language": "hi"}}, ProfileStore(Path(td) / "p.json"))
        screen = ScreenContext(app="t.exe", title="t", text="", focused_text="",
                               method="uia")
        spoken = "yeh saamaan vaala hai"
        d = pipe.process(spoken, screen, heard_language="hi", latin_output=True)
        check("latin_output=True respells", d.text != spoken and "saamaan" not in d.text,
              d.text)
        d = pipe.process(spoken, screen, heard_language="hi", latin_output=False)
        check("latin_output=False leaves Latin text alone", d.text == spoken, d.text)
        d = pipe.process("the good book", screen, heard_language="en", latin_output=True)
        check("English audio is never respelled", d.text == "the good book", d.text)
        d = pipe.process("yeh saamaan vaala hai", screen, force_script="native",
                         heard_language="hi", latin_output=True)
        check("native-script mode is not respelled", d.text == spoken, d.text)

    print(f"\n{'all passed' if not failures else f'{failures} FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
