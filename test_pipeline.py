#!/usr/bin/env python
"""End-to-end test of the personalisation pipeline.

Covers the path from raw transcript to delivered text, and the learning loop
that runs in reverse. No audio and no network - it exercises the parts that are
deterministic so a regression shows up immediately.

    python test_pipeline.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from livewhisper import config as cfgio
from livewhisper.context import ScreenContext
from livewhisper.notes import NoteBook
from livewhisper.pipeline import Pipeline
from livewhisper.profile import Habits, ProfileStore

from livewhisper.console import setup as _console

_console()

PASS, FAIL = "  ok  ", " FAIL "
failures: list[str] = []


def check(name: str, got, want) -> None:
    ok = got == want
    print(f"[{PASS if ok else FAIL}] {name}")
    if not ok:
        print(f"          got:  {got!r}")
        print(f"          want: {want!r}")
        failures.append(name)


def check_true(name: str, cond, detail: str = "") -> None:
    print(f"[{PASS if cond else FAIL}] {name}" + (f"  {detail}" if detail else ""))
    if not cond:
        failures.append(name)


def main() -> int:
    cfg = cfgio.load("config.yaml")
    tmp = Path(tempfile.mkdtemp())
    store = ProfileStore(path=tmp / "profiles.json")
    # The sections below compare romanized words, so formatting - which
    # capitalises and punctuates - is off for them. Section 9 turns it on.
    plain = {**cfg, "output": {**(cfg.get("output") or {}),
                               "format": {"enabled": False}}}
    pipe = Pipeline(plain, store)

    print("\n=== 1. romanization ===")
    screen = ScreenContext(app="whatsapp.exe", title="Chat", text="",
                           focused_text="", method="uia")
    d = pipe.process("कल मैं office जाऊंगा", screen)
    check_true("devanagari converted to latin", "कल" not in d.text, d.text)
    check_true("english preserved", "office" in d.text, d.text)
    print(f"          -> {d.text}")

    print("\n=== 2. english passes through untouched ===")
    d = pipe.process("I will be there at five", screen)
    check("no change to pure english", d.text, "I will be there at five")
    check("not marked as romanized", d.romanized, False)

    print("\n=== 3. script chosen from what is on screen ===")
    deva_field = ScreenContext(app="notepad.exe", title="", text="",
                               focused_text="मैं अभी वहाँ पहुँच रहा हूँ", method="uia")
    check("native-script field keeps native script",
          pipe.choose_script("notepad.exe", deva_field), "native")
    latin_field = ScreenContext(app="whatsapp.exe", title="", text="",
                                focused_text="yes I will be there soon", method="uia")
    check("latin field stays latin",
          pipe.choose_script("whatsapp.exe", latin_field), "latin")
    d = pipe.process("मैं आ रहा हूँ", deva_field)
    check_true("devanagari kept when field is devanagari",
               "मैं" in d.text, d.text)

    print("\n=== 4. spelling conventions generalise ===")
    conv = store.get(ProfileStore.GLOBAL).conventions
    conv.learn("मुझे", "mujhe", "muze")
    check_true("one correction does not make a rule", "jh" not in conv.rules,
               f"rules={conv.rules}")
    conv.learn("समझो", "samjho", "samzo")
    check("second word promotes it", conv.rules.get("jh"), "z")
    d = pipe.process("मुझे लगता है समझो", screen)
    check_true("rule applies to new text", "muze" in d.text and "samzo" in d.text,
               d.text)
    print(f"          -> {d.text}")

    print("\n=== 5. per-app orthographic habits ===")
    p = store.get("whatsapp.exe")
    p.habits = Habits(capitalize=0.02, terminal_period=0.03, samples=10)
    out = p.habits.apply("Yes I will be there. See you then.")
    check("lowercased for whatsapp", out, "yes i will be there. see you then")
    formal = store.get("outlook.exe")
    formal.habits = Habits(capitalize=0.99, terminal_period=0.95, samples=10)
    check("outlook untouched",
          formal.habits.apply("Yes I will be there."), "Yes I will be there.")

    print("\n=== 6. habits are not applied before there is evidence ===")
    fresh = store.get("newapp.exe")
    fresh.habits.observe("hello there")
    check_true("one sample is not enough", not fresh.habits.trusted,
               f"samples={fresh.habits.samples}")

    print("\n=== 7. notes ===")
    nb = NoteBook(directory=tmp / "notes")
    nb.start("Test note")
    nb.append("first thing said")
    note = nb.append("second thing said")
    check("both entries recorded", len(note.entries), 2)
    check_true("written to disk", note.path.exists(), note.path.name)
    body = note.path.read_text(encoding="utf-8")
    check_true("markdown contains the text", "second thing said" in body)
    nb.stop()

    print("\n=== 8. profile survives a restart ===")
    store.save()
    again = ProfileStore(path=tmp / "profiles.json")
    check("rules persisted",
          again.get(ProfileStore.GLOBAL).conventions.rules.get("jh"), "z")
    check_true("habits persisted", again.get("whatsapp.exe").habits.capitalize < 0.1)

    print("\n=== 9. the text is finished before it is delivered ===")
    # Rules only, so this does not depend on Ollama running on the test
    # machine; the model path has its own suite in tests/test_llm_format.py.
    ruled = {**cfg, "output": {**(cfg.get("output") or {}),
                               "format": {**((cfg.get("output") or {}).get("format") or {}),
                                          "engine": "rules"}}}
    finished = Pipeline(ruled, ProfileStore(path=tmp / "formatted.json"))
    d = finished.process("kal milte hain comma theek hai", screen)   # whatsapp
    check_true("a spoken comma becomes punctuation", "," in d.text, d.text)
    check_true("a chat app gets no full stop added", not d.text.endswith("."), d.text)
    check("the style came from the app", d.style, "chat")
    mail = ScreenContext(app="outlook.exe", title="Mail", text="",
                         focused_text="", method="uia")
    d = finished.process("i will send it tonight", mail)
    check("a mail window is prose", d.style, "prose")
    check_true("prose finishes the sentence", d.text.endswith("."), d.text)
    check_true("and capitalises it", d.text.startswith("I will"), d.text)
    d = finished.process("मुझे लगता है", mail)
    check_true("romanized Hindi is formatted too, not skipped",
               d.text.endswith(".") and "मुझे" not in d.text, d.text)

    # Formatting capitalises the first word, and the field the user corrects
    # therefore contains a capital too. Learning has to see past that: it once
    # recorded M -> m as the user's spelling habit and missed the real one.
    fresh_store = ProfileStore(path=tmp / "learn_formatted.json")
    learner = Pipeline(ruled, fresh_store)
    learner.process("मुझे", ctx_app := ScreenContext(
        app="t.exe", title="t", text="", focused_text="", method="uia"))
    learner.learn_from_screen(ScreenContext(app="t.exe", title="t", text="",
                                            focused_text="muze", method="uia"))
    learner.process("समझो", ctx_app)
    learner.learn_from_screen(ScreenContext(app="t.exe", title="t", text="",
                                            focused_text="samzo", method="uia"))
    learned = fresh_store.get(ProfileStore.GLOBAL).conventions
    check("a habit is learned through formatted text", learned.rules.get("jh"), "z")
    check_true("and not the capital the formatter added",
               "M" not in learned.rules and "m" not in learned.rules,
               f"rules={learned.rules}")

    print()
    if failures:
        print(f"{len(failures)} FAILED: {', '.join(failures)}")
        return 1
    print("all pipeline tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
