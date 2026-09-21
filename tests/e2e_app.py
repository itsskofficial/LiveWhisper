#!/usr/bin/env python
"""The whole app, end to end, the way a person uses it.

Every other test starts from a transcript or a function call. This one drives
the real App object - recording, language priming, transcription, formatting,
pasting - into a real Notepad window, with real speech:

  1. Synthetic speech (edge-tts neural voices) is played out of the speakers.
  2. The app records it through WASAPI loopback, exactly as it records a
     meeting, so no microphone or virtual cable is needed.
  3. The dictation is stopped as the hotkey would stop it, and the test waits
     for the app to go idle.
  4. What landed in Notepad is read back through UI Automation and compared
     with what a person would have typed.

It then corrects a word in Notepad and dictates again, to check that the app
learned the correction - the self-learning loop, measured as a user would see
it.

    python tests/e2e_app.py                 # local engine
    python tests/e2e_app.py --backend groq  # needs GROQ_API_KEY

Needs speakers (any output device), Windows, and a network connection the first
time, to synthesise the clips. Takes over the foreground window while running.
"""

from __future__ import annotations

import argparse
import os
import asyncio
import json
import re
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import numpy as np  # noqa: E402

from livewhisper.console import setup as _console  # noqa: E402

_console()
CLIPS = ROOT / "build" / "e2e"
OUT = ROOT / "tests" / "results"

# (name, voice, what is said, checks). Checks are what a user would notice:
# words that must appear, words that must not, and the shape of the result.
CASES = [
    ("en_prose", "en-US-AriaNeural",
     "Hey Priya, just wanted to check if the report is ready. "
     "I need it before the call tomorrow.",
     {"has": ["Priya", "report is ready", "before the call tomorrow"],
      "ends": ".", "not": []}),
    ("en_question", "en-US-GuyNeural",
     "Can you send me the latest numbers when you get a chance?",
     {"has": ["latest numbers", "chance"], "ends": "?", "not": []}),
    ("en_commands", "en-US-AriaNeural",
     "Hi Rahul comma thanks for the update full stop new paragraph "
     "let's talk on Monday",
     {"has": ["Rahul,", "update.", "\n\n", "Monday"],
      "not": ["comma", "kama", "full stop", "paragraph"]}),
    ("en_list", "en-US-GuyNeural",
     "Tasks for tomorrow. Bullet point fix the login bug. "
     "Bullet point update the docs. Bullet point ship the release.",
     {"has": ["- Fix the login bug", "- Update the docs", "- Ship the release"],
      "not": ["bullet"]}),
    ("en_correction", "en-US-AriaNeural",
     "Let's meet on Monday, I mean Tuesday, at four.",
     {"has": ["Tuesday"], "not": ["Monday", "I mean"]}),
    ("en_paragraph", "en-US-GuyNeural",
     "Thanks everyone for joining today. We covered the roadmap for the next "
     "quarter. The main goals are faster onboarding, better offline support, "
     "and a cleaner settings page. If you have questions, please post them in "
     "the channel.",
     {"has": ["roadmap", "next quarter", "onboarding", "offline support",
              "settings page", "channel"], "ends": ".", "not": []}),
    ("hi_mixed", "hi-IN-MadhurNeural",
     "कल मैं ऑफिस जाऊंगा और मीटिंग अटेंड करूंगा",
     {"has": ["kal", "office", "meeting", "attend"], "not_script": True}),
    ("hi_codeswitch", "hi-IN-SwaraNeural",
     "मैंने pull request review कर लिया है, अब merge कर दो",
     {"has": ["pull request", "review", "merge"], "not_script": True}),
    ("si_tts", "si-LK-SameeraNeural",
     "මම හෙට කාර්යාලයට යනවා",
     {"has": [], "not_script": True}),
]

# Real human speech for every language FLEURS has: two recordings each, scored
# against every accepted romanization. Punjabi and Sindhi have no synthetic
# voice at all, and read speech from real people is the better test anyway.
FLEURS = ROOT / "build" / "fleurs"
SWEEP = ["hi", "bn", "ur", "pa", "mr", "te", "ta", "gu", "kn", "ml", "sd", "en"]


