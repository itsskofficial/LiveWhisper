#!/usr/bin/env python
"""Both outputs, every language, the way the app produces them.

A speaker of any of the twelve languages can ask for their words in the
language's own script, or romanized the way they type it. This measures both,
through the same code the app runs: the backend with the specialists that are
installed, restricted detection over {language, English}, then the pipeline
with the script forced.

    native      the text in its own script, against the FLEURS reference
                word error (WER) and character error (CER) - CER is the fair
                measure of spelling in scripts where one word is long
    romanized   the romanized text against every spelling of each reference word
                attested in Google's Dakshina lexicons ("delivered WER"), and
                the share of words spelled the way people most commonly spell
                them ("usual spelling")
    leaks       dictations where native script survived into romanized output

    python tests/eval_outputs.py build/fleurs --n 20
    python tests/eval_outputs.py build/fleurs-dev --langs hi,bn --label dev

Formatting uses the rules, not the model: formatting never changes words, and
this measures words.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from bench_asr import accepted_spellings, edit, load_audio, words  # noqa: E402
from livewhisper import config as cfgio  # noqa: E402
from livewhisper.console import setup as _console  # noqa: E402
from livewhisper.pipeline import Pipeline  # noqa: E402
from livewhisper.profile import ProfileStore  # noqa: E402
from livewhisper.script.lexicon import get_lexicon  # noqa: E402

_console()
OUT = ROOT / "tests" / "results"
NATIVE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u0900-\u0DFF]")
ALL = ["hi", "bn", "ur", "pa", "mr", "te", "ta", "gu", "kn", "ml", "sd", "si"]


def usual_share(lang: str, reference: str, got: str) -> float:
    """Share of reference words whose most common spelling appears in the output."""
    lex = get_lexicon(lang)
    lex.load()
    ref = words(reference)
    tops = [lex.lookup(w) for w in ref]
    tops = [t.lower() for t in tops if t]
    if not tops:
        return float("nan")
    out = set(words(got))
    return sum(t in out for t in tops) / len(tops)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("data", type=Path)
    ap.add_argument("--langs", default=",".join(ALL))
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--routes", default="D:/models/ct2",
                    help="folder of converted specialists; '' for large-v3 alone")
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    from e2e_app import installed_routes
    from livewhisper.transcribe import LocalBackend

    manifest = json.loads((args.data / "manifest.json").read_text(encoding="utf-8"))
    base = cfgio.load(ROOT / "config.yaml")
    local = dict(base["transcription"]["local"])
    local["models"] = installed_routes(Path(args.routes)) if args.routes else {}
    local["max_extra_models"] = 1
    backend = LocalBackend(local, languages=["en"])
    backend.load()
    backend.warm()

    tmp = Path(tempfile.mkdtemp())
    rows, samples = [], []
    for lang in [x for x in args.langs.split(",") if x]:
        clips = [c for c in manifest if c["lang"] == lang][: args.n]
        if not clips:
            print(f"{lang}: no clips")
            continue
        backend.languages = [lang, "en"]
        cfg = {**base, "script": {**base.get("script", {}), "language": lang},
               "output": {**base["output"], "format": {"engine": "rules"}}}
        pipe = Pipeline(cfg, ProfileStore(tmp / f"{lang}.json"))
        acc = {"n_e": 0, "n_c": 0, "n_w": 0, "n_ch": 0, "r_e": 0, "r_n": 0,
               "usual": [], "leaks": 0, "heard_ok": 0, "secs": 0.0, "audio": 0.0}
        for c in clips:
            audio = load_audio(args.data / c["name"])
            t0 = time.perf_counter()
            native_text = backend.transcribe(audio, native=True)
            heard, latin = backend.last_language, backend.last_latin_output
            route = backend._route(heard)
            if route.get("latin_output"):
                roman_text = backend.transcribe(audio, native=False)
                heard_r, latin_r = backend.last_language, backend.last_latin_output
            else:
                roman_text, heard_r, latin_r = native_text, heard, latin
            acc["secs"] += time.perf_counter() - t0
            acc["audio"] += len(audio) / 16000
            acc["heard_ok"] += heard == lang

            native_out = pipe.process(native_text, None, force_script="native",
                                      heard_language=heard).text
            roman_out = pipe.process(roman_text, None, force_script="latin",
                                     heard_language=heard_r, latin_output=latin_r).text

            ref = words(c["reference"])
            got_n = words(native_out)
            acc["n_e"] += edit(ref, got_n)
            acc["n_w"] += len(ref)
            ref_c, got_c = list("".join(ref)), list("".join(got_n))
            acc["n_c"] += edit(ref_c, got_c)
            acc["n_ch"] += len(ref_c)
            ok = accepted_spellings(lang, ref)
            acc["r_e"] += edit(ok, words(roman_out), same=lambda a, w: w in a)
            acc["r_n"] += len(ok)
            u = usual_share(lang, c["reference"], roman_out)
            if u == u:
                acc["usual"].append(u)
            leaked = bool(NATIVE.search(roman_out))
            acc["leaks"] += leaked
            if len([s for s in samples if s["lang"] == lang]) < 8:
                samples.append({"lang": lang, "reference": c["reference"],
                                "native": native_out, "romanized": roman_out,
                                "heard": heard})
        k = len(clips)
        row = {"lang": lang, "n": k,
               "native_wer": acc["n_e"] / acc["n_w"], "native_cer": acc["n_c"] / acc["n_ch"],
               "roman_wer": acc["r_e"] / acc["r_n"],
               "usual_spelling": statistics.mean(acc["usual"]) if acc["usual"] else None,
               "leaks": acc["leaks"], "language_ok": acc["heard_ok"] / k,
               "xrt": acc["audio"] / acc["secs"] if acc["secs"] else 0,
               "route": Path(backend._route(lang).get("path", "large-v3")).name}
        rows.append(row)
        print(f"{lang}  native WER {row['native_wer']:6.1%}  CER {row['native_cer']:6.1%}   "
              f"romanized WER {row['roman_wer']:6.1%}  usual spelling "
              f"{(row['usual_spelling'] or 0):5.1%}  leaks {row['leaks']}  "
              f"lang ok {row['language_ok']:4.0%}  [{row['route']}]", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    label = args.label or args.data.name
    (OUT / f"outputs_{label}.json").write_text(
        json.dumps({"rows": rows, "samples": samples}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
