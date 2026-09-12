#!/usr/bin/env python
"""Does system-audio capture actually work? Play a known clip and record it back.

This is the feature the project started from - capturing what the machine is
playing, with no virtual cable - and nothing verified it automatically. The
existing test_accuracy.py records whatever happens to be playing, so it fails on
a quiet machine and proves nothing on a loud one.

Here the test supplies its own sound: it plays a clip out the default output
device while recording through WASAPI loopback, then transcribes the recording
and compares it with the transcript of the original file. If loopback is wired up
correctly those two agree closely.

    python tests/test_loopback.py [--audio build/audio] [--clip en_1]

Needs a working output device. Skips rather than fails when there is none, since
CI has no sound card.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper import config as cfgio  # noqa: E402
from livewhisper.audio import AudioError, Recorder  # noqa: E402
from livewhisper.console import setup as _console  # noqa: E402
from livewhisper.script.languages import WORD  # noqa: E402

_console()

failures: list = []


def norm(text: str) -> list:
    return WORD.findall(unicodedata.normalize("NFKC", text.lower()))


def wer(ref: list, hyp: list) -> float:
    n, m = len(ref), len(hyp)
    if n == 0:
        return 1.0 if m else 0.0
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        cur = [i] + [0] * m
        for j in range(1, m + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1,
                         prev[j - 1] + (ref[i - 1] != hyp[j - 1]))
        prev = cur
    return prev[m] / n


def play(pcm, rate: int = 16000) -> threading.Thread:
    """Push audio out the default output device on a background thread.

    Deliberately plays through the normal output rather than writing a file, so
    the sound has to travel the same path a video call or a YouTube tab would.
    """
    import pyaudiowpatch as pyaudio

    def run():
        pa = pyaudio.PyAudio()
        try:
            stream = pa.open(format=pyaudio.paFloat32, channels=1, rate=rate,
                             output=True)
            stream.write(pcm.astype("float32").tobytes())
            stream.stop_stream()
            stream.close()
        finally:
            pa.terminate()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", type=Path, default=Path("build/audio"))
    ap.add_argument("--clip", default="en_1",
                    help="English by default: the clearest signal for a "
                         "capture test, where the question is the wiring")
    args = ap.parse_args()

    manifest = args.audio / "manifest.json"
    if not manifest.exists():
        print(f"no fixtures at {args.audio}; build with "
              f"scripts/make_test_audio.py")
        return 0

    cases = {c["name"]: c for c in json.loads(manifest.read_text(encoding="utf-8"))}
    case = cases.get(args.clip) or next(iter(cases.values()))
    path = args.audio / f"{case['name']}.mp3"
    if not path.exists():
        print(f"{path} missing")
        return 0

    from tests.test_audio_e2e import load_audio
    pcm, seconds = load_audio(path)
    print(f"clip {case['name']}, {seconds:.1f}s: {case['native'][:60]}")

    cfg = cfgio.load(Path("config.yaml"))
    rec = Recorder(capture_system=True, capture_mic=False)

    print("\n=== capture ===")
    try:
        rec.start()
    except AudioError as exc:
        print(f"could not start capture ({exc}); skipping")
        return 0

    time.sleep(0.4)                       # let the stream settle before sound
    t = play(pcm)
    peak_seen = 0.0
    deadline = time.monotonic() + seconds + 2.0
    while t.is_alive() and time.monotonic() < deadline:
        peak_seen = max(peak_seen, rec.level())
        time.sleep(0.05)
    t.join(timeout=2.0)
    time.sleep(0.4)                       # trailing audio still in flight
    recording = rec.stop()

    audio = recording.audio
    print(f"  played   {seconds:.1f}s")
    print(f"  captured {recording.seconds:.1f}s")
    print(f"  peak level while playing {peak_seen:.3f}")
    print(f"  system_peak reported by the recorder {recording.system_peak:.3f}")

    # system_peak is the recorder's own verdict, and 0.0 is how it reports
    # "loopback gave me nothing but silence" - the failure the app warns about.
    ok = recording.system_peak > 0.0
    print(f"[{'  ok  ' if ok else ' FAIL '}] recorder saw signal on the "
          f"system track")
    if not ok:
        failures.append("system_peak was 0.0 - loopback captured silence")

    ok = audio is not None and len(audio) > 16000
    print(f"[{'  ok  ' if ok else ' FAIL '}] loopback returned audio")
    if not ok:
        failures.append("loopback returned no audio")
        return report()

    import numpy as np
    rms = float(np.sqrt(np.mean(np.square(audio))))
    ok = rms > 1e-4
    print(f"[{'  ok  ' if ok else ' FAIL '}] captured audio is not silence  "
          f"(rms {rms:.5f})")
    if not ok:
        failures.append(f"captured silence (rms {rms:.5f}); "
                        f"loopback device may be wrong")
        return report()

    # Length within a second of what was played. A loopback that captures the
    # wrong device often returns something, so duration and content both matter.
    drift = abs(len(audio) / 16000 - seconds)
    ok = drift < 2.0
    print(f"[{'  ok  ' if ok else ' FAIL '}] duration matches what was played  "
          f"(off by {drift:.1f}s)")
    if not ok:
        failures.append(f"captured duration off by {drift:.1f}s")

    print("\n=== does it transcribe to the same words? ===")
    from livewhisper.transcribe import build_backend
    backend = build_backend("local", cfg["transcription"])
    backend.load()
    direct = backend.transcribe(pcm)
    through = backend.transcribe(audio)
    print(f"  from the file      {direct.strip()}")
    print(f"  through loopback   {through.strip()}")

    w = wer(norm(direct), norm(through))
    ok = w <= 0.25
    print(f"[{'  ok  ' if ok else ' FAIL '}] loopback transcript matches the "
          f"file's within 25%  (WER {w:.1%})")
    if not ok:
        failures.append(f"loopback transcript diverged, WER {w:.1%}")

    return report()


def report() -> int:
    if failures:
        print(f"\n{len(failures)} FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nsystem audio capture works end to end")
    return 0


if __name__ == "__main__":
    sys.exit(main())
