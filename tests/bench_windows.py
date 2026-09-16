#!/usr/bin/env python
"""Which decode window keeps every word without costing single sentences?

Two failure modes pull in opposite directions:

  long windows   Whisper stops early on a packed 30-second window. A 40-second
                 Hindi recording came back with 62 of its 92 words.
  short windows  cut a single sentence mid-speech and lose context: 10-second
                 windows raised Hindi's error on single FLEURS sentences from
                 27.8% to 31.0%.

So each candidate is scored on both at once: the FLEURS sentences on their own,
and paragraph-length recordings built by joining three of them with pauses.

    python tests/bench_windows.py build/fleurs --langs hi,en --n 36
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

from bench_asr import edit, load_audio, words  # noqa: E402
from livewhisper.console import setup as _console  # noqa: E402
from livewhisper.transcribe import window_for  # noqa: E402

_console()
OUT = Path(__file__).resolve().parent / "results"
RATE = 16000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("data", type=Path)
    ap.add_argument("--langs", default="hi,en")
    ap.add_argument("--n", type=int, default=36)
    ap.add_argument("--model", default="large-v3")
    args = ap.parse_args()

    manifest = json.loads((args.data / "manifest.json").read_text(encoding="utf-8"))
    from faster_whisper import BatchedInferencePipeline, WhisperModel

    model = WhisperModel(args.model, device="cuda", compute_type="int8_float16")
    batched = BatchedInferencePipeline(model=model)

    candidates = {
        "30 (library)": lambda secs: None,
        "20": lambda secs: 20,
        "15": lambda secs: 15,
        "10": lambda secs: 10,
        "shipped": window_for,
    }

    results: dict = {}
    for lang in [x for x in args.langs.split(",") if x]:
        clips = [c for c in manifest if c["lang"] == lang][: args.n]
        singles = [(load_audio(args.data / c["name"]), c["reference"]) for c in clips]
        pause = np.zeros(int(0.8 * RATE), dtype=np.float32)
        paragraphs = []
        for i in range(0, len(singles) - 2, 3):
            group = singles[i:i + 3]
            audio = np.concatenate([group[0][0], pause, group[1][0], pause, group[2][0]])
            paragraphs.append((audio, " ".join(r for _a, r in group)))

        print(f"\n=== {lang}: {len(singles)} sentences "
              f"(median {np.median([len(a) for a, _ in singles]) / RATE:.0f}s), "
              f"{len(paragraphs)} paragraphs "
              f"(median {np.median([len(a) for a, _ in paragraphs]) / RATE:.0f}s) ===")
        print(f"  {'window':<20} {'sentences WER':>14} {'paragraphs WER':>15} "
              f"{'words kept':>11} {'paragraph wall':>15}")
        for name, pick in candidates.items():
            row = {}
            for kind, items in (("sentences", singles), ("paragraphs", paragraphs)):
                e = n = got = 0
                wall = 0.0
                for audio, ref in items:
                    t0 = time.perf_counter()
                    segs, _ = batched.transcribe(
                        audio, batch_size=8, language=lang, beam_size=5,
                        chunk_length=pick(len(audio) / RATE))
                    hyp = " ".join(s.text.strip() for s in segs)
                    wall += time.perf_counter() - t0
                    r = words(ref)
                    e += edit(r, words(hyp))
                    n += len(r)
                    got += min(len(words(hyp)), len(r))
                row[kind] = {"wer": e / n, "kept": got / n,
                             "wall_ms": wall / len(items) * 1000}
            results.setdefault(lang, {})[name] = row
            print(f"  {name:<20} {row['sentences']['wer']:>14.1%} "
                  f"{row['paragraphs']['wer']:>15.1%} "
                  f"{row['paragraphs']['kept']:>11.0%} "
                  f"{row['paragraphs']['wall_ms']:>13.0f}ms", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "decode_windows.json").write_text(json.dumps(results, indent=1),
                                             encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
