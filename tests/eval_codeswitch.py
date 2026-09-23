#!/usr/bin/env python
"""Code-switched speech in any of the twelve languages, through the app's routing.

tests/eval_hinglish.py measures Hindi with Hindi and English as the only
choices. A Marathi speaker's app is set to Hindi, Marathi and English, and
Whisper then hears Marathi as Hindi ("tu AI system design kuthun shikla" came
back as Hindi). This runs a set such as tests/data/codeswitch_mr.json the way
that user's app would: detection restricted to --languages, the specialist
routes installed under --routes, both output scripts.

    heard right      clips detected as the language they are in
    english kept     English words that come out as the same English word
                     in the romanized text (not "aai" for "AI")
    words accepted   the language's own words romanized to a spelling people
                     use (attested in Dakshina)
    native exact     in native-script mode, the language's own words spelled
                     exactly as in the reference

    python tests/eval_codeswitch.py --lang mr --languages hi,mr,en [--split test]
        [--routes D:/models/ct2] [--try mr=D:/models/ct2/mr-indicwhisper]
        [--online] [--label name]
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from livewhisper import config as cfgio  # noqa: E402
from livewhisper.console import setup as _console  # noqa: E402
from livewhisper.pipeline import Pipeline  # noqa: E402
from livewhisper.profile import ProfileStore  # noqa: E402
from livewhisper.script.lexicon import get_lexicon  # noqa: E402
from livewhisper.script.romanize import Romanizer  # noqa: E402

_console()
OUT = ROOT / "tests" / "results"
VOICES = {"mr": ["mr-IN-AarohiNeural", "mr-IN-ManoharNeural"],
          "hi": ["hi-IN-MadhurNeural", "hi-IN-SwaraNeural"],
          "gu": ["gu-IN-DhwaniNeural", "gu-IN-NiranjanNeural"],
          "ta": ["ta-IN-PallaviNeural", "ta-IN-ValluvarNeural"],
          "te": ["te-IN-ShrutiNeural", "te-IN-MohanNeural"],
          "kn": ["kn-IN-SapnaNeural", "kn-IN-GaganNeural"],
          "ml": ["ml-IN-SobhanaNeural", "ml-IN-MidhunNeural"],
          "bn": ["bn-IN-TanishaaNeural", "bn-IN-BashkarNeural"],
          "ur": ["ur-IN-GulNeural", "ur-IN-SalmanNeural"]}
LATIN = re.compile(r"[A-Za-z']+")
NATIVE = re.compile(r"[^\sA-Za-z0-9'.,?!\u0964\u0965-]+")


def synthesise(items: list, lang: str, audio: Path) -> None:
    import edge_tts
    audio.mkdir(parents=True, exist_ok=True)

    async def run():
        for i, item in enumerate(items):
            for v, voice in enumerate(VOICES[lang]):
                path = audio / f"{i:02d}_{v}.mp3"
                if not path.exists():
                    await edge_tts.Communicate(item["said"], voice).save(str(path))
    asyncio.run(run())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="mr")
    ap.add_argument("--data", default="")
    ap.add_argument("--languages", default="hi,mr,en",
                    help="what the speaker's app detects among (transcription.languages)")
    ap.add_argument("--split", default="", help="dev or test; blank = both")
    ap.add_argument("--routes", default="D:/models/ct2")
    ap.add_argument("--try", dest="try_", default="",
                    help="route overrides, e.g. mr=D:/models/ct2/mr-indicwhisper; mr=none")
    ap.add_argument("--online", action="store_true", help="the Online backend (Groq, then here)")
    ap.add_argument("--prompt", default="",
                    help="a code-switched example given to Whisper when decoding --lang, "
                    "to keep English words in Latin letters")
    ap.add_argument("--no-fixes", action="store_true",
                    help="without the Hindi/Marathi detection threshold and the word check")
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    from e2e_app import installed_routes
    from test_audio_e2e import load_audio
    from livewhisper.transcribe import build_backend

    data = Path(args.data or ROOT / "tests" / "data" / f"codeswitch_{args.lang}.json")
    all_items = json.loads(data.read_text(encoding="utf-8"))
    synthesise(all_items, args.lang, ROOT / "build" / f"codeswitch_{args.lang}")
    picked = [(i, it) for i, it in enumerate(all_items)
              if not args.split or it.get("split") == args.split]

    base = cfgio.load(ROOT / "config.yaml")
    tcfg = json.loads(json.dumps(base["transcription"]))
    local = tcfg["local"]
    local["models"] = installed_routes(Path(args.routes)) if args.routes else {}
    for item in [x for x in args.try_.split(",") if x]:
        lang, path = item.split("=", 1)
        if path == "none":
            local["models"].pop(lang, None)
        else:
            local["models"][lang] = {"path": path}
    local["max_extra_models"] = 2
    languages = [x for x in args.languages.split(",") if x]
    backend = build_backend("auto" if args.online else "local", tcfg, languages=languages)
    if args.prompt:
        from livewhisper.transcribe import LocalBackend
        plain_prompt = LocalBackend._prompt

        def _prompt(self, language):
            base_prompt = plain_prompt(self, language)
            if language != args.lang:
                return base_prompt
            return " ".join(p for p in (args.prompt, base_prompt) if p)
        LocalBackend._prompt = _prompt
    if args.no_fixes:
        # The app before the language fixes, for a before/after on one split.
        from livewhisper.script import langcheck
        from livewhisper.transcribe import LocalBackend
        LocalBackend._second_guess_hindi = lambda self, best, pool: best
        langcheck.reconsider = lambda *a, **k: None
    if args.online and not os.environ.get("GROQ_API_KEY"):
        print("note: no GROQ_API_KEY in the environment; the app's .env is used if present")
    cfg = {**base, "script": {**base.get("script", {}), "language": args.lang},
           "output": {**base["output"], "format": {"engine": "rules"}}}
    pipe = Pipeline(cfg, ProfileStore(Path(tempfile.mkdtemp()) / "p.json"))
    lex = get_lexicon(args.lang)
    lex.load()
    plain = Romanizer(args.lang)

    heard = collections.Counter()
    eng_hit = eng_n = own_hit = own_n = nat_hit = nat_n = 0
    lost_english: collections.Counter = collections.Counter()
    samples = []
    audio_dir = ROOT / "build" / f"codeswitch_{args.lang}"
    for i, item in picked:
        english = [w.lower() for w in item["english"]]
        own = NATIVE.findall(item["said"])
        for v in range(len(VOICES[args.lang])):
            pcm, _ = load_audio(audio_dir / f"{i:02d}_{v}.mp3")
            roman_raw = backend.transcribe(pcm, native=False)
            got = getattr(backend, "last_language", None)
            heard[got] += 1
            roman = pipe.process(roman_raw, None, force_script="latin", heard_language=got,
                                 latin_output=bool(getattr(backend, "last_latin_output", False))).text
            native_raw = backend.transcribe(pcm, native=True)
            native = pipe.process(native_raw, None, force_script="native",
                                  heard_language=getattr(backend, "last_language", None)).text

            out_words = [w.lower() for w in LATIN.findall(roman)]
            for w in english:
                eng_n += 1
                if w in out_words:
                    eng_hit += 1
                else:
                    lost_english[w] += 1
            for h in own:
                ok = {f.lower() for f in (lex._entries.get(h) or [])}
                ok.add(plain.word(h)[0].lower())
                own_n += 1
                own_hit += any(o in out_words for o in ok)
            native_words = set(NATIVE.findall(native))
            for h in own:
                nat_n += 1
                nat_hit += h in native_words
            samples.append({"said": item["said"], "heard": got, "raw": roman_raw,
                            "reconsidered": getattr(getattr(backend, "local", backend),
                                                    "reconsidered", None),
                            "romanized": roman,
                            "native": native})

    result = {"lang": args.lang, "languages": languages, "split": args.split or "all",
              "prompt": args.prompt, "fixes": not args.no_fixes,
              "online": args.online, "routes": {k: v.get("path") for k, v in local["models"].items()},
              "clips": len(samples), "heard": dict(heard),
              "heard_right": heard[args.lang] / max(1, len(samples)),
              "english_kept": eng_hit / max(1, eng_n),
              "words_accepted": own_hit / max(1, own_n),
              "native_exact": nat_hit / max(1, nat_n),
              "english_lost": dict(lost_english.most_common(15)), "samples": samples}
    print(f"{args.label or 'run'}: clips {result['clips']}  heard {dict(heard)}  "
          f"heard right {result['heard_right']:.0%}  English kept {result['english_kept']:.1%}  "
          f"{args.lang} words accepted {result['words_accepted']:.1%}  "
          f"native exact {result['native_exact']:.1%}")
    print("English words most often lost:", result["english_lost"])
    for s in samples[:6]:
        print(f"  said {s['said']}  [{s['heard']}]\n   rom {s['romanized']}\n   nat {s['native']}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"codeswitch_{args.lang}_{args.label or 'eval'}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