# ------------------------------------------------------------------ audio

def synthesise() -> None:
    import edge_tts

    CLIPS.mkdir(parents=True, exist_ok=True)

    async def one(name, voice, text):
        path = CLIPS / f"{name}.mp3"
        if not path.exists():
            await edge_tts.Communicate(text, voice).save(str(path))

    async def all_():
        for name, voice, text, _ in CASES:
            await one(name, voice, text)
    asyncio.run(all_())


def load(name: str) -> np.ndarray:
    from test_audio_e2e import load_audio
    pcm, _ = load_audio(CLIPS / f"{name}.mp3")
    return pcm


def play(pcm: np.ndarray) -> threading.Thread:
    from test_loopback import play as _play
    return _play(pcm)


# ---------------------------------------------------------------- notepad

class Notepad:
    """A real Notepad window, driven and read through UI Automation."""

    def __init__(self):
        import uiautomation as auto
        self.auto = auto
        self.proc = subprocess.Popen(["notepad.exe"])
        deadline = time.time() + 15
        self.win = None
        while time.time() < deadline and self.win is None:
            for w in auto.GetRootControl().GetChildren():
                if w.ClassName == "Notepad":
                    self.win = w
                    break
            time.sleep(0.3)
        if self.win is None:
            raise RuntimeError("Notepad did not open")

    def editor(self):
        for kind in ("DocumentControl", "EditControl"):
            c = getattr(self.win, kind)(searchDepth=8)
            if c.Exists(1):
                return c
        raise RuntimeError("no editor in Notepad")

    def focus(self) -> None:
        self.win.SetActive()
        self.win.SetFocus()
        ed = self.editor()
        ed.SetFocus()
        ed.Click(simulateMove=False)
        time.sleep(0.2)

    def text(self) -> str:
        ed = self.editor()
        try:
            return ed.GetValuePattern().Value.replace("\r\n", "\n").replace("\r", "\n")
        except Exception:
            return ed.GetTextPattern().DocumentRange.GetText(-1).replace("\r\n", "\n")

    def clear(self) -> None:
        import keyboard
        self.focus()
        keyboard.send("ctrl+a")
        time.sleep(0.05)
        keyboard.send("delete")
        time.sleep(0.2)

    def type_over(self, text: str) -> None:
        """Replace everything with `text`, as a user editing the field would.

        Pasted, not typed: keyboard.write raced Notepad and produced
        "iiin iiiice ,,,,,," - a harness failure, not the app's.
        """
        import keyboard
        import pyperclip
        self.clear()
        pyperclip.copy(text)
        keyboard.send("ctrl+v")
        time.sleep(0.3)

    def close(self) -> None:
        try:
            self.proc.kill()
        except Exception:
            pass


# -------------------------------------------------------------------- app

def installed_routes(models_dir: Path) -> dict:
    """Every catalogued GPU specialist already converted under models_dir."""
    from livewhisper.specialists import CATALOGUE
    routes = {}
    for spec in CATALOGUE:
        path = models_dir / spec.name
        if spec.device == "gpu" and (path / "model.bin").exists():
            if spec.role == "native":
                if spec.lang in routes and routes[spec.lang].get("latin_output"):
                    routes[spec.lang]["native"] = str(path)
                continue
            route = {"path": str(path)}
            if spec.latin_output:
                route["latin_output"] = True
            if spec.language:
                route["language"] = spec.language
            routes[spec.lang] = route
    return routes


