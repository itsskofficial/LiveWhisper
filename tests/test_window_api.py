#!/usr/bin/env python
"""Everything the app window can ask for, without opening a window.

The page is a thin view; the behaviour lives in window.Api. This drives the Api
the way the page does - settings, languages, dictionary, teaching, history -
against a throwaway LIVEWHISPER_HOME, so the real config is never touched.
tests/ui_tour.py covers the page itself.

    python tests/test_window_api.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = Path(tempfile.mkdtemp())
os.environ["LIVEWHISPER_HOME"] = str(HOME)          # before livewhisper is imported
sys.path.insert(0, str(ROOT))

from livewhisper import paths  # noqa: E402
from livewhisper.console import setup as _console  # noqa: E402

_console()
fails = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    fails += not ok
    print(f"[{'  ok  ' if ok else ' FAIL '}] {name}" + (f"  {detail}" if detail else ""))


def main() -> int:
    try:
        check("a fresh home gets the default config", paths.ensure_config().exists())
        from livewhisper import config as cfgio
        from livewhisper.main import App
        from livewhisper.window import Api

        app = App(paths.CONFIG)
        app._bind_hotkeys = app._unbind_hotkeys = lambda: None
        app._warm_up = lambda: None
        api = Api(app)

        print("=== every call returns plain data ===")
        for name in ("state", "list_components", "dictionary", "languages", "settings",
                     "history"):
            try:
                json.dumps(getattr(api, name)())
                check(f"{name}()", True)
            except Exception as e:
                check(f"{name}()", False, repr(e))
        st = api.state()
        check("first launch is not onboarded", st["onboarded"] is False)
        check("the record hotkey is reported", bool(st["hotkeys"].get("record")))

        print("\n=== settings ===")
        check("a setting saves", api.save_setting("output.auto_paste", False)["ok"])
        check("...to disk", cfgio.load(paths.CONFIG)["output"]["auto_paste"] is False)
        check("...and to the running app", app.cfg["output"]["auto_paste"] is False)
        r = api.save_setting("audio.mic_gain", "not a number")
        check("a wrongly typed value is refused", r["ok"] is False, str(r))
        api.finish_onboarding()
        check("onboarding is remembered", api.state()["onboarded"] is True)

        print("\n=== the Online switch ===")
        import os as _os
        _os.environ["GROQ_API_KEY"] = _os.environ.get("GROQ_API_KEY") or "test-key"
        api.save_setting("processing", "online")
        c = cfgio.load(paths.CONFIG)
        check("online: speech goes to Groq, falling back to this PC",
              c["transcription"]["backend"] == "auto")
        check("online: formatting goes to Groq", c["output"]["format"]["engine"] == "groq")
        check("online: writing goes to Groq", c["actions"]["models"]["provider"] == "groq")
        check("the window reads it back", api.settings()["processing"] == "online")
        api.save_setting("processing", "local")
        c = cfgio.load(paths.CONFIG)
        check("off again: all three back on this PC",
              c["transcription"]["backend"] == "local"
              and c["output"]["format"]["engine"] == "auto"
              and c["actions"]["models"]["provider"] == "auto")
        api.save_setting("output.format.engine", "rules")
        api.save_setting("processing", "online")
        check("formatting switched off stays off when going online",
              cfgio.load(paths.CONFIG)["output"]["format"]["engine"] == "rules")
        api.save_setting("processing", "local")
        api.save_setting("output.format.engine", "auto")

        print("\n=== languages ===")
        api.set_languages(["hi", "ta", "en", "xx"])
        t = cfgio.load(paths.CONFIG)["transcription"]
        check("picked languages restrict detection, with English",
              list(t["languages"]) == ["hi", "ta", "en"], str(t["languages"]))
        langs = {l["code"]: l for l in api.languages()["languages"]}
        check("the page sees what was picked",
              langs["hi"]["selected"] and langs["ta"]["selected"] and not langs["bn"]["selected"])
        check("every language has its endonym", all(l["native"] for l in langs.values()))
        api.set_languages(["mr"])
        check("one language pins romanization to it",
              cfgio.load(paths.CONFIG)["script"]["language"] == "mr")

        print("\n=== dictionary ===")
        api.set_vocabulary(["Kubernetes", "Priyanka", "kubernetes", " "])
        d = api.dictionary()
        check("words are added once each, blanks dropped",
              d["vocabulary"] == ["Kubernetes", "Priyanka"], str(d["vocabulary"]))
        check("...and reach the speech model's vocabulary",
              "Priyanka" in app.cfg["transcription"]["vocabulary"])

        print("\n=== teaching ===")
        t = api.teach_start("hi")
        check("Hindi has its hand-written sentences", len(t["prompts"]) == 5)
        answers = [{"native": p["native"], "typed": typed} for p, typed in zip(t["prompts"], [
            "muze kal office jana hai, tu aa raha hai kya?",
            "wo fir se der se aaya, bahut zyada time laga.",
            "theek hai yaar, koi baat nahi, kal milte hain.",
            "kaun sa chahiye tuze? kisi wajah se nahi aaya wo.",
            ""])]
        r = api.teach_finish(answers)
        check("typing j as z is learned", any("z" in n for n in r["learned"]), str(r["learned"]))
        check("the skipped sentence is counted", r["skipped"] == 1)
        check("the before/after preview is shown", len(r["preview"]) == 3)
        check("what was learned shows in the dictionary",
              bool(api.dictionary()["rules"] or api.dictionary()["spellings"]))
        api.forget_all()
        d = api.dictionary()
        check("forget everything forgets", not d["rules"] and not d["spellings"])

        print("\n=== history ===")
        app.history.add("hello there, this is a test", 2.0, app="notepad.exe")
        app.history.add("second one", 1.0, app="slack.exe", delivered="copied")
        items = api.history()
        check("newest first", [e["text"] for e in items][:2] ==
              ["second one", "hello there, this is a test"])
        check("search finds by text and by app",
              len(api.history("TEST")) == 1 and len(api.history("slack")) == 1)
        api.history_delete(items[0]["id"])
        check("delete removes one", [e["text"] for e in api.history()] ==
              ["hello there, this is a test"])
        s = api.state()["stats"]
        check("stats count words", s["words"] == 6 and s["dictations"] == 1, str(s))
        api.history_clear()
        check("clear removes all", api.history() == [])
    finally:
        shutil.rmtree(HOME, ignore_errors=True)

    print(f"\n{'all passed' if not fails else f'{fails} FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
