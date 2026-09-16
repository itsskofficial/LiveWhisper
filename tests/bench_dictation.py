#!/usr/bin/env python
"""Where the seconds go in one dictation, and what the knobs are worth.

The README's throughput figure - 37x realtime on a two-minute recording - is
true and almost irrelevant: nobody waits for a two-minute recording. What you
feel is a four-second sentence, where the fixed costs dominate. This measures
that case directly, breaking one dictation into its parts and then pricing each
decoding option against the same clips.

    python tests/bench_dictation.py build/fleurs --lang en --n 8

Times are medians over `--n` clips, after a warm-up, with the model already
loaded - the state the app is in when you press the hotkey.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

from bench_asr import load_audio  # noqa: E402
from livewhisper.console import setup as _console  # noqa: E402

_console()
OUT = Path(__file__).resolve().parent / "results"


def median_ms(fn, repeat: int) -> float:
    times = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    return statistics.median(times)


def clip(audio: np.ndarray, seconds: float) -> np.ndarray:
    """The first `seconds` of audio, or the whole clip if it is shorter."""
    return audio[: int(seconds * 16000)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("data", type=Path)
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--lang", default="en")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--compute", default="int8_float16")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--label", default=None)
    args = ap.parse_args()

    manifest = json.loads((args.data / "manifest.json").read_text(encoding="utf-8"))
    clips = [c for c in manifest if c["lang"] == args.lang][: args.n]
    if not clips:
        print(f"no {args.lang} clips in {args.data}")
        return 1
    audios = [load_audio(args.data / c["name"]) for c in clips]

    from faster_whisper import BatchedInferencePipeline, WhisperModel

    t0 = time.perf_counter()
    model = WhisperModel(args.model, device=args.device, compute_type=args.compute)
    load_s = time.perf_counter() - t0
    batched = BatchedInferencePipeline(model=model)

    def decode(audio, **kw):
        kw.setdefault("language", args.lang)
        kw.setdefault("beam_size", 5)
        kw.setdefault("vad_filter", True)
        kw.setdefault("condition_on_previous_text", False)
        segments, _info = model.transcribe(audio, **kw)
        return " ".join(s.text for s in segments)

    # The first decode after a load pays for kernel selection and caches. Time
    # it on its own - it is what the first dictation after launch waited for,
    # before the app ran a warm-up decode at launch - then warm up properly.
    t0 = time.perf_counter()
    decode(clip(audios[0], 4))
    first_ms = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    decode(clip(audios[0], 4))
    second_ms = (time.perf_counter() - t0) * 1000
    for a in audios[1:3]:
        decode(clip(a, 4))

    label = args.label or f"{Path(args.model).name}-{args.device}"
    print(f"\n{label}: loaded in {load_s:.1f}s  ({args.compute}, {len(clips)} clips)")
    print(f"first decode after load {first_ms:.0f}ms, the same clip again "
          f"{second_ms:.0f}ms\n")

    print("=== one dictation, by length ===")
    print(f"  {'spoken':>7} {'detect':>9} {'decode':>9} {'total':>9} {'xRT':>7}")
    rows: list = []
    for seconds in (2.0, 4.0, 8.0, 15.0):
        cuts = [clip(a, seconds) for a in audios]
        actual = statistics.median(len(c) / 16000 for c in cuts)
        det = statistics.median(
            median_ms(lambda c=c: model.detect_language(c[: 30 * 16000],
                                                        vad_filter=True), 1)
            for c in cuts)
        dec = statistics.median(median_ms(lambda c=c: decode(c), 1) for c in cuts)
        total = det + dec
        rows.append({"seconds": actual, "detect_ms": det, "decode_ms": dec,
                     "total_ms": total})
        print(f"  {actual:>6.1f}s {det:>8.0f}ms {dec:>8.0f}ms {total:>8.0f}ms "
              f"{actual / (total / 1000):>6.1f}x")

    print("\n=== what each option costs, on a 4-second dictation ===")
    four = [clip(a, 4.0) for a in audios]

    def timed(name: str, **kw) -> float:
        ms = statistics.median(median_ms(lambda c=c: decode(c, **kw), 1) for c in four)
        print(f"  {name:<44} {ms:>8.0f}ms")
        return ms

    base = timed("beam 5, VAD on  (what ships today)")
    options = {
        "beam 1": timed("beam 1", beam_size=1),
        "beam 2": timed("beam 2", beam_size=2),
        "no VAD": timed("beam 5, VAD off", vad_filter=False),
        "beam 1 no VAD": timed("beam 1, VAD off", beam_size=1, vad_filter=False),
    }
    ms = statistics.median(
        median_ms(lambda c=c: " ".join(
            s.text for s in batched.transcribe(c, batch_size=8, language=args.lang,
                                               beam_size=5)[0]), 1) for c in four)
    options["batched 8"] = ms
    print(f"  {'batched (8), beam 5':<44} {ms:>8.0f}ms")

    print(f"\n  baseline {base:.0f}ms; best option saves "
          f"{base - min(options.values()):.0f}ms "
          f"({min(options, key=options.get)})")

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"dictation_{label}.json"
    path.write_text(json.dumps(
        {"model": args.model, "device": args.device, "compute": args.compute,
         "lang": args.lang, "clips": len(clips), "load_s": load_s,
         "first_decode_ms": first_ms, "second_decode_ms": second_ms,
         "by_length": rows, "options_4s_ms": {"baseline_beam5_vad": base, **options}},
        indent=1), encoding="utf-8")
    print(f"\nwritten to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