def make_app(backend: str, routes: dict | None = None):
    """The real App, with its own profile store and speakers-only capture."""
    from livewhisper import config as cfgio
    from livewhisper.main import App
    from livewhisper.pipeline import Pipeline
    from livewhisper.profile import ProfileStore

    tmp = Path(tempfile.mkdtemp())
    cfg = cfgio.load(ROOT / "config.yaml")
    cfg["audio"]["capture_mic"] = False          # the test speaks through speakers
    cfg["audio"]["capture_system"] = True
    cfg["audio"]["dictation_includes_system"] = True   # dictation is mic-only by default
    cfg["transcription"]["backend"] = backend
    cfg["transcription"]["languages"] = ["en", "hi"]
    cfg.setdefault("script", {})["language"] = "hi"
    cfg["output"]["restore_clipboard"] = False
    if routes:
        cfg["transcription"]["local"]["models"] = routes
        cfg["transcription"]["local"]["max_extra_models"] = 2
    # The pill is on, as it is for users: the run shows it recording and working.
    cfg["ui"]["overlay"] = not os.environ.get("LW_E2E_NO_PILL")
    path = tmp / "config.yaml"
    cfgio.save(path, cfg)
    app = App(path)
    app.styles = ProfileStore(tmp / "profiles.json")
    from livewhisper.history import History
    app.history = History(tmp / "history.jsonl")
    app.pipeline = Pipeline(app.cfg, app.styles)
    notify = app.notify
    app.notify = lambda msg, title="LiveWhisper": (print(f"      [note] {msg}"),
                                                   notify(msg, title))
    return app


def speak_as(app, lang: str) -> None:
    """Configure the running app for a user who speaks `lang` and English."""
    from livewhisper.pipeline import Pipeline
    langs = [lang] if lang == "en" else [lang, "en"]
    app.cfg["transcription"]["languages"] = langs
    app.cfg.setdefault("script", {})["language"] = lang if lang != "en" else "hi"
    backend = app.backend()
    for b in (backend, getattr(backend, "local", None), getattr(backend, "groq", None)):
        if b is not None and hasattr(b, "languages"):
            b.languages = list(langs)
    app.pipeline = Pipeline(app.cfg, app.styles)


def delivered_wer(lang: str, reference: str, got: str) -> float:
    from bench_asr import accepted_spellings, edit, words
    ref = words(reference)
    if lang == "en":
        return edit(ref, words(got)) / max(1, len(ref))
    ok = accepted_spellings(lang, ref)
    return edit(ok, words(got), same=lambda a, w: w in a) / max(1, len(ok))


def dictate(app, pcm: np.ndarray) -> dict:
    """Start, speak, stop, wait: returns timings."""
    from livewhisper.main import State

    app.toggle_record()                          # hotkey down
    if app.state is not State.RECORDING:
        raise RuntimeError("recording did not start")
    time.sleep(0.4)
    t = play(pcm)
    t.join()
    time.sleep(0.7)                              # a person lets go a beat later
    stopped = time.perf_counter()
    app.toggle_record()                          # hotkey again
    while app.state is not State.IDLE:
        time.sleep(0.02)
        if time.perf_counter() - stopped > 60:
            raise RuntimeError("transcription did not finish")
    return {"wait_ms": (time.perf_counter() - stopped) * 1000,
            "spoken_s": len(pcm) / 16000}


