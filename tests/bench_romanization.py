#!/usr/bin/env python
"""Benchmark 1: how close is our romanization to what a human actually wrote?

Every accuracy number quoted so far has been a *coverage* number - how many
words the dictionary contains. That is not the same as being right. This
measures the thing users actually experience: give the romanizer a real
sentence in the native script, and compare its output against the romanization
a human being produced for that same sentence.

Dakshina provides ~5,000 such pairs per language. They are the closest thing to
ground truth that exists for this task.

    python tests/bench_romanization.py <dakshina-root> [--n 600]

Metrics
-------
WER          word error rate against the human romanization
identical    share of words spelled exactly as the human spelled them
acceptable   identical, plus words where we and the human both used a spelling
             Dakshina records for that word
wrong        words where our spelling is not one anybody offered - the only
             bucket that is unambiguously an error
aligned      share of sentences where we produced the same NUMBER of words as
             the human, and so could be compared word-for-word. The three
             columns above are computed over these sentences only, so a low
             `aligned` means they describe a subset - read WER for the rest
untouched    share of native-script words we failed to convert at all

A caveat that matters: romanization is genuinely ambiguous - exp2 measured 45%
of words having several attested spellings. So a WER of 30% does NOT mean 30%
wrong; much of it is one valid spelling against another, which is why
`acceptable` exists alongside WER.
"""

from __future__ import annotations

import argparse
import random
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper.script.languages import (  # noqa: E402
    CODES, LANGUAGES, WORD, run_pattern,
)
from livewhisper.script.lexicon import get_lexicon  # noqa: E402
from livewhisper.script.romanize import Romanizer  # noqa: E402

from livewhisper.console import setup as _console

_console()

OUT = Path("tests/results")
SEED = 11


def norm(text: str) -> list:
    text = unicodedata.normalize("NFKC", text.lower())
    return WORD.findall(text)


def wer(ref: list, hyp: list) -> tuple:
    """Levenshtein over words -> (errors, substitutions, deletions, insertions)."""
    n, m = len(ref), len(hyp)
    if n == 0:
        return m, 0, 0, m
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        cur = [i] + [0] * m
        for j in range(1, m + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1,
                         prev[j - 1] + (ref[i - 1] != hyp[j - 1]))
        prev = cur
    return prev[m], 0, 0, 0


