#!/usr/bin/env python
"""Where the time goes between releasing the hotkey and seeing text.

A dictation tool is judged on the pause after you stop talking, so this measures
each stage separately rather than quoting one throughput figure. Throughput and
latency are different questions: a model that runs at 27x realtime on a
five-minute recording still takes a second on a three-second one, because the
fixed costs do not shrink.

    python tests/bench_latency.py [--audio build/audio] [--repeat 5]

Transcription is measured only if audio fixtures exist; everything else runs
anywhere.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper import config as cfgio  # noqa: E402
from livewhisper.console import setup as _console  # noqa: E402
from livewhisper.context import ScreenContext  # noqa: E402
from livewhisper.pipeline import Pipeline  # noqa: E402
from livewhisper.profile import ProfileStore  # noqa: E402
from livewhisper.script.languages import CODES  # noqa: E402
from livewhisper.script.romanize import Romanizer  # noqa: E402

_console()

# One sentence per length, so the reader can see how cost scales with input.
SHORT = "कल मैं office जाऊंगा"
MEDIUM = SHORT + " और मीटिंग अटेंड " \
    "करूंगा, बाद में " \
    "बात करते हैं"
LONG = " ".join([MEDIUM] * 12)


def timed(fn, repeat: int) -> tuple:
    """(median_ms, p95_ms). Median because one GC pause should not set the number."""
    xs = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        xs.append((time.perf_counter() - t0) * 1000)
    xs.sort()
    p95 = xs[min(len(xs) - 1, int(len(xs) * 0.95))]
    return statistics.median(xs), p95


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", type=Path, default=Path("build/audio"))
    ap.add_argument("--repeat", type=int, default=9)
    args = ap.parse_args()

    cfg = cfgio.load(Path("config.yaml"))
    store = ProfileStore(Path("build") / "latency_profile.json")
    pipe = Pipeline(cfg, store)

    print("=== cold start: paid once per launch ===")
    # Must be first. Constructing a Romanizer earlier warms the shared lexicon
    # and model caches, and then this reads as 0 ms.
    ms, _ = timed(lambda: Romanizer("hi").text(SHORT), 1)
    print(f"  {'first romanization (loads lexicon + model)':<46} {ms:>9.0f} ms")
    r = Romanizer("hi")

    print("\n=== per dictation, warm ===")
    print(f"  {'stage':<46} {'median':>9} {'p95':>9}")
    rows = [
        ("romanize a short sentence (6 words)", lambda: r.text(SHORT)),
        ("romanize a medium sentence (13 words)", lambda: r.text(MEDIUM)),
        ("romanize a long dictation (156 words)", lambda: r.text(LONG)),
        ("full pipeline, short (romanize + habits)",
         lambda: pipe.process(SHORT, ScreenContext(app="t.exe", title="t",
                                                   text="", focused_text="",
                                                   method="uia"))),
        ("full pipeline, long", lambda: pipe.process(
            LONG, ScreenContext(app="t.exe", title="t", text="",
                                focused_text="", method="uia"))),
        ("learn from a corrected field",
         lambda: pipe.learn_from_screen(
             ScreenContext(app="t.exe", title="t", text="",
                           focused_text="kal main office jaunga", method="uia"))),
        ("profile save (json to disk)", store.save),
    ]
    for label, fn in rows:
        fn()                                     # warm caches first
        ms, p95 = timed(fn, args.repeat)
        print(f"  {label:<46} {ms:>8.2f}ms {p95:>8.2f}ms")

    print("\n=== switching language mid-session ===")
    # Someone who speaks two languages pays this on the first word of the second
    # one, so it matters more than its size suggests.
    for code in ("ta", "ml"):
        ms, _ = timed(lambda c=code: Romanizer(c).text(SHORT), 1)
        print(f"  {'first use of ' + code + ' (loads its lexicon)':<46} "
              f"{ms:>9.0f} ms")
    warm = {c: Romanizer(c) for c in CODES}
    for c in warm:
        warm[c].text(SHORT)
    ms, p95 = timed(lambda: [warm[c].text(SHORT) for c in CODES], args.repeat)
    print(f"  {'romanize once in all 12, all warm':<46} {ms:>8.2f}ms")

    manifest = args.audio / "manifest.json"
    if not manifest.exists():
        print(f"\n(no audio at {args.audio}; skipping transcription. "
              f"Build with scripts/make_test_audio.py)")
        return 0

    print("\n=== transcription: throughput is not latency ===")
    from tests.test_audio_e2e import load_audio           # noqa: E402
    from livewhisper.transcribe import build_backend      # noqa: E402
    import numpy as np

    backend = build_backend("local", cfg["transcription"])
    t0 = time.perf_counter()
    backend.load()
    load_ms = (time.perf_counter() - t0) * 1000
    print(f"  {'model load, once per launch':<46} {load_ms:>9.0f} ms")

    cases = json.loads(manifest.read_text(encoding="utf-8"))
    clips = [args.audio / f"{c['name']}.mp3" for c in cases]
    clips = [p for p in clips if p.exists()]
    if not clips:
        return 0

    # One real clip, then the same audio repeated to build longer inputs. Repeats
    # are not natural speech, but they isolate the question being asked: how much
    # of the wait is fixed cost?
    base, _ = load_audio(clips[0])
    print(f"  {'audio':>8} {'wall':>9} {'xRT':>7} {'fixed cost share':>18}")
    single = None
    for mult in (1, 3, 10, 30):
        pcm = np.tile(base, mult)
        secs = len(pcm) / 16000.0
        t0 = time.perf_counter()
        backend.transcribe(pcm)
        took = time.perf_counter() - t0
        if mult == 1:
            single = took
        share = ""
        if single is not None and mult > 1:
            # Rough split: whatever does not scale with length.
            share = f"{max(0.0, 1 - (took / (single * mult))):.0%} amortised"
        print(f"  {secs:>7.1f}s {took:>8.2f}s {secs / took:>6.1f}x {share:>18}")

    print("\n  The README's throughput figure only applies to long recordings.\n"
          "  For a short dictation the wait is dominated by fixed cost, which is\n"
          "  the number a user actually feels.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
