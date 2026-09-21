#!/usr/bin/env python
"""The app's hotkey flow, with fake audio and fake models.

What these guard is what a user feels: which audio a recording takes, which
hotkeys may interrupt which, what happens when a model is missing, and that no
state leaks from one dictation into the next.

    python tests/test_app_flow.py
"""

from __future__ import annotations

import sys
import tempfile
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from livewhisper import main as main_mod  # noqa: E402
from livewhisper import output, providers  # noqa: E402
from livewhisper import config as cfgio  # noqa: E402
from livewhisper.console import setup as _console  # noqa: E402
from livewhisper.transcribe import AutoBackend, GroqBackend, LocalBackend  # noqa: E402

_console()
ROOT = Path(__file__).resolve().parent.parent
fails = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    fails += not ok
    print(f"[{'  ok  ' if ok else ' FAIL '}] {name}" + (f"  {detail}" if detail else ""))


class FakeRecorder:
    made: list = []

    def __init__(self, capture_system, capture_mic, system_gain=1.0, mic_gain=1.0):
        self.capture_system, self.capture_mic = capture_system, capture_mic
        FakeRecorder.made.append(self)

    def start(self):
        pass

    def snapshot(self):
        return np.zeros(16000 * 3, np.float32)

    def stop(self):
        return types.SimpleNamespace(audio=np.zeros(16000 * 2, np.float32), seconds=2.0,
                                     system_peak=0.5, mic_peak=0.5)


class FakeBackend:
    def __init__(self):
        self.generation = 0

    def new_recording(self):
        self.generation += 1
        return self.generation

    def prime(self, audio, generation=None):
        return None

    def transcribe(self, audio, hotwords=""):
        return "hello there"


def make_app():
    main_mod.Recorder = FakeRecorder
    main_mod.context.capture = lambda **kw: None
    tmp = Path(tempfile.mkdtemp())
    cfg = cfgio.load(ROOT / "config.yaml")
    cfg["ui"]["overlay"] = False
    path = tmp / "config.yaml"
    cfgio.save(path, cfg)
    app = main_mod.App(path)
    app._backend = FakeBackend()
    app.notices = []
    app.notify = lambda msg, title="": app.notices.append(msg)
    return app