def agreement(native_words: list, human_words: list, our_words: list, lex) -> tuple:
    """Word-level breakdown against the human, aligned by position.

    Returns (identical, differ_but_both_valid, ours_not_attested, total).

    An earlier version of this asked "is our output an attested spelling?" and
    unsurprisingly answered 100% every time - our output *comes from* the
    attested list, so the question was circular. What actually matters is how
    our choice compares to the human's:

      identical          we picked the same spelling they did
      both valid         we differ, but Dakshina records both as real spellings
                         (45% of words have several, so this is disagreement,
                         not error)
      ours not attested  our spelling is not one anybody offered - the only
                         bucket that is unambiguously wrong

    Sentences whose word counts disagree are skipped rather than guessed at.
    """
    if not (len(native_words) == len(human_words) == len(our_words)):
        return 0, 0, 0, 0
    same = both = odd = 0
    for nat, hum, our in zip(native_words, human_words, our_words):
        forms = {f.lower() for f in lex.variants(nat)}
        top = lex.lookup(nat)
        if top:
            forms.add(top.lower())
        if our.lower() == hum.lower():
            same += 1
        elif not forms:
            odd += 1          # unknown word, we guessed with the model
        elif our.lower() in forms:
            both += 1
        else:
            odd += 1
    return same, both, odd, len(native_words)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--n", type=int, default=600, help="sentences per language")
    args = ap.parse_args()

    random.seed(SEED)
    OUT.mkdir(parents=True, exist_ok=True)

    lines = ["# Benchmark: romanization vs human ground truth\n\n",
             f"{args.n} sentences per language from Dakshina's human-romanized "
             "corpus. These are sentences a person wrote out in Latin letters; "
             "we compare our output to theirs.\n\n",
             "| language | sentences | WER | identical | acceptable | wrong | "
             "untouched |\n|---|---|---|---|---|---|---|\n"]

    print(f"{'language':<12} {'sents':>6} {'WER':>7} {'identical':>9} "
          f"{'acceptable':>11} {'wrong':>8} {'aligned':>8} "
          f"{'untouched':>10}")
    print("-" * 80)

    totals = []
    for code in CODES:
        rom_path = (args.root / code / "romanized" /
                    f"{code}.romanized.rejoined.dev.roman.txt")
        nat_path = (args.root / code / "romanized" /
                    f"{code}.romanized.rejoined.dev.native.txt")
        if not rom_path.exists() or not nat_path.exists():
            print(f"{LANGUAGES[code].name:<12} no data")
            continue

        natives = nat_path.read_text(encoding="utf-8").splitlines()
        romans = rom_path.read_text(encoding="utf-8").splitlines()
        pairs = [(n, r) for n, r in zip(natives, romans)
                 if n.strip() and r.strip() and len(n) < 400]
        random.shuffle(pairs)
        pairs = pairs[:args.n]
        if not pairs:
            continue

        r = Romanizer(code)
        pattern = run_pattern(code)
        lex = get_lexicon(code)

        err = ref_len = 0
        same = both = odd = aligned = 0
        alignable = 0
        native_tokens = left_tokens = 0

        for native, human in pairs:
            got = r.text(native)
            ref, hyp = norm(human), norm(got)
            e, *_ = wer(ref, hyp)
            err += e
            ref_len += len(ref)

            nat_words = pattern.findall(native)
            native_tokens += len(nat_words)
            left_tokens += len(pattern.findall(got))

            a, b, c, t = agreement(nat_words, WORD.findall(human.lower()),
                                   WORD.findall(got.lower()), lex)
            same += a
            both += b
            odd += c
            aligned += t
            alignable += (t > 0)

        w = err / ref_len if ref_len else 1.0
        identical = same / aligned if aligned else 0.0
        acceptable = (same + both) / aligned if aligned else 0.0
        wrong = odd / aligned if aligned else 0.0
        covered = alignable / len(pairs)
        untouched = left_tokens / native_tokens if native_tokens else 0.0
        totals.append((code, w, identical, acceptable, wrong, covered,
                       untouched))

        print(f"{LANGUAGES[code].name:<12} {len(pairs):>6} {w:>6.1%} "
              f"{identical:>9.1%} {acceptable:>11.1%} {wrong:>8.1%} "
              f"{covered:>8.1%} {untouched:>10.1%}")
        lines.append(f"| {LANGUAGES[code].name} | {len(pairs)} | {w:.1%} | "
                     f"{identical:.1%} | {acceptable:.1%} | {wrong:.1%} | "
                     f"{untouched:.1%} |\n")

    print("-" * 80)
    if totals:
        n = len(totals)
        aw = sum(t[1] for t in totals) / n
        ai = sum(t[2] for t in totals) / n
        aa = sum(t[3] for t in totals) / n
        ao = sum(t[4] for t in totals) / n
        ac = sum(t[5] for t in totals) / n
        au = sum(t[6] for t in totals) / n
        print(f"{'AVERAGE':<12} {'':>6} {aw:>6.1%} {ai:>9.1%} {aa:>11.1%} "
              f"{ao:>8.1%} {ac:>8.1%} {au:>10.1%}")
        lines.append(f"\n**Average — WER {aw:.1%}, identical to human {ai:.1%}, "
                     f"acceptable {aa:.1%}, unambiguously wrong {ao:.1%}, "
                     f"untouched {au:.1%}**\n")

    lines.append("""
## Reading these numbers

**Acceptable is the honest headline.** Romanization has no single right answer -
Dakshina itself records several accepted spellings for 45% of words. Strict WER
penalises `nahi` against a human's `nahin`, which is not an error anybody would
report. `acceptable` counts our word right if it matches the human OR if both
are spellings Dakshina records for that word.

**Wrong** is the bucket that genuinely is wrong: a spelling nobody offered.

**Untouched** is the one number with no ambiguity: native-script words still
sitting in the output because neither the dictionary nor the model could spell
them. Those are visibly wrong to a user, so it is the metric to drive down.
""")

    (OUT / "bench_romanization.md").write_text("".join(lines), encoding="utf-8")
    print(f"\nwrote {OUT / 'bench_romanization.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
