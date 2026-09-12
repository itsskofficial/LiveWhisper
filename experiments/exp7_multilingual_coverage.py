#!/usr/bin/env python
"""Experiment 7: does the Hindi approach generalise to the other eleven?

exp2 measured 92.3% lexicon coverage for Hindi on real Whisper output. The whole
multi-language expansion rests on that number holding for Bengali, Tamil, Telugu
and the rest. If coverage collapses outside Hindi, shipping twelve languages
would be shipping eleven bad experiences.

Measured two ways per language:
  held-out    - words from Dakshina's own test split, which the shipped lexicon
                (built from all splits) should mostly contain
  frequency   - the most common words of the language, which is what real
                speech is actually made of

    python experiments/exp7_multilingual_coverage.py <dakshina-root>
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper.script.languages import CODES, LANGUAGES  # noqa: E402
from livewhisper.script.lexicon import get_lexicon  # noqa: E402

OUT = Path("experiments/results")


def load_words(root: Path, lang: str, split: str) -> list:
    """Native-script words from a Dakshina split."""
    path = root / lang / "lexicons" / f"{lang}.translit.sampled.{split}.tsv"
    if not path.exists():
        return []
    words = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if parts and parts[0].strip():
                words.append(parts[0].strip())
    return words


def load_corpus_words(root: Path, lang: str, limit: int = 4000) -> list:
    """Word tokens from running text, weighted by frequency as speech would be."""
    for name in (f"{lang}.romanized.rejoined.dev.native.txt",
                 f"{lang}.romanized.rejoined.test.native.txt"):
        path = root / lang / "romanized" / name
        if path.exists():
            break
    else:
        return []
    from livewhisper.script.languages import run_pattern
    pat = run_pattern(lang)
    counts: Counter = Counter()
    with open(path, encoding="utf-8") as f:
        for line in f:
            counts.update(pat.findall(line))
            if sum(counts.values()) > limit * 12:
                break
    # Expand back into a frequency-weighted list, so common words count more.
    out = []
    for w, n in counts.most_common(limit):
        out.extend([w] * min(n, 20))
    return out


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("dakshina_dataset_v1.0")
    if not root.exists():
        print(f"dakshina root not found: {root}")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)

    lines = ["# Experiment 7 - does the approach hold across twelve languages?\n\n",
             "Lexicon coverage measured per language. `held-out` uses Dakshina's "
             "test split; `in running text` weights by how often words actually "
             "occur, which is closer to what speech contains.\n\n",
             "| language | | speakers | lexicon | held-out | in running text |\n",
             "|---|---|---|---|---|---|\n"]

    print(f"{'lang':<12} {'speakers':>9} {'lexicon':>9} {'held-out':>9} "
          f"{'running text':>13}")
    print("-" * 58)

    totals = []
    for code in CODES:
        lang = LANGUAGES[code]
        lex = get_lexicon(code)
        if not len(lex):
            print(f"{lang.name:<12} {'-':>9}  no lexicon")
            continue

        held = load_words(root, code, "test")
        held_cov = (sum(1 for w in held if lex.lookup(w)) / len(held) * 100
                    if held else 0.0)

        corpus = load_corpus_words(root, code)
        corp_cov = (sum(1 for w in corpus if lex.lookup(w)) / len(corpus) * 100
                    if corpus else None)

        totals.append((code, held_cov, corp_cov))
        corp_s = f"{corp_cov:.1f}%" if corp_cov is not None else "n/a"
        print(f"{lang.name:<12} {lang.speakers_m:>8}M {len(lex):>9,} "
              f"{held_cov:>8.1f}% {corp_s:>13}")
        lines.append(f"| {lang.name} | {lang.nickname} | {lang.speakers_m}M | "
                     f"{len(lex):,} | {held_cov:.1f}% | {corp_s} |\n")

    print("-" * 58)
    if totals:
        avg_held = sum(h for _, h, _ in totals) / len(totals)
        corp_vals = [c for _, _, c in totals if c is not None]
        avg_corp = sum(corp_vals) / len(corp_vals) if corp_vals else 0
        reach = sum(LANGUAGES[c].speakers_m for c, _, _ in totals)
        print(f"{'AVERAGE':<12} {reach:>8}M {'':>9} {avg_held:>8.1f}% "
              f"{avg_corp:>12.1f}%")
        lines.append(f"\n**Average across {len(totals)} languages: "
                     f"{avg_held:.1f}% held-out, {avg_corp:.1f}% in running "
                     f"text. Combined reach ~{reach/1000:.1f} billion "
                     f"speakers.**\n")

    (OUT / "exp7_multilingual_coverage.md").write_text("".join(lines),
                                                       encoding="utf-8")
    print(f"\nwrote {OUT / 'exp7_multilingual_coverage.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
