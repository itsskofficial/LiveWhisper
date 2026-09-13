#!/usr/bin/env python
"""Language restriction and per-language model switching, with fake models.

No GPU and no downloads: faster-whisper is replaced by stand-ins that record
what they were asked, so this checks the decisions - which language, which
model, which decode token, what gets reported back - rather than the models.

    python tests/test_routing.py
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import faster_whisper  # noqa: E402

from livewhisper.console import setup as _console  # noqa: E402

_console()
loads: list = []
fails = 0


class FakeWhisper:
    def __init__(self, path, device=None, compute_type=None):
        if "broken" in path:
            raise RuntimeError("bad weights")
        loads.append(path)
        self.path = path

    def transcribe(self, audio, **kw):
        seg = types.SimpleNamespace(text=f"[{self.path}:{kw.get('language')}]")
        info = types.SimpleNamespace(language=kw.get("language"), language_probability=1.0)
        return iter([seg]), info

    def detect_language(self, audio, vad_filter=False):
        # What Whisper really did on short Hindi clips: Urdu on top.
        return "ur", 0.6, [("ur", 0.6), ("hi", 0.3), ("en", 0.1)]


faster_whisper.WhisperModel = FakeWhisper
faster_whisper.BatchedInferencePipeline = lambda model: None

from livewhisper.transcribe import AutoBackend, GroqBackend, LocalBackend  # noqa: E402


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    fails += not ok
    print(f"[{'  ok  ' if ok else ' FAIL '}] {name}" + (f"  {detail}" if detail else ""))


def backend(**cfg_extra) -> LocalBackend:
    cfg = {"batch_size": 1, "max_extra_models": 1, "models": {
        "ta": "ta-spec",
        "hi": {"path": "hinglish", "latin_output": True, "language": "en"},
        "kn": "broken-spec"}}
    cfg.update(cfg_extra)
    b = LocalBackend(cfg, languages=["hi", "ta", "kn", "en"])
    b._model = FakeWhisper("main")
    b._batched = None
    return b


def main() -> int:
    audio = np.zeros(16000, "float32")

    print("=== detection limited to the user's languages ===")
    b = backend()
    b.load = lambda: None
    out = b.transcribe(audio)
    check("Urdu-leaning detection resolved to Hindi, routed to the Hinglish model "
          "and decoded with its own token", out == "[hinglish:en]", out)
    check("the app is still told the audio was Hindi", b.last_language == "hi",
          str(b.last_language))
    check("latin_output raised for that model", b.last_latin_output is True)
    free = LocalBackend({"batch_size": 1}, languages=[])
    free._model = FakeWhisper("main")
    check("no restriction configured leaves detection to Whisper",
          free._pick_language(audio) is None)

    print("\n=== switching ===")
    b.cfg["language"] = "ta"
    check("plain path route", b.transcribe(audio) == "[ta-spec:ta]"
          and b.last_latin_output is False)
    b.cfg["language"] = "en"
    check("unrouted language uses the main model", b.transcribe(audio) == "[main:en]"
          and b.last_language == "en")
    b.cfg["language"] = "kn"
    check("a specialist that will not load falls back to the main model",
          b.transcribe(audio) == "[main:kn]")
    b.cfg["max_extra_models"] = 2
    b._routed.clear()
    for lang in ("ta", "hi", "ta"):
        b.cfg["language"] = lang
        b.transcribe(audio)
    check("most recently used specialist kept last",
          list(b._routed) == ["hinglish", "ta-spec"], str(list(b._routed)))
    b.cfg["max_extra_models"] = 0
    b._routed.clear()
    b.cfg["language"] = "ta"
    check("max_extra_models 0 disables specialists", b.transcribe(audio) == "[main:ta]")

    print("\n=== loading is visible, and the main language is ready early ===")
    messages: list = []
    b = backend()
    b.notify = messages.append
    b._model = None
    loads.clear()
    b.cfg["model"] = "main"
    b.load()
    check("load() preloads the main language's specialist",
          "hinglish" in loads, str(loads))
    check("the tray is told while it loads",
          any("Hindi" in m for m in messages), str(messages))
    messages.clear()
    b.cfg["language"] = "hi"
    b.transcribe(audio)
    check("no second load message once it is warm", not messages, str(messages))

    print("\n=== combined backend ===")
    g = GroqBackend({})
    g.is_configured = lambda: True
    g.transcribe = lambda a: "groq text"
    g.last_language = "hi"
    local = backend()
    local.last_latin_output = True                # stale, from an earlier local run
    auto = AutoBackend(g, local)
    check("Groq-served text never reports latin_output",
          auto.transcribe(audio) == "groq text" and auto.last_latin_output is False)

    print(f"\n{'all passed' if not fails else f'{fails} FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
