#!/usr/bin/env python
"""Score a Hinglish model's saved transcripts the way the app delivers them.

bench_asr.py scores a latin_output model on its raw text. The app never pastes
raw text from those models: pipeline.py runs respell() over it first, which
shortens textbook long vowels (saamaan -> samaan) to spellings people type. So
the raw number understates every Hinglish model by several points, and
comparing it with large-v3's delivered number compares unlike things.

This reads the transcripts a bench_asr run saved and scores them both ways.

    python tests/rescore_delivered.py tests/results/asr_prime-seq.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bench_asr import accepted_spellings, edit, words  # noqa: E402
from livewhisper.console import setup as _console  # noqa: E402
from livewhisper.script.respell import respell  # noqa: E402

_console()


def score(samples: list, fix) -> float:
    e = n = 0
    for s in samples:
        ok = accepted_spellings(s["lang"], words(s["ref"]))
        e += edit(ok, words(fix(s["hyp"], s["lang"])), same=lambda a, w: w in a)
        n += len(ok)
    return e / n if n else float("nan")


def main() -> int:
    for path in sys.argv[1:]:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        samples = data["samples"]
        raw = score(samples, lambda text, lang: text)
        fixed = score(samples, lambda text, lang: respell(text, lang))
        print(f"{Path(path).name:<36} n={len(samples):<3} raw {raw:.1%}  "
              f"as delivered {fixed:.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
