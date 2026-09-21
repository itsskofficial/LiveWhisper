#!/usr/bin/env python
"""Code-switched Hindi-English, the way people actually talk in chat.

FLEURS is read news in formal Hindi. Real dictation sounds like "pull request
review kar liya, ab merge kar do": Hindi grammar with English nouns and verbs.
tests/data/hinglish_eval.json holds 40 such sentences; each is synthesised with
two neural Hindi voices (edge-tts) and run through the app's own backend and
pipeline, in both output modes.

    english kept     English words spoken in the sentence that come out as the
                     same English word in the romanized text. The worst failure
                     for a Hinglish user is "meeting" coming back as "meting" or
                     "miting" because it went through Devanagari first.
    hindi accepted   Hindi words whose romanization is a spelling attested in
                     Dakshina - one people actually use.
    native exact     in native-script mode, Hindi words spelled exactly as in
                     the reference Devanagari.

    python tests/eval_hinglish.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
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
DATA = ROOT / "tests" / "data" / "hinglish_eval.json"
AUDIO = ROOT / "build" / "hinglish"
OUT = ROOT / "tests" / "results"
VOICES = ["hi-IN-MadhurNeural", "hi-IN-SwaraNeural"]
DEVA = re.compile(r"[\u0900-\u097F]+")
TOKEN = re.compile(r"[\u0900-\u097F]+|[A-Za-z']+")
WORD = re.compile(r"\w+", re.UNICODE)


def synthesise(items: list) -> None:
    import edge_tts
    AUDIO.mkdir(parents=True, exist_ok=True)

    async def run():
        for i, item in enumerate(items):
            for v, voice in enumerate(VOICES):
                path = AUDIO / f"{i:02d}_{v}.mp3"
                if not path.exists():
                    await edge_tts.Communicate(item["said"], voice).save(str(path))
    asyncio.run(run())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--routes", default="D:/models/ct2")
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    from e2e_app import installed_routes
    from test_audio_e2e import load_audio
    from livewhisper.transcribe import LocalBackend

    items = json.loads(DATA.read_text(encoding="utf-8"))
    synthesise(items)
    base = cfgio.load(ROOT / "config.yaml")
    local = dict(base["transcription"]["local"])
    local["models"] = installed_routes(Path(args.routes)) if args.routes else {}
    local["max_extra_models"] = 2
    backend = LocalBackend(local, languages=["hi", "en"])
    backend.load()
    cfg = {**base, "script": {**base.get("script", {}), "language": "hi"},
           "output": {**base["output"], "format": {"engine": "rules"}}}
    pipe = Pipeline(cfg, ProfileStore(Path(tempfile.mkdtemp()) / "p.json"))
    lex = get_lexicon("hi")
    lex.load()
    plain = Romanizer("hi")

    eng_hit = eng_n = hin_hit = hin_n = nat_hit = nat_n = 0
    lost_english: dict = {}
    samples = []
    for i, item in enumerate(items):
        english = [w.lower() for w in item["english"]]
        hindi = DEVA.findall(item["said"])
        for v in range(len(VOICES)):
            pcm, _ = load_audio(AUDIO / f"{i:02d}_{v}.mp3")
            roman_raw = backend.transcribe(pcm, native=False)
            roman = pipe.process(roman_raw, None, force_script="latin",
                                 heard_language=backend.last_language,
                                 latin_output=backend.last_latin_output).text
            native_raw = backend.transcribe(pcm, native=True)
            native = pipe.process(native_raw, None, force_script="native",
                                  heard_language=backend.last_language).text

            out_words = [w.lower() for w in WORD.findall(roman)]
            for w in english:
                eng_n += 1
                if w in out_words:
                    eng_hit += 1
                else:
                    lost_english[w] = lost_english.get(w, 0) + 1
            for h in hindi:
                ok = {f.lower() for f in (lex._entries.get(h) or [])}
                ok.add(plain.word(h)[0].lower())
                hin_n += 1
                hin_hit += any(o in out_words for o in ok)
            native_words = set(DEVA.findall(native))
            for h in hindi:
                nat_n += 1
                nat_hit += h in native_words
            if len(samples) < 16:
                samples.append({"said": item["said"], "romanized": roman, "native": native})

    result = {"english_kept": eng_hit / eng_n, "hindi_accepted": hin_hit / hin_n,
              "native_exact": nat_hit / nat_n, "clips": len(items) * len(VOICES),
              "english_lost": dict(sorted(lost_english.items(), key=lambda kv: -kv[1])[:15]),
              "samples": samples}
    print(f"clips {result['clips']}: English words kept {result['english_kept']:.1%}, "
          f"Hindi words in an accepted spelling {result['hindi_accepted']:.1%}, "
          f"native Hindi spelled exactly {result['native_exact']:.1%}")
    print("English words most often lost:", result["english_lost"])
    for s in samples[:6]:
        print(f"  said {s['said']}\n   rom {s['romanized']}\n   nat {s['native']}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"hinglish_{args.label or 'eval'}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
