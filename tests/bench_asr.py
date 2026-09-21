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


def _available_commit_gb() -> float | None:
    """How much more memory Windows can commit right now, in GB."""
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        st = MEMORYSTATUSEX()
        st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return None
        return st.ullAvailPageFile / 1e9
    except Exception:
        return None


# Each benchmark process commits 4-5 GB (CUDA and cuDNN reserve a great deal of
# address space). Four of them plus a conversion exhausted Windows' commit limit
# and crashed a conversion with no traceback; waiting for this much headroom
# before loading keeps them from stacking that far.
COMMIT_NEED_GB = 6.0


def _free_vram_mb() -> int | None:
    import subprocess
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.free",
                              "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout
        return int(out.strip().splitlines()[0])
    except Exception:
        return None


class _LoadGate:
    """Let one benchmark at a time load a model, and only when it will fit.

    Running every language in parallel pushed an 8 GB card to 7.9 GB in use; the
    next model to load would have died with CUDA out-of-memory and taken that
    language's result with it. The lock serializes loads, not whole runs: once a
    model is on the GPU its memory is visible to nvidia-smi and the next waiter
    can judge for itself. The OS drops the lock if a holder crashes.
    """

    def __init__(self, need_mb: int):
        self.need_mb = need_mb
        OUT.mkdir(parents=True, exist_ok=True)
        self.handle = open(OUT.parent / ".gpu-load.lock", "a+b")

    def __enter__(self):
        import msvcrt
        said = False
        while True:
            try:
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                if not said:
                    print("waiting for another benchmark to load its model...", flush=True)
                    said = True
                time.sleep(15)
                continue
            free = _free_vram_mb()
            commit = _available_commit_gb()
            if (free is None or free >= self.need_mb) and                     (commit is None or commit >= COMMIT_NEED_GB):
                return self
            # Hold nothing while waiting for memory, so a finishing run can exit.
            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            if not said:
                print(f"waiting for {self.need_mb} MB free VRAM (have {free}) and "
                      f"{COMMIT_NEED_GB:.0f} GB committable memory (have "
                      f"{commit if commit is None else round(commit, 1)})...", flush=True)
                said = True
            time.sleep(30)

    def __exit__(self, *exc):
        import msvcrt
        try:
            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        return False


class Model:
    prompt = ""
    def __init__(self, name: str, compute_type: str, beam: int, need_mb: int = 3000,
                 english_min: float = 0.0, batch: int = 0, chunk_length: int = 0,
                 timestamps: bool = False):
        from faster_whisper import BatchedInferencePipeline, WhisperModel
        self.english_min = english_min
        self.batch = batch
        self.chunk_length = chunk_length
        self.timestamps = timestamps
        with _LoadGate(need_mb):
            t0 = time.perf_counter()
            self.name = name
            self.m = WhisperModel(name, device="cuda", compute_type=compute_type)
            self.batched = BatchedInferencePipeline(model=self.m) if batch > 1 else None
            self.beam = beam
            self.load_s = time.perf_counter() - t0

    def detect(self, audio, allowed: list | None) -> tuple:
        """-> (language, its probability, {language: probability}).

        The distribution is kept so decision rules can be tested offline - for
        instance "only choose English when it clearly beats the Indic language",
        after Marathi audio detected as English came out as fluent, unrelated
        English on 7 of 40 clips.
        """
        lang, p, probs = self.m.detect_language(audio)
        if not allowed:
            top = dict(sorted(probs, key=lambda x: -x[1])[:5])
            return lang, p, top
        # Renormalise over the languages this user actually speaks.
        pool = [(l, q) for l, q in probs if l in allowed]
        if not pool:
            return lang, p, {}
        total = sum(q for _, q in pool) or 1.0
        best = max(pool, key=lambda x: x[1])
        dist = {l: q / total for l, q in pool}
        # Same rule as LocalBackend._second_guess_english: a borderline English
        # loses to the user's other language.
        others = [(l, q) for l, q in pool if l != "en"]
        if best[0] == "en" and others and dist.get("en", 0) < self.english_min:
            best = max(others, key=lambda x: x[1])
        return best[0], best[1] / total, dist

    def transcribe(self, audio, language: str | None) -> str:
        if self.batched is not None:
            segs, info = self.batched.transcribe(
                audio, batch_size=self.batch, language=language,
                beam_size=self.beam,
                chunk_length=self.chunk_length or None,
                without_timestamps=not self.timestamps,
                initial_prompt=self.prompt or None)
        else:
            segs, info = self.m.transcribe(audio, language=language,
                                           beam_size=self.beam, vad_filter=True,
                                           condition_on_previous_text=False,
                                           initial_prompt=self.prompt or None)
        return " ".join(s.text.strip() for s in segs).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("data", type=Path)
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--prompt", default="", help="initial prompt for every clip")
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
    ap.add_argument("--english-min", type=float, default=0.0,
                    help="constrained mode: choose English only above this "
                         "probability (the app uses 0.99; 0 = plain argmax)")
    ap.add_argument("--batch", type=int, default=0,
                    help="decode through the batched pipeline, as the app does. "
                         "0 = the sequential path")
    ap.add_argument("--chunk-length", type=int, default=0,
                    help="seconds of speech per decoded window in batched mode. "
                         "0 = the library default, which is the model maximum")
    ap.add_argument("--timestamps", action="store_true",
                    help="batched mode: decode with timestamp tokens, as the "
                         "sequential path does (the batched default omits them)")
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

    model = Model(args.model, args.compute, args.beam, english_min=args.english_min,
                  batch=args.batch, chunk_length=args.chunk_length,
                  timestamps=args.timestamps)
    model.prompt = args.prompt
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
            probs: dict = {}
            if args.mode == "forced":
                heard = lang
            elif args.mode == "constrained":
                allowed = (args.allowed.split(",") if args.allowed
                           else sorted({lang, "en"}))
                heard, _, probs = model.detect(audio, allowed)
            else:
                heard, _, probs = model.detect(audio, None)
            hyp = model.transcribe(audio, heard)
            wall += time.perf_counter() - t0

            lang_ok += heard == lang
            ref_w, hyp_w = words(c["reference"]), words(hyp)
            if lang == "en":
                script_ok += not has_indic(hyp)
            elif args.latin_output:
                script_ok += not has_indic(hyp)
            else:
                # Hindi/Marathi share Devanagari and Urdu/Sindhi share Arabic
                # script, and the script counter credits each character to
                # whichever language it checks first. Without this, Sindhi
                # could never score, whatever the model wrote.
                present = set(languages_for_script(hyp))
                shared = next((pair for pair in ({"hi", "mr"}, {"ur", "sd"})
                               if lang in pair), {lang})
                script_ok += bool(present & shared)

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
            # Per language, not overall: a global cap of 200 filled up after the
            # first five languages of a 12-language run and silently dropped
            # every Malayalam and Sindhi transcript.
            if sum(1 for x in samples if x["lang"] == lang) < 60:
                samples.append({"lang": lang, "heard": heard,
                                "probs": {k: round(v, 4) for k, v in probs.items()},
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
