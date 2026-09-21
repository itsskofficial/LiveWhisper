#!/usr/bin/env python
"""Corrections to a Hinglish model's text are learned, like corrections to
romanized text always were - and English edits are not.

The Hinglish speech model writes Latin itself, so there is no native word to
key a correction on. Before this, fixing "karunga" to "karoonga" in its output
was silently ignored: on a GPU, that is every Hindi speaker's default route.

    python tests/test_learning_hinglish.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper.pipeline import Pipeline  # noqa: E402
from livewhisper.profile import ProfileStore  # noqa: E402

fails = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    fails += not ok
    print(f"[{'  ok  ' if ok else ' FAIL '}] {name}" + (f"  {detail}" if detail else ""))


def screen(text: str):
    return SimpleNamespace(app="notepad.exe", focused_text=text, text=text, script=None)


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    cfg = {"output": {"format": {"engine": "rules"}}, "script": {"language": "hi"}}
    pipe = Pipeline(cfg, ProfileStore(tmp / "p.json"))
    said = "kal main office jaunga aur meeting attend karunga"

    first = pipe.process(said, screen(""), heard_language="hi", latin_output=True)
    check("the Hinglish model's text is marked as respelled", first.respelled)
    edited = first.text.replace("karunga", "karoonga").replace("meeting", "meetings")
    notes = pipe.learn_from_screen(screen(edited))
    check("the respelling is learned", any("karoonga" in n for n in notes), str(notes))
    check("an English edit is not", not any("meetings" in n for n in notes), str(notes))

    again = pipe.process(said, screen(edited), heard_language="hi", latin_output=True)
    check("the next dictation uses the user's spelling", "karoonga" in again.text, again.text)
    check("and leaves English alone", "meeting " in again.text and "meetings" not in again.text,
          again.text)

    kept = ProfileStore(tmp / "p.json")
    check("it survives a restart",
          kept.get(ProfileStore.GLOBAL).conventions.overrides.get("karunga") == "karoonga")

    other = pipe.process("karunga", screen(""), heard_language="hi", latin_output=True)
    check("capitals follow the sentence", other.text.startswith("Karoonga"), other.text)

    print(f"\n{'all passed' if not fails else f'{fails} FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