def main() -> int:
    print("=== which audio a recording takes ===")
    app = make_app()
    FakeRecorder.made.clear()
    app._start("dictate")
    rec = FakeRecorder.made[-1]
    check("dictation records the microphone only",
          rec.capture_mic and not rec.capture_system)
    app._prime_stop.set()
    app.recorder = None
    app.state = main_mod.State.IDLE
    app.note_mode = True
    app._start("dictate")
    rec = FakeRecorder.made[-1]
    check("notes mode records the meeting too", rec.capture_mic and rec.capture_system)
    app._prime_stop.set()
    app.recorder, app.state, app.note_mode = None, main_mod.State.IDLE, False
    app.cfg["audio"]["dictation_includes_system"] = True
    app._start("dictate")
    check("dictation can opt back in to system audio", FakeRecorder.made[-1].capture_system)
    app._prime_stop.set()
    app.recorder, app.state = None, main_mod.State.IDLE
    app.actions.unavailable = lambda: None
    app.toggle_command()
    check("Ctrl+Alt+W listens to the microphone only",
          FakeRecorder.made[-1].capture_mic and not FakeRecorder.made[-1].capture_system)
    app._prime_stop.set()

    print("\n=== hotkeys do not trample each other ===")
    app = make_app()
    app.actions.unavailable = lambda: None
    app.toggle_record()
    check("dictation started", app.state is main_mod.State.RECORDING)
    before = len(FakeRecorder.made)
    app.toggle_command()
    check("Ctrl+Alt+W during a dictation is refused, the dictation keeps going",
          app.state is main_mod.State.RECORDING and app._mode == "dictate"
          and len(FakeRecorder.made) == before, str(app.notices[-1:]))
    app.fix_field()
    check("Ctrl+Alt+F during a dictation is refused",
          app.state is main_mod.State.RECORDING, str(app.notices[-1:]))
    app._prime_stop.set()

    app = make_app()
    app.actions.unavailable = lambda: "Writing needs a language model."
    app.toggle_command()
    check("a missing writing model is reported before listening",
          app.state is main_mod.State.IDLE and app.recorder is None
          and "language model" in app.notices[-1], str(app.notices[-1:]))

    app = make_app()
    app.actions.unavailable = lambda: None
    written: list = []
    app.actions.compose = lambda instruction, profile, screen: f"OK: {instruction}"
    orig_deliver = output.deliver
    output.deliver = lambda text, **kw: (written.append(text), (True, True))[1]
    try:
        app.toggle_command()
        check("Ctrl+Alt+W started listening", app.state is main_mod.State.RECORDING
              and app._mode == "command")
        app.toggle_command()
        deadline = time.time() + 5
        while app.state is not main_mod.State.IDLE and time.time() < deadline:
            time.sleep(0.02)
        check("pressing it again writes and pastes the text",
              written and written[-1].startswith("OK: hello there"), str(written))
    finally:
        output.deliver = orig_deliver

    print("\n=== a language settled for one recording stays with it ===")
    import faster_whisper
    b = LocalBackend({"batch_size": 1, "models": {}}, languages=["hi", "en"])
    b._model = types.SimpleNamespace(
        detect_language=lambda a, vad_filter=True: ("hi", 0.9, [("hi", 0.9), ("en", 0.1)]),
        transcribe=lambda a, **kw: (iter([types.SimpleNamespace(text="x", start=0, end=1)]),
                                    types.SimpleNamespace(language=kw.get("language"),
                                                          language_probability=1.0)))
    b.load = lambda: None
    g = b.new_recording()
    b.transcribe(np.zeros(16000, np.float32))
    b.prime(np.zeros(16000, np.float32), generation=g)    # arrives too late
    check("detection that finishes after its recording was transcribed is dropped",
          b._primed is None, str(b._primed))
    g2 = b.new_recording()
    b.prime(np.zeros(16000, np.float32), generation=g2)
    check("detection for the current recording is kept", b._primed == "hi")
    b.forget_priming()
    b.prime(np.zeros(16000, np.float32), generation=g2)
    check("a cancelled recording's detection is dropped even if it finishes later",
          b._primed is None, str(b._primed))

    groq = GroqBackend({})
    groq.is_configured = lambda: False
    auto = AutoBackend(groq, b)
    g3 = auto.new_recording()
    auto.prime(np.zeros(16000, np.float32), generation=g3)
    check("the default auto engine settles the language early too", b._primed == "hi")

    print("\n=== warm-up never downloads ===")
    cold = LocalBackend({"model": "large-v3-not-downloaded", "batch_size": 1})
    loaded = []
    cold.load = lambda: loaded.append(1)
    cold.is_downloaded = lambda: False
    cold.warm()
    check("an undownloaded model is not loaded at launch", not loaded)

    print("\n=== the clipboard ===")
    calls = {"n": 0}
    real_copy = output.pyperclip.copy

    def flaky(text):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("OpenClipboard failed")
    output.pyperclip.copy = flaky
    try:
        output._copy("x")
        check("a clipboard held by another app is retried", calls["n"] == 3)
        output.pyperclip.copy = lambda t: (_ for _ in ()).throw(RuntimeError("busy"))
        try:
            output._copy("x", attempts=3)
            check("a clipboard that stays busy is reported as busy", False)
        except output.ClipboardBusy:
            check("a clipboard that stays busy is reported as busy", True)
    finally:
        output.pyperclip.copy = real_copy

    print("\n=== writing models ===")
    import os
    saved = os.environ.pop("GROQ_API_KEY", None)
    os.environ["GROQ_API_KEY"] = "test"
    providers.Ollama.available = lambda self: False
    p = providers.build({"provider": "ollama", "model": "qwen2.5:7b"})
    check("falling back to Groq uses Groq's own model, not the Ollama one",
          p.name == "groq" and p.model == "llama-3.3-70b-versatile", p.model)
    del os.environ["GROQ_API_KEY"]
    try:
        providers.build({"provider": "ollama", "model": "qwen2.5:7b"})
        check("no model anywhere names the fix", False)
    except providers.ProviderError as e:
        check("no model anywhere names the fix", "ollama pull qwen2.5:7b" in str(e), str(e))
    if saved is not None:
        os.environ["GROQ_API_KEY"] = saved

    print(f"\n{'all passed' if not fails else f'{fails} FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
