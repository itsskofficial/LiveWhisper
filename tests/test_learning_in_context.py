#!/usr/bin/env python
"""Corrections are learned when the box holds more than the last dictation.

Found recording the demo: three dictations into one chat message, correcting
"tujhe" to "tuze" after the first and "mujhe" to "muze" after the second. The
second correction was never learned - with the first line still in the box,
"Mujhe pata hai" was aligned against "tuze kal milta" - so the "jh" -> "z"
habit that two corrections should form never formed.

    python tests/test_learning_in_context.py
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper import config as cfgio  # noqa: E402
from livewhisper.console import setup as _console  # noqa: E402
from livewhisper.context import ScreenContext  # noqa: E402
from livewhisper.pipeline import Pipeline  # noqa: E402
from livewhisper.profile import ProfileStore  # noqa: E402

_console()
fails = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    fails += not ok
    print(f"[{'  ok  ' if ok else ' FAIL '}] {name}" + (f"  {detail}" if detail else ""))


def session(before: str = "", after_each: str = "\n") -> tuple:
    """Dictate three Hindi lines into one box, fixing the first two."""
    cfg = cfgio.load(Path(__file__).resolve().parent.parent / "config.yaml")
    cfg = {**cfg, "script": {**cfg.get("script", {}), "language": "hi"}}
    pipe = Pipeline(cfg, ProfileStore(Path(tempfile.mkdtemp()) / "p.json"))
    box = before
    notes = []

    def screen():
        return ScreenContext(app="chat.exe", title="Chat", text=box, focused_text=box, method="uia")

    last = ""
    for native, fix in (("तुझे कल मिलता हूँ", ("tujhe", "tuze")),
                        ("मुझे पता है", ("mujhe", "muze")),
                        ("मैं समझ गया, झगड़ा मत कर", None)):
        notes += pipe.learn_from_screen(screen())
        last = pipe.process(native, screen(), force_script="latin", heard_language="hi").text
        box = (box + after_each if box else "") + last
        if fix:
            box = re.sub(fix[0], fix[1], box, flags=re.IGNORECASE)
    return notes, last, box


def main() -> int:
    print("=== each dictation on its own line ===")
    notes, last, _ = session()
    check("the second correction is learned", any("muze" in n for n in notes), str(notes))
    check("two corrections make the jh -> z habit", any("jh -> z" in n for n in notes))
    check("and it reaches words never corrected", "samaz" in last and "zagada" in last, last)

    print("\n=== dictations run on in one line ===")
    notes, last, _ = session(after_each=" ")
    check("the habit still forms", any("jh -> z" in n for n in notes), str(notes))
    check("and is applied", "samaz" in last, last)

    print("\n=== text the user typed before dictating ===")
    notes, last, _ = session(before="haan bhai sun")
    check("the habit still forms", any("jh -> z" in n for n in notes), str(notes))

    print("\n=== a box holding only our paste behaves as before ===")
    p = Pipeline._our_stretch("Tujhe kal milta hun", "tuze kal milta hun")
    check("the whole box is used", p == "tuze kal milta hun", repr(p))
    p = Pipeline._our_stretch("Mujhe pata hai", "tuze kal milta hun\nmuze pata hai")
    check("the latest stretch is picked", p == "muze pata hai", repr(p))

    print(f"\n{'all passed' if not fails else f'{fails} FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