def judge(text: str, checks: dict) -> list:
    problems = []
    low = text.lower()
    for want in checks.get("has", []):
        if (want.lower() if want.strip() else want) not in (low if want.strip() else text):
            problems.append(f"missing {want!r}")
    for bad in checks.get("not", []):
        if bad.lower() in low:
            problems.append(f"still contains {bad!r}")
    if checks.get("ends") and not text.rstrip().endswith(checks["ends"]):
        problems.append(f"does not end with {checks['ends']!r}")
    if checks.get("not_script") and re.search(r"[ऀ-෿]", text):
        problems.append("native script left in")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="local", choices=("local", "groq", "auto"))
    ap.add_argument("--only", default="",
                    help="run cases whose name starts with this; 'sweep' or 'learn'")
    ap.add_argument("--per-lang", type=int, default=2)
    ap.add_argument("--routes", default="",
                    help="a folder of converted specialists (e.g. D:/models/ct2) to "
                         "route languages to, as `specialists install` would")
    args = ap.parse_args()

    import logging
    CLIPS.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=str(CLIPS / "app.log"), filemode="w", level=logging.INFO,
                        format="%(asctime)s.%(msecs)03d %(name)s | %(message)s",
                        datefmt="%H:%M:%S", encoding="utf-8")
    print("synthesising clips...")
    synthesise()
    routes = installed_routes(Path(args.routes)) if args.routes else None
    if routes:
        print(f"specialists: {', '.join(f'{k}->{Path(v['path']).name}' for k, v in routes.items())}")
    app = make_app(args.backend, routes)
    print("loading and warming the models (what the app does at launch)...")
    t0 = time.perf_counter()
    app._warm_up()
    print(f"  ready in {time.perf_counter() - t0:.1f}s\n")

    pad = Notepad()
    rows, fails = [], 0
    try:
        for name, _voice, said, checks in CASES:
            if args.only and not name.startswith(args.only):
                continue
            lang = name.split("_")[0]
            speak_as(app, "hi" if lang == "en" else lang)
            pad.clear()
            pad.focus()
            timing = dictate(app, load(name))
            time.sleep(0.4)
            got = pad.text()
            d = app.pipeline._last
            problems = judge(got, checks)
            fails += bool(problems)
            rows.append({"case": name, "said": said, "got": got, "problems": problems,
                         "formatted_by": getattr(d, "formatted_by", None),
                         "style": getattr(d, "style", None), **timing})
            mark = "  ok  " if not problems else " FAIL "
            print(f"[{mark}] {name:<14} {timing['wait_ms']:>6.0f} ms after stop  "
                  f"({getattr(d, 'formatted_by', '?')})")
            print(f"         {got!r}")
            for p in problems:
                print(f"         -> {p}")

        if not args.only or args.only == "sweep":
            print("\n=== every language, real speech ===")
            from bench_asr import load_audio as load_fleurs
            manifest = json.loads((FLEURS / "manifest.json").read_text(encoding="utf-8"))
            for lang in SWEEP:
                clips = [c for c in manifest if c["lang"] == lang][:args.per_lang]
                if not clips:
                    print(f"[ skip ] {lang}: no recordings")
                    continue
                speak_as(app, lang)
                for c in clips:
                    pad.clear()
                    pad.focus()
                    timing = dictate(app, load_fleurs(FLEURS / c["name"]))
                    time.sleep(0.4)
                    got = pad.text()
                    wer = delivered_wer(lang, c["reference"], got)
                    leaked = bool(re.search(r"[؀-ۿऀ-෿]", got))
                    heard = getattr(app.backend(), "last_language", None)
                    rows.append({"case": f"sweep_{lang}", "lang": lang, "heard": heard,
                                 "reference": c["reference"], "got": got,
                                 "delivered_wer": wer, "native_script_left": leaked,
                                 **timing})
                    flag = " LEAK" if leaked else ""
                    print(f"  {lang}  heard {heard!s:<3} delivered WER {wer:>6.1%}  "
                          f"{timing['wait_ms']:>6.0f} ms{flag}  {got[:70]!r}")
            speak_as(app, "hi")

        # The learning loop: correct a word the way a user would, dictate again,
        # and see whether the next dictation spells it their way.
        if not args.only or args.only.startswith("learn"):
            print("\n=== learning from a correction ===")
            pad.clear()
            pad.focus()
            dictate(app, load("hi_mixed"))
            time.sleep(0.4)
            first = pad.text()
            corrected = first.replace("karunga", "karoonga").replace("Karunga", "Karoonga")
            learned_ok = corrected != first
            if learned_ok:
                pad.type_over(corrected)
                pad.focus()
                pad.win.SendKeys("{Ctrl}{End}", waitTime=0.1)
                pad.win.SendKeys(" ", waitTime=0.1)
                dictate(app, load("hi_mixed"))
                time.sleep(0.4)
                second = pad.text()
                learned_ok = second.count("karoonga") >= 2
                print(f"  first   {first!r}\n  edited  {corrected!r}\n  next    {second!r}")
            else:
                print(f"  could not find 'karunga' to correct in {first!r}")
            fails += not learned_ok
            print(f"[{'  ok  ' if learned_ok else ' FAIL '}] the correction was learned")
            rows.append({"case": "learning", "ok": learned_ok})
    finally:
        pad.close()

    waits = [r["wait_ms"] for r in rows if "wait_ms" in r]
    if waits:
        print(f"\nwait after stopping: median {statistics.median(waits):.0f} ms, "
              f"worst {max(waits):.0f} ms")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"e2e_app_{args.backend}.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{'all passed' if not fails else f'{fails} FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
