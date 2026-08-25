#!/usr/bin/env python
"""Experiment 6: which sentences should onboarding ask the user to type?

exp5 showed a small number of letter-level conventions explain most romanization
variation. Rather than asking the user to tap through preference pairs, show
them a few real sentences in Devanagari and ask them to type each one the way
they normally would.

That yields three things from one action:
  - their romanization conventions (from how they spelled each word)
  - their capitalization habit
  - their punctuation habit

This picks the smallest set of sentences that exercises the most conventions,
by greedy set cover over real Dakshina sentences.

    python experiments/exp6_onboarding_sentences.py <dakshina-root>
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from exp2_dakshina_coverage import load_lexicon  # noqa: E402
from exp5_spelling_axes import axes_from_variants  # noqa: E402

OUT = Path("experiments/results")
DEVA = re.compile(r"[ऀ-ॿ]+")
TOP_AXES = 20
WANT = 6
MIN_WORDS, MAX_WORDS = 5, 14      # short enough that nobody abandons onboarding


def load_sentences(root: Path) -> list[str]:
    path = root / "hi" / "romanized" / "hi.romanized.rejoined.dev.native.txt"
    if not path.exists():
        return []
    seen, out = set(), []
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s in seen:
                continue
            seen.add(s)
            out.append(s)
    return out


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("dakshina_dataset_v1.0")
    lex = load_lexicon(root, "hi")
    sents = load_sentences(root)
    if not lex or not sents:
        print("need both the lexicon and the romanized sentence data")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"lexicon {len(lex):,} words   sentences {len(sents):,}")

    # Rank axes as in exp5, then keep the top ones as our coverage target.
    counts = Counter()
    word_axes: dict[str, set] = {}
    for w, forms in lex.items():
        if len(forms) < 2:
            continue
        ax = set(axes_from_variants([f for f, _ in forms]))
        if ax:
            word_axes[w] = ax
            counts.update(ax)
    target = [a for a, _ in counts.most_common(TOP_AXES)]
    target_set = set(target)
    print(f"targeting the top {TOP_AXES} conventions\n")

    # What does each candidate sentence exercise?
    cand = []
    for s in sents:
        words = DEVA.findall(s)
        if not (MIN_WORDS <= len(words) <= MAX_WORDS):
            continue
        covered = set()
        for w in words:
            covered |= word_axes.get(w, set()) & target_set
        if covered:
            cand.append((s, covered, len(words)))
    print(f"usable candidate sentences: {len(cand):,}")

    # Greedy set cover, tie-broken toward shorter sentences.
    chosen, got = [], set()
    for _ in range(WANT):
        best = max(cand, key=lambda c: (len(c[1] - got), -c[2]), default=None)
        if not best or not (best[1] - got):
            break
        chosen.append(best)
        got |= best[1]
        cand.remove(best)

    lines = ["# Experiment 6 - onboarding sentences\n\n",
             f"Greedy cover of the top {TOP_AXES} spelling conventions using real "
             f"Dakshina sentences.\n\n"]

    print(f"\n{len(chosen)} sentences cover {len(got)}/{TOP_AXES} conventions "
          f"({len(got)/TOP_AXES*100:.0f}%)\n")
    running = set()
    for i, (s, cov, n) in enumerate(chosen, 1):
        running |= cov
        new = sorted(f"{a}/{b}" for a, b in cov)
        print(f"{i}. {s}")
        print(f"   {n} words - exercises {len(cov)} conventions - "
              f"cumulative {len(running)}/{TOP_AXES}")
        print(f"   {', '.join(new[:8])}\n")
        lines.append(f"## {i}\n\n**{s}**\n\n{n} words, exercises "
                     f"{len(cov)} conventions, cumulative "
                     f"{len(running)}/{TOP_AXES}\n\n`{', '.join(new)}`\n\n")

    missed = sorted(f"{a}/{b}" for a, b in target_set - got)
    if missed:
        lines.append(f"## Not covered\n\n`{', '.join(missed)}`\n")
        print(f"not covered: {', '.join(missed)}")

    (OUT / "exp6_onboarding_sentences.md").write_text("".join(lines), encoding="utf-8")
    print(f"\nwrote {OUT / 'exp6_onboarding_sentences.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
