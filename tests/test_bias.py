#!/usr/bin/env python
"""Names taken off the screen and handed to the decoder.

The useful half is obvious; the dangerous half is that a prompt full of
irrelevant words drags the transcript toward them. So the rules here are about
what must NOT end up in the prompt, and tests/bench_bias.py measures what it
does to real audio.

    python tests/test_bias.py
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from livewhisper.bias import MAX_CHARS, MAX_PHRASES, candidates, phrases  # noqa: E402
from livewhisper.console import setup as _console  # noqa: E402

_console()
fails = 0

EMAIL = """Subject: Kubernetes migration timeline
From: Priya Raghavan

Hi Sarthak, the WASAPI issue Marcus raised is still open. Priya thinks the
LiveWhisper rollout should wait until Thursday. Can you confirm the GST
numbers today?
"""


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    fails += not ok
    print(f"[{'  ok  ' if ok else ' FAIL '}] {name}" + (f"  {detail}" if detail else ""))


def main() -> int:
    print("=== what gets picked up ===")
    got = phrases(EMAIL)
    picked = [w.strip() for w in got.split(",")]
    for name in ("Priya", "Sarthak", "Marcus", "Raghavan", "WASAPI",
                 "LiveWhisper", "Kubernetes", "GST"):
        check(f"{name} is offered to the decoder", name in picked, got)
    check("the names people repeat come first",
          picked.index("Priya") < picked.index("Kubernetes"), got)

    print("\n=== what must not ===")
    for word in ("Subject", "From", "Hi", "Can", "The", "Thanks"):
        check(f"{word!r} is not treated as a name", word not in picked, got)
    check("ordinary prose offers nothing at all",
          phrases("the meeting is at five and we should go now. this is fine.") == "",
          repr(phrases("the meeting is at five. this is fine.")))
    check("an empty screen is empty", phrases("", "") == "")
    check("a single letter is not a name", "I" not in phrases("I went. I saw."))

    print("\n=== the field being typed into counts for more ===")
    ranked = [w.strip() for w in phrases(EMAIL, focused_text="Marcus Marcus").split(",")]
    check("a name in the focused field outranks one in the window",
          ranked.index("Marcus") < ranked.index("Priya"), str(ranked[:4]))

    print("\n=== the user's own vocabulary wins ===")
    got = phrases(EMAIL, extra="Dakshina, CTranslate2")
    check("their words come first", got.startswith("Dakshina, CTranslate2"), got)
    check("and the screen still contributes", "Priya" in got, got)

    print("\n=== it stays small ===")
    letters = "abcdefghijklmnopqrstuvwxyz"
    made = [f"N{letters[i % 26]}{letters[i // 26 % 26]}ndal" for i in range(300)]
    crowded = " ".join(f"and {w} {w} said something here." for w in made)
    got = phrases(crowded)
    offered = [w for w in got.split(", ") if w]
    check("the screen really did have names on it",
          len(offered) > 5 and offered[0] in made, got[:60])
    check(f"at most {MAX_PHRASES} phrases", len(offered) <= MAX_PHRASES, f"{len(offered)}")
    check(f"at most {MAX_CHARS} characters", len(got) <= MAX_CHARS, f"{len(got)}")

    import time
    big = crowded * 4                            # ~100k characters of window text
    t0 = time.perf_counter()
    phrases(big)
    ms = (time.perf_counter() - t0) * 1000
    check("a full screen of text is read in a few milliseconds", ms < 60,
          f"{ms:.1f} ms for {len(big)} characters")

    print("\n=== duplicates and scoring ===")
    scored = candidates("Priya wrote. Priya replied. Kubernetes is hard.")
    check("a repeated name scores above a single mention",
          scored["Priya"] > scored["Kubernetes"], str(dict(scored)))

    print("\n=== it reaches the decoder ===")
    import faster_whisper

    seen: dict = {}

    class FakeWhisper:
        def __init__(self, *a, **kw):
            pass

        def transcribe(self, audio, **kw):
            seen.update(kw)
            seg = types.SimpleNamespace(text="hello", start=0.0, end=1.0)
            return iter([seg]), types.SimpleNamespace(language="en",
                                                      language_probability=1.0)

        def detect_language(self, audio, vad_filter=False):
            return "en", 1.0, [("en", 1.0)]

    saved = faster_whisper.WhisperModel, faster_whisper.BatchedInferencePipeline
    faster_whisper.WhisperModel = FakeWhisper
    faster_whisper.BatchedInferencePipeline = lambda model: None
    try:
        from livewhisper.transcribe import LocalBackend
        b = LocalBackend({"batch_size": 1, "language": "en"}, vocabulary="Dakshina")
        b._model = FakeWhisper()
        b.load = lambda: None
        b.transcribe(np.zeros(16000, "float32"), hotwords="Priya, Marcus")
        check("the names are passed as hotwords", seen.get("hotwords") == "Priya, Marcus",
              str(seen.get("hotwords")))
        prompt = seen.get("initial_prompt") or ""
        check("the configured vocabulary still goes in as the prompt",
              prompt.endswith("Dakshina"), prompt)
        check("English is told to expect spoken punctuation",
              prompt.startswith(LocalBackend.SPOKEN_PUNCTUATION), prompt)
        b.transcribe(np.zeros(16000, "float32"))
        check("no names on screen means no hotwords at all",
              seen.get("hotwords") is None, str(seen.get("hotwords")))
    finally:
        faster_whisper.WhisperModel, faster_whisper.BatchedInferencePipeline = saved

    print(f"\n{'all passed' if not fails else f'{fails} FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
