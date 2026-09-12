#!/usr/bin/env python
"""Capture whatever is currently playing and measure transcription accuracy.

    python test_accuracy.py --seconds 60 --label panel
    python test_accuracy.py --seconds 60 --label panel --reference ref.txt

With a reference file it reports WER. The reference is usually YouTube's own
captions, which are themselves imperfect - so treat the number as an upper bound
on error, not ground truth.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import yaml

from livewhisper.audio import Recorder, write_wav
from livewhisper.transcribe import build_backend

from livewhisper.console import setup as _console

_console()

OUT = Path("accuracy_runs")


def normalise(text: str) -> list[str]:
    """Lowercase, strip punctuation - compare words, not typography."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9ऀ-ॿ\s']", " ", text)
    return text.split()


def wer(ref: list[str], hyp: list[str]) -> tuple[float, int, int, int]:
    """Levenshtein over words. Returns (wer, substitutions, deletions, insertions)."""
    n, m = len(ref), len(hyp)
    if n == 0:
        return (0.0 if m == 0 else 1.0), 0, 0, m
    # Full DP table so we can backtrace the error breakdown.
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)

    i, j, sub, dele, ins = n, m, 0, 0, 0
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            if ref[i - 1] != hyp[j - 1]:
                sub += 1
            i, j = i - 1, j - 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            dele += 1
            i -= 1
        else:
            ins += 1
            j -= 1
    return d[n][m] / n, sub, dele, ins


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--label", default="run")
    ap.add_argument("--reference", type=Path, default=None)
    ap.add_argument("--backend", default=None, help="override: auto | groq | local")
    ap.add_argument("--keep-audio", action="store_true")
    args = ap.parse_args()

    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    backend_name = args.backend or cfg["transcription"].get("backend", "auto")
    OUT.mkdir(exist_ok=True)

    print(f"recording {args.seconds:.0f}s of system audio + mic ...")
    rec = Recorder(
        capture_system=cfg["audio"].get("capture_system", True),
        capture_mic=cfg["audio"].get("capture_mic", True),
    )
    rec.start()
    time.sleep(args.seconds)
    r = rec.stop()
    print(f"  captured {r.seconds:.1f}s  system_peak={r.system_peak:.3f}  "
          f"mic_peak={r.mic_peak:.3f}")
    if r.system_peak < 1e-4:
        print("  FAIL: no system audio captured")
        return 1

    if args.keep_audio:
        write_wav(OUT / f"{args.label}.wav", r.audio)

    backend = build_backend(backend_name, cfg["transcription"])
    if hasattr(backend, "notify"):
        backend.notify = lambda m: print(f"  [{m}]")
    t0 = time.time()
    text = backend.transcribe(r.audio)
    print(f"  transcribed in {time.time()-t0:.1f}s via {backend_name} "
          f"({r.seconds/max(time.time()-t0, .01):.0f}x realtime)")

    path = OUT / f"{args.label}.txt"
    path.write_text(text, encoding="utf-8")
    words = len(text.split())
    print(f"  {words} words -> {path}\n")
    print(text[:900] + ("..." if len(text) > 900 else ""))

    if args.reference and args.reference.exists():
        ref = normalise(args.reference.read_text(encoding="utf-8"))
        hyp = normalise(text)
        rate, sub, dele, ins = wer(ref, hyp)
        print(f"\n  reference words : {len(ref)}")
        print(f"  hypothesis words: {len(hyp)}")
        print(f"  WER             : {rate*100:.1f}%  "
              f"(sub {sub}, del {dele}, ins {ins})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
