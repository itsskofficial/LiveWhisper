#!/usr/bin/env python
"""Both outputs against what a person actually typed.

Google's Dakshina corpus pairs sentences in each language's script with a
romanization a native speaker typed by hand. Speaking those sentences (edge-tts
neural voices) and running them through the app gives the one test where the
romanized output is compared with a human's own romanization, not with a
dictionary - and it covers Sinhala, which FLEURS does not have.

    native        WER and CER against the original sentence
    romanized     WER against the human romanization ("as typed"), and against
                  the human's word OR any spelling Dakshina attests for that word
                  ("acceptable") - romanization has no single right answer

Synthetic speech is cleaner than real speech, so the native numbers here are
optimistic; the romanized ones are the point. Punjabi and Sindhi have no voice.

    python tests/eval_dakshina_speech.py <dakshina_dataset_v1.0> --n 15
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from bench_asr import edit, words  # noqa: E402
from livewhisper import config as cfgio  # noqa: E402
from livewhisper.console import setup as _console  # noqa: E402
from livewhisper.pipeline import Pipeline  # noqa: E402
from livewhisper.profile import ProfileStore  # noqa: E402
from livewhisper.script.lexicon import get_lexicon  # noqa: E402

_console()
AUDIO = ROOT / "build" / "dakshina_speech"
OUT = ROOT / "tests" / "results"
VOICES = {"hi": "hi-IN-SwaraNeural", "bn": "bn-IN-TanishaaNeural", "ur": "ur-PK-UzmaNeural",
          "mr": "mr-IN-AarohiNeural", "te": "te-IN-ShrutiNeural", "ta": "ta-IN-PallaviNeural",
          "gu": "gu-IN-DhwaniNeural", "kn": "kn-IN-SapnaNeural", "ml": "ml-IN-SobhanaNeural",
          "si": "si-LK-ThiliniNeural"}


def sentences(root: Path, lang: str, n: int) -> list:
    base = root / lang / "romanized"
    native = (base / f"{lang}.romanized.rejoined.test.native.txt").read_text(encoding="utf-8").splitlines()
    roman = (base / f"{lang}.romanized.rejoined.test.roman.txt").read_text(encoding="utf-8").splitlines()
    out = []
    for nat, rom in zip(native, roman):
        k = len(nat.split())
        if 4 <= k <= 14 and len(rom.split()) == k:
            out.append((nat, rom))
        if len(out) >= n:
            break
    return out


def synthesise(lang: str, items: list) -> None:
    import edge_tts
    folder = AUDIO / lang
    folder.mkdir(parents=True, exist_ok=True)

    async def run():
        for i, (nat, _rom) in enumerate(items):
            path = folder / f"{i:02d}.mp3"
            if not path.exists():
                await edge_tts.Communicate(nat, VOICES[lang]).save(str(path))
    asyncio.run(run())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dakshina", type=Path)
    ap.add_argument("--langs", default=",".join(VOICES))
    ap.add_argument("--n", type=int, default=15)
    ap.add_argument("--routes", default="D:/models/ct2")
    ap.add_argument("--try", dest="try_", default="")
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    from e2e_app import installed_routes
    from test_audio_e2e import load_audio
    from livewhisper.transcribe import LocalBackend

    base = cfgio.load(ROOT / "config.yaml")
    local = dict(base["transcription"]["local"])
    local["models"] = installed_routes(Path(args.routes)) if args.routes else {}
    for item in [x for x in args.try_.split(",") if x]:
        lang, path = item.split("=", 1)
        if path == "none":
            local["models"].pop(lang, None)
        else:
            local["models"][lang] = {"path": path}
    local["max_extra_models"] = 1
    backend = LocalBackend(local, languages=["en"])
    backend.load()
    tmp = Path(tempfile.mkdtemp())

    rows, samples = [], []
    for lang in [x for x in args.langs.split(",") if x]:
        items = sentences(args.dakshina, lang, args.n)
        synthesise(lang, items)
        backend.languages = [lang, "en"]
        cfg = {**base, "script": {**base.get("script", {}), "language": lang},
               "output": {**base["output"], "format": {"engine": "rules"}}}
        pipe = Pipeline(cfg, ProfileStore(tmp / f"{lang}.json"))
        lex = get_lexicon(lang)
        lex.load()
        ne = nw = nce = nc = te = ae = rn = 0
        for i, (nat, rom) in enumerate(items):
            pcm, _ = load_audio(AUDIO / lang / f"{i:02d}.mp3")
            native_raw = backend.transcribe(pcm, native=True)
            heard = backend.last_language
            native_out = pipe.process(native_raw, None, force_script="native",
                                      heard_language=heard).text
            if backend._route(heard).get("latin_output"):
                roman_raw = backend.transcribe(pcm, native=False)
            else:
                roman_raw = native_raw
            roman_out = pipe.process(roman_raw, None, force_script="latin",
                                     heard_language=backend.last_language,
                                     latin_output=backend.last_latin_output).text

            ref = words(nat)
            got = words(native_out)
            ne += edit(ref, got)
            nw += len(ref)
            nce += edit(list("".join(ref)), list("".join(got)))
            nc += len("".join(ref))

            human = words(rom)
            out_r = words(roman_out)
            te += edit(human, out_r)
            natw = nat.split()
            sets = []
            for j, h in enumerate(human):
                ok = {h}
                if len(natw) == len(human):
                    ok |= {f.lower() for f in (lex._entries.get(natw[j].strip(".,!?()\"'")) or [])}
                sets.append(ok)
            ae += edit(sets, out_r, same=lambda a, w: w in a)
            rn += len(human)
            if len([s for s in samples if s["lang"] == lang]) < 4:
                samples.append({"lang": lang, "native_ref": nat, "native": native_out,
                                "typed": rom, "romanized": roman_out})
        row = {"lang": lang, "n": len(items), "native_wer": ne / nw, "native_cer": nce / nc,
               "roman_wer_typed": te / rn, "roman_wer_acceptable": ae / rn}
        rows.append(row)
        print(f"{lang}  native WER {row['native_wer']:6.1%} CER {row['native_cer']:6.1%}   "
              f"romanized WER vs typed {row['roman_wer_typed']:6.1%}, "
              f"vs acceptable {row['roman_wer_acceptable']:6.1%}", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"dakshina_speech_{args.label or 'eval'}.json").write_text(
        json.dumps({"rows": rows, "samples": samples}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
