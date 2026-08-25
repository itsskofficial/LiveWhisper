#!/usr/bin/env python
"""Experiment 5: how many corrections does a personalised speller actually need?

exp2 found 45% of Hindi words have more than one attested romanization. But
those variants are not random - they follow a small number of personal spelling
conventions. "mujhe" vs "muze" is not a fact about that word, it is a fact about
how someone spells झ.

If a handful of conventions explain most of the variation, then a handful of
corrections personalises the whole vocabulary, and we can even ask the user
up front instead of waiting for corrections.

    python experiments/exp5_spelling_axes.py <dakshina-root>
"""

from __future__ import annotations

import difflib
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from exp2_dakshina_coverage import load_lexicon  # noqa: E402

OUT = Path("experiments/results")
MAX_SPAN = 3          # ignore wholesale rewrites, we want letter-level habits


def axes_from_variants(forms: list[str]) -> list[tuple[str, str]]:
    """Extract letter-level substitution axes between spellings of one word."""
    found = []
    for i in range(len(forms)):
        for j in range(i + 1, len(forms)):
            a, b = forms[i], forms[j]
            sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
            for tag, i1, i2, j1, j2 in sm.get_opcodes():
                if tag != "replace":
                    continue
                x, y = a[i1:i2], b[j1:j2]
                if not x or not y or len(x) > MAX_SPAN or len(y) > MAX_SPAN:
                    continue
                # Canonicalise direction so jh->z and z->jh are one axis.
                found.append(tuple(sorted((x, y))))
    return found


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("dakshina_dataset_v1.0")
    lex = load_lexicon(root, "hi")
    if not lex:
        print(f"no hindi lexicon under {root}")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)

    multi = {w: [f for f, _ in forms] for w, forms in lex.items() if len(forms) > 1}
    print(f"words with more than one attested spelling: {len(multi):,} "
          f"of {len(lex):,}\n")

    axes = Counter()
    words_touching_axis: dict[tuple, set] = {}
    for w, forms in multi.items():
        for ax in axes_from_variants(forms):
            axes[ax] += 1
            words_touching_axis.setdefault(ax, set()).add(w)

    total = sum(axes.values())
    print(f"total substitution instances: {total:,}")
    print(f"distinct axes: {len(axes):,}\n")

    print(f"{'rank':>4}  {'axis':<14} {'count':>6} {'words':>6}  {'cum %':>6}")
    lines = ["# Experiment 5 - personal spelling axes\n\n",
             f"Words with >1 attested spelling: **{len(multi):,}** of {len(lex):,}\n\n",
             f"Distinct substitution axes: {len(axes):,} across "
             f"{total:,} instances\n\n",
             "| rank | axis | instances | words affected | cumulative % |\n",
             "|---|---|---|---|---|\n"]

    cum = 0
    for rank, (ax, n) in enumerate(axes.most_common(25), 1):
        cum += n
        pct = cum / total * 100
        label = f"{ax[0]} / {ax[1]}"
        nwords = len(words_touching_axis[ax])
        print(f"{rank:>4}  {label:<14} {n:>6} {nwords:>6}  {pct:>5.1f}%")
        lines.append(f"| {rank} | `{ax[0]}` / `{ax[1]}` | {n} | {nwords} | {pct:.1f}% |\n")

    # How much of the variation do the top-K axes explain?
    lines.append("\n## Coverage by number of preferences learned\n\n"
                 "| preferences known | variation explained |\n|---|---|\n")
    print("\n  preferences known -> variation explained")
    for k in (5, 10, 15, 20, 30, 50, 100):
        c = sum(n for _, n in axes.most_common(k))
        print(f"    top {k:>3} axes      {c/total*100:5.1f}%")
        lines.append(f"| {k} | {c/total*100:.1f}% |\n")

    # Words affected by the single most common axis, as a concrete illustration.
    top_ax = axes.most_common(1)[0][0]
    sample = sorted(words_touching_axis[top_ax])[:8]
    lines.append(f"\n## Illustration\n\nThe single most common axis "
                 f"(`{top_ax[0]}` / `{top_ax[1]}`) alone affects "
                 f"{len(words_touching_axis[top_ax])} words, e.g. "
                 f"{', '.join(sample)}\n")

    (OUT / "exp5_spelling_axes.md").write_text("".join(lines), encoding="utf-8")
    print(f"\nwrote {OUT / 'exp5_spelling_axes.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
