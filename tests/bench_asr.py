#!/usr/bin/env python
"""Which speech model should transcribe which language? Measured on real people.

Runs FLEURS clips (people reading aloud, see scripts/fetch_fleurs.py) through
one or more speech models and scores three things:

  WER / CER      against the reference, in the native script. CER matters for
                 Dravidian languages, where one "word" can be a whole clause and
                 a single wrong suffix fails the entire word.
  script ok      share of clips transcribed in the right script at all - the
                 failure that sends Malayalam out as Romanian.
  delivered      what the user actually receives: the transcript after
                 romanization, scored against every accepted Latin spelling of
                 each reference word. This is the only column that can compare
                 a normal Whisper model with one that emits Hinglish directly.

Language handling is the other axis, because on short clips it matters more
than the model:

  auto          Whisper picks from all 99 languages
  constrained   Whisper picks, but only among the languages you speak
  forced        the language is known

    python tests/bench_asr.py build/fleurs --model large-v3 --mode constrained
    python tests/bench_asr.py build/fleurs --model D:/models/ct2/tamil --langs ta --mode forced
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper.console import setup as _console  # noqa: E402
from livewhisper.script.languages import (  # noqa: E402
    WORD, has_indic, languages_for_script,
)
from livewhisper.script.lexicon import get_lexicon  # noqa: E402
from livewhisper.script.romanize import Romanizer  # noqa: E402

_console()

OUT = Path("tests/results")


def words(text: str) -> list:
    return WORD.findall(unicodedata.normalize("NFKC", text).lower())


def edit(ref: list, hyp: list, same=lambda a, b: a == b) -> int:
    n, m = len(ref), len(hyp)
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        cur = [i] + [0] * m
        for j in range(1, m + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1,
                         prev[j - 1] + (0 if same(ref[i - 1], hyp[j - 1]) else 1))
        prev = cur
    return prev[m]


def accepted_spellings(lang: str, ref_words: list) -> list:
    """For each native reference word, every Latin spelling we would accept."""
    lex = get_lexicon(lang)
    r = Romanizer(lang)
    out = []
    for w in ref_words:
        forms = {f.lower() for f in lex.variants(w)}
        top = lex.lookup(w)
        if top:
            forms.add(top.lower())
        forms.add(r.word(w)[0].lower())
        out.append(forms)
    return out


def load_audio(path: Path):
    import soundfile as sf
    import numpy as np
    audio, rate = sf.read(str(path), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if rate != 16000:
        import soxr
        audio = soxr.resample(audio, rate, 16000)
    return np.ascontiguousarray(audio, dtype="float32")


class Model:
    def __init__(self, name: str, compute_type: str, beam: int):
        from faster_whisper import WhisperModel
        t0 = time.perf_counter()
        self.name = name
        self.m = WhisperModel(name, device="cuda", compute_type=compute_type)
        self.beam = beam
        self.load_s = time.perf_counter() - t0

    def detect(self, audio, allowed: list | None) -> tuple:
        lang, p, probs = self.m.detect_language(audio)
        if not allowed:
            return lang, p
        # Renormalise over the languages this user actually speaks.
        pool = [(l, q) for l, q in probs if l in allowed]
        if not pool:
            return lang, p
        total = sum(q for _, q in pool) or 1.0
        best = max(pool, key=lambda x: x[1])
        return best[0], best[1] / total

    def transcribe(self, audio, language: str | None) -> str:
        segs, info = self.m.transcribe(audio, language=language,
                                       beam_size=self.beam, vad_filter=True,
                                       condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segs).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("data", type=Path)
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--label", default=None)
    ap.add_argument("--mode", choices=("auto", "constrained", "forced"),
                    default="constrained")
    ap.add_argument("--allowed", default="",
                    help="languages the speaker uses, for constrained mode. "
                         "Default: the clip's own language plus English - the "
                         "setup a real single-language user has")
    ap.add_argument("--langs", default="", help="only these clip languages")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--compute", default="int8_float16")
    ap.add_argument("--beam", type=int, default=5)
    ap.add_argument("--latin-output", action="store_true",
                    help="model emits romanized text directly (Hinglish models)")
    args = ap.parse_args()

    manifest = json.loads((args.data / "manifest.json").read_text(encoding="utf-8"))
    only = set(filter(None, args.langs.split(",")))
    by_lang: dict = {}
    for c in manifest:
        if only and c["lang"] not in only:
            continue
        by_lang.setdefault(c["lang"], [])
        if len(by_lang[c["lang"]]) < args.n:
            by_lang[c["lang"]].append(c)

    model = Model(args.model, args.compute, args.beam)
    label = args.label or f"{Path(args.model).name}-{args.mode}"
    print(f"{label}: loaded in {model.load_s:.0f}s")
    print(f"{'lang':<5} {'n':>3} {'WER':>6} {'CER':>6} {'lang ok':>8} "
          f"{'script ok':>9} {'delivered':>10} {'xRT':>6}")
    print("-" * 62)

    rows, samples = [], []
    for lang, clips in by_lang.items():
        e_w = n_w = e_c = n_c = e_d = n_d = 0
        lang_ok = script_ok = 0
        audio_s = wall = 0.0
        for c in clips:
            audio = load_audio(args.data / c["name"])
            audio_s += len(audio) / 16000
            t0 = time.perf_counter()
            if args.mode == "forced":
                heard = lang
            elif args.mode == "constrained":
                allowed = (args.allowed.split(",") if args.allowed
                           else sorted({lang, "en"}))
                heard, _ = model.detect(audio, allowed)
            else:
                heard, _ = model.detect(audio, None)
            hyp = model.transcribe(audio, heard)
            wall += time.perf_counter() - t0

            lang_ok += heard == lang
            ref_w, hyp_w = words(c["reference"]), words(hyp)
            if lang == "en":
                script_ok += not has_indic(hyp)
            elif args.latin_output:
                script_ok += not has_indic(hyp)
            else:
                script_ok += lang in languages_for_script(hyp) or (
                    lang in ("hi", "mr") and bool(
                        set(languages_for_script(hyp)) & {"hi", "mr"}))

            if not args.latin_output:
                e_w += edit(ref_w, hyp_w)
                n_w += len(ref_w)
                ref_c = list("".join(ref_w))
                e_c += edit(ref_c, list("".join(hyp_w)))
                n_c += len(ref_c)

            # Delivered: what reaches the user after romanization.
            if lang != "en":
                if args.latin_output or not has_indic(hyp):
                    out_w = hyp_w
                else:
                    target = next(iter(languages_for_script(hyp)), lang)
                    out_w = words(Romanizer(target).text(hyp))
                ok_sets = accepted_spellings(lang, ref_w)
                e_d += edit(ok_sets, out_w, same=lambda s, w: w in s)
                n_d += len(ok_sets)
            if len(samples) < 200:
                samples.append({"lang": lang, "heard": heard,
                                "ref": c["reference"], "hyp": hyp})

        k = len(clips)
        wer = e_w / n_w if n_w else float("nan")
        cer = e_c / n_c if n_c else float("nan")
        dlv = e_d / n_d if n_d else float("nan")
        rows.append({"lang": lang, "n": k, "wer": wer, "cer": cer,
                     "lang_ok": lang_ok / k, "script_ok": script_ok / k,
                     "delivered_wer": dlv, "xrt": audio_s / wall if wall else 0})
        print(f"{lang:<5} {k:>3} {wer:>6.1%} {cer:>6.1%} {lang_ok / k:>8.0%} "
              f"{script_ok / k:>9.0%} {dlv:>10.1%} {audio_s / wall:>5.1f}x",
              flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"asr_{label}.json").write_text(
        json.dumps({"model": args.model, "mode": args.mode, "rows": rows,
                    "samples": samples}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"\nwrote {OUT / f'asr_{label}.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
