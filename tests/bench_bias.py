#!/usr/bin/env python
"""Does telling the decoder what is on screen help, and what does it cost?

Biasing is the feature with the most obvious upside and the least obvious
downside. Names it is told about come out right; names it is told about that
were never spoken can be written down anyway, and a prompt of unrelated words
can drag the whole transcript. Both have to be measured, so each clip is
decoded three times:

    nothing        as the app used to
    the right names  the proper nouns in what was actually said - the screen
                     you are replying to, in the good case
    the wrong names  proper nouns from other recordings entirely - the screen
                     having nothing to do with your sentence, which is the
                     common case and the one that can do harm

Reported per language: word error rate, and how many of the target names
survived into the transcript.

    python tests/bench_bias.py build/fleurs --langs en,hi --n 30
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bench_asr import edit, load_audio, words  # noqa: E402
from livewhisper.console import setup as _console  # noqa: E402

_console()
OUT = Path(__file__).resolve().parent / "results"

# A proper noun for this purpose: capitalised, not opening the sentence, not a
# word the model would know anyway.
_NAME = re.compile(r"(?<!^)(?<![.!?]\s)\b([A-Z][a-z]{2,})\b")
_SKIP = {"The", "This", "That", "They", "There", "These", "Those", "When",
         "While", "What", "Where", "Which", "With", "Although", "However",
         "Because", "After", "Before", "During", "Since", "Many", "Most",
         "Some", "One", "Two", "Three", "First", "Second", "Third", "In",
         "It", "If", "As", "At", "But", "For", "And", "All", "New"}


def names_in(text: str) -> list:
    return [w for w in dict.fromkeys(_NAME.findall(text)) if w not in _SKIP]


def kept(hypothesis: str, targets: list) -> tuple:
    """How many target names appear in the transcript, case-insensitively."""
    low = hypothesis.lower()
    return sum(1 for t in targets if t.lower() in low), len(targets)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("data", type=Path)
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--langs", default="en")
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--compute", default="int8_float16")
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--chunk-length", type=int, default=10)
    args = ap.parse_args()

    manifest = json.loads((args.data / "manifest.json").read_text(encoding="utf-8"))

    from faster_whisper import BatchedInferencePipeline, WhisperModel

    model = WhisperModel(args.model, device="cuda", compute_type=args.compute)
    batched = BatchedInferencePipeline(model=model) if args.batch > 1 else None

    def decode(audio, language: str, hotwords: str = "") -> str:
        if batched is not None:
            segs, _ = batched.transcribe(audio, batch_size=args.batch,
                                         language=language, beam_size=5,
                                         chunk_length=args.chunk_length or None,
                                         hotwords=hotwords or None)
        else:
            segs, _ = model.transcribe(audio, language=language, beam_size=5,
                                       vad_filter=True,
                                       condition_on_previous_text=False,
                                       hotwords=hotwords or None)
        return " ".join(s.text.strip() for s in segs).strip()

    rows = []
    for lang in [x for x in args.langs.split(",") if x]:
        clips = [c for c in manifest if c["lang"] == lang][: args.n]
        # English names are the ones a Latin-script prompt can bias toward;
        # for other languages the same trick has to work on what the reference
        # writes in Latin at all, so clips without any are skipped.
        with_names = [(c, names_in(c["reference"])) for c in clips]
        with_names = [(c, n) for c, n in with_names if n]
        if not with_names:
            print(f"{lang}: no clips with proper nouns in the reference; skipped")
            continue

        pool = [n for _c, ns in with_names for n in ns]
        totals = {k: [0, 0, 0, 0] for k in ("none", "right", "wrong")}  # e,n,kept,tgt
        for i, (c, targets) in enumerate(with_names):
            audio = load_audio(args.data / c["name"])
            ref = words(c["reference"])
            # Names from a different clip, so the screen is genuinely unrelated.
            other = [n for n in pool if n not in targets]
            wrong = ", ".join(other[(i * 7) % max(1, len(other)):][:8])
            for key, hot in (("none", ""), ("right", ", ".join(targets)),
                             ("wrong", wrong)):
                hyp = decode(audio, lang, hot)
                k, t = kept(hyp, targets)
                totals[key][0] += edit(ref, words(hyp))
                totals[key][1] += len(ref)
                totals[key][2] += k
                totals[key][3] += t

        row = {"lang": lang, "clips": len(with_names)}
        for key, (e, n, k, t) in totals.items():
            row[f"wer_{key}"] = e / n
            row[f"names_{key}"] = k / t if t else 0.0
        rows.append(row)
        print(f"{lang}: {row['clips']} clips with names\n"
              f"   nothing on screen   WER {row['wer_none']:.1%}   "
              f"names kept {row['names_none']:.0%}\n"
              f"   the right names     WER {row['wer_right']:.1%}   "
              f"names kept {row['names_right']:.0%}\n"
              f"   unrelated names     WER {row['wer_wrong']:.1%}   "
              f"names kept {row['names_wrong']:.0%}", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "bias.json"
    path.write_text(json.dumps({"model": args.model, "rows": rows}, indent=1),
                    encoding="utf-8")
    print(f"\nwritten to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
