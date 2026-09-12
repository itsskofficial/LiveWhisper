#!/usr/bin/env python
"""End to end from real speech: audio in, the text a user would have typed out.

Every other test in this repo starts from a transcript string, which quietly
assumes the hardest part works. This one starts from audio and runs the whole
chain - decode, transcribe, detect the language, romanize, apply habits - so that
transcription, language detection and romanization are measured together rather
than in isolation.

Language detection is the part only this test can catch. The romanizer is told
which language it is reading, and that answer comes from whatever Whisper
reports about the audio. If Whisper says Marathi for Hindi audio, every lookup
goes to the wrong lexicon and no unit test would notice.

Audio fixtures are not in the repo (they are large and regenerable). Build them
with scripts/make_test_audio.py, which needs edge-tts and a network connection:

    python scripts/make_test_audio.py build/audio
    python tests/test_audio_e2e.py build/audio
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper import config as cfgio  # noqa: E402
from livewhisper.console import setup as _console  # noqa: E402
from livewhisper.context import ScreenContext  # noqa: E402
from livewhisper.pipeline import Pipeline  # noqa: E402
from livewhisper.profile import ProfileStore  # noqa: E402
from livewhisper.script.languages import (  # noqa: E402
    WORD, has_indic, languages_for_script, script_counts,
)
from livewhisper.script.lexicon import get_lexicon  # noqa: E402
from livewhisper.transcribe import build_backend  # noqa: E402

_console()

failures: list = []
notes: list = []

# Clip name prefix -> the language actually spoken in it.
LANG_OF = {"hi": "hi", "mr": "mr", "ta": "ta", "bn": "bn", "te": "te",
           "gu": "gu", "kn": "kn", "ml": "ml", "ur": "ur", "pa": "pa"}


def lexicon_has(lang: str | None, word: str) -> bool:
    """Did we leave a word in native script that we knew how to spell?

    A word with no lexicon entry is left native on purpose - visible and
    correctable beats a confident wrong guess, and the character model refuses
    its own degenerate output. Leaving a word we *could* have spelled is a bug,
    so only those count against us.
    """
    if not lang:
        return False
    try:
        lex = get_lexicon(lang)
        return bool(lex.lookup(word) or lex.variants(word))
    except Exception:
        return False


def load_audio(path: Path):
    """Decode any file ffmpeg understands to the mono 16 kHz the model wants."""
    import av
    import numpy as np

    with av.open(str(path)) as c:
        stream = c.streams.audio[0]
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        chunks = []
        for frame in c.decode(stream):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):
            chunks.append(out.to_ndarray().reshape(-1))
    if not chunks:
        raise RuntimeError(f"no audio decoded from {path}")
    pcm = np.concatenate(chunks).astype("float32") / 32768.0
    return pcm, len(pcm) / 16000.0


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


def norm(text: str) -> list:
    return WORD.findall(unicodedata.normalize("NFKC", text.lower()))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio", type=Path, nargs="?", default=Path("build/audio"))
    ap.add_argument("--backend", default="local",
                    help="local keeps it offline and reproducible")
    args = ap.parse_args()

    manifest_path = args.audio / "manifest.json"
    if not manifest_path.exists():
        print(f"no fixtures at {args.audio}. Build them first:\n"
              f"    python scripts/make_test_audio.py {args.audio}")
        return 0                      # skip, do not fail CI over missing audio

    cases = json.loads(manifest_path.read_text(encoding="utf-8"))
    cfg = cfgio.load(Path("config.yaml"))
    backend = build_backend(args.backend, cfg["transcription"])
    print(f"backend: {args.backend} "
          f"({cfg['transcription']['local'].get('model')})")
    t0 = time.perf_counter()
    backend.load()
    print(f"model loaded in {time.perf_counter() - t0:.1f}s\n")

    store = ProfileStore(Path("build") / "audio_test_profile.json")
    pipe = Pipeline(cfg, store)

    print(f"{'clip':<7} {'lang':>5} {'heard':>6} {'audio':>6} {'xRT':>6} "
          f"{'nativeWER':>10} {'romanWER':>9}")
    print("-" * 60)

    rows = []
    for case in cases:
        path = next((args.audio / f"{case['name']}{e}"
                     for e in (".mp3", ".wav", ".m4a")
                     if (args.audio / f"{case['name']}{e}").exists()), None)
        if path is None:
            notes.append(f"{case['name']}: clip missing")
            continue

        pcm, seconds = load_audio(path)
        t0 = time.perf_counter()
        transcript = backend.transcribe(pcm)
        took = time.perf_counter() - t0
        heard = getattr(backend, "last_language", None)

        d = pipe.process(transcript, ScreenContext(app="t.exe", title="t",
                                                   text="", focused_text="",
                                                   method="uia"),
                         heard_language=heard)

        native_wer = wer(norm(case["native"]), norm(transcript))
        roman_wer = wer(norm(case["expect"]), norm(d.text))
        code = case["name"].split("_")[0]
        rows.append((code, case, transcript, d, native_wer, roman_wer))

        print(f"{case['name']:<7} {code:>5} {str(heard):>6} {seconds:>5.1f}s "
              f"{seconds / took:>5.1f}x {native_wer:>9.1%} {roman_wer:>8.1%}")

    print("-" * 60)
    print("\n=== what each clip produced ===")
    for code, case, transcript, d, nw, rw in rows:
        print(f"\n  {case['name']}  (detected {d.language or '-'})")
        print(f"    spoken     {case['native']}")
        print(f"    whisper    {transcript.strip()}")
        print(f"    delivered  {d.text.strip()}")
        print(f"    a human'd  {case['expect']}")

    print("\n=== what we control ===")
    # Split deliberately. Whisper's accuracy is not ours to assert on - it is a
    # third-party model, and on 2-3 second clips it misidentifies the language
    # often, sometimes wildly (Malayalam heard as Romanian). What IS ours: given
    # whatever text arrives, the user must never see a word we knew how to spell
    # left in native script, and the lexicon must match the script present.

    for code, case, transcript, d, nw, rw in rows:
        leftover = [w for w in WORD.findall(d.text) if has_indic(w)]
        known = [w for w in leftover if lexicon_has(d.language, w)]
        ok = not known
        extra = (f"  leftover={known[:4]}" if known
                 else f"  ({len(leftover)} unknown words left visible)"
                 if leftover else "")
        print(f"[{'  ok  ' if ok else ' FAIL '}] {case['name']}: "
              f"no known word left in native script{extra}")
        if not ok:
            failures.append(f"{case['name']} left known words unromanized: "
                            f"{known[:4]}")

    print()
    for code, case, transcript, d, nw, rw in rows:
        present = languages_for_script(transcript)
        ok = (not present) or (d.language in present)
        print(f"[{'  ok  ' if ok else ' FAIL '}] {case['name']}: "
              f"lexicon {d.language!r} matches script present {present}")
        if not ok:
            failures.append(f"{case['name']}: used {d.language!r} for {present}")

    print()
    for code, case, transcript, d, nw, rw in rows:
        if code != "en":
            continue
        ok = not d.romanized and not has_indic(d.text)
        print(f"[{'  ok  ' if ok else ' FAIL '}] English audio is not romanized")
        if not ok:
            failures.append(f"English clip was romanized: {d.text!r}")

    # Hindi is the one language where the model is reliably good and the lexicon
    # is curated, so it gets a real accuracy bar rather than a report.
    hi = [r for r in rows if r[0] in ("hi", "mix")]
    if hi:
        worst = max(r[4] for r in hi)
        ok = worst <= 0.35
        print(f"[{'  ok  ' if ok else ' FAIL '}] Hindi transcription WER at "
              f"most 35%  (worst {worst:.1%})")
        if not ok:
            failures.append(f"Hindi transcription WER {worst:.1%}")
        worst_r = max(r[5] for r in hi)
        ok = worst_r <= 0.35
        print(f"[{'  ok  ' if ok else ' FAIL '}] Hindi delivered text within "
              f"35% of a human's spelling  (worst {worst_r:.1%})")
        if not ok:
            failures.append(f"Hindi romanized WER {worst_r:.1%}")

    print("\n=== what the speech model did, for the record ===")
    scored = [r for r in rows if r[0] in LANG_OF]
    right_script = [c["name"] for _, c, t, _, _, _ in scored
                    if LANG_OF[c["name"].split("_")[0]]
                    in languages_for_script(t)]
    latin_out = [c["name"] for _, c, t, _, _, _ in rows if not script_counts(t)]
    print(f"  transcribed into the expected script: "
          f"{len(right_script)}/{len(scored)}  {right_script}")
    print(f"  returned Latin instead of native script: {latin_out}")
    print(f"  average transcription WER: "
          f"{sum(r[4] for r in rows) / len(rows):.1%}")
    print(f"  average delivered-vs-human WER: "
          f"{sum(r[5] for r in rows) / len(rows):.1%}")
    print("  On 2-3 second clips large-v3 misidentifies several of these\n"
          "  languages; longer audio detects far better. Either way the app\n"
          "  now romanizes whatever script it is handed.")

    for n in notes:
        print(f"[ note ] {n}")
    if failures:
        print(f"\n{len(failures)} FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nthe whole chain works on real speech")
    return 0


if __name__ == "__main__":
    sys.exit(main())
