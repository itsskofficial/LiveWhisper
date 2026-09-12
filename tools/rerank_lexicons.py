#!/usr/bin/env python
"""Re-rank each lexicon by what people write in sentences, not in word lists.

The lexicon orders spellings by how many annotators offered them when shown a
word in isolation. Benchmarking against human-romanized *sentences* showed that
is the wrong signal: the isolated-word vote favours longer, more phonetically
explicit spellings than people actually type in running text.

    Malayalam  വിഖ്യാത   lexicon says vikhyaatha   humans wrote vikhyatha
    Malayalam  നാടക      lexicon says naadaka      humans wrote nadaka
    Tamil      போட்டிகளில் lexicon says poattigalil  humans wrote pottigalil

Dakshina also ships ~5,000 human-romanized sentences per language. This counts
which spelling those humans actually used, and promotes it to first place.
Spellings never seen in running text keep their original order behind it.

Two guards, both of which came from a real regression: a spelling must be
typeable on an ordinary keyboard (the corpora contain scholarly diacritics like
aḵẖtar), and must appear at least twice before it overturns the word-list vote.

    python tools/rerank_lexicons.py <dakshina-root>

Rewrites data/<code>.lexicon.tsv in place.
"""

from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper.script.languages import CODES, LANGUAGES, run_pattern  # noqa: E402

from livewhisper.console import setup as _console

_console()

DATA = Path(__file__).resolve().parent.parent / "data"
WORD = re.compile(r"[^\W\d_]+", re.UNICODE)

# A spelling is only useful if the user could have typed it on a plain keyboard.
# Dakshina's corpora contain scholarly transliterations with diacritics -
# Punjabi aḵẖtar for akhtar, ġani for gani - which are correct ISO 15919 and
# completely wrong as output: nobody types them and they look broken in a chat
# window. They are rare enough to lose the word-list vote, but they do appear in
# running text, so without this filter the rerank promotes them.
TYPEABLE = re.compile(r"[a-z'’.-]+")

# One sighting in running text is not evidence, it is a typo or an outlier. The
# incumbent spelling already has a word-list vote behind it, so require the
# corpus form to appear at least twice before overturning that.
MIN_SIGHTINGS = 2


def corpus_counts(root: Path, code: str) -> dict:
    """native word -> Counter of the spellings humans used in sentences."""
    base = root / code / "romanized"
    counts: dict = defaultdict(Counter)
    pattern = run_pattern(code)

    # ONLY the test split. The benchmark evaluates on dev, so learning from dev
    # here would be training on the evaluation set and the improvement would be
    # meaningless.
    for split in ("test",):
        nat_p = base / f"{code}.romanized.rejoined.{split}.native.txt"
        rom_p = base / f"{code}.romanized.rejoined.{split}.roman.txt"
        if not (nat_p.exists() and rom_p.exists()):
            continue
        natives = nat_p.read_text(encoding="utf-8").splitlines()
        romans = rom_p.read_text(encoding="utf-8").splitlines()
        for native, roman in zip(natives, romans):
            nw = pattern.findall(native)
            rw = WORD.findall(roman.lower())
            # Only learn from sentences that align cleanly. A mismatched count
            # means a word was merged or dropped, and guessing there would
            # teach the wrong spelling to every word after it.
            if not nw or len(nw) != len(rw):
                continue
            for n, r in zip(nw, rw):
                if TYPEABLE.fullmatch(r):
                    counts[n][r] += 1
    return counts


def load_lexicon(path: Path) -> dict:
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 2:
                continue
            forms = []
            for field in parts[1:]:
                if not field:
                    continue
                spelling, _, count = field.rpartition(":")
                if not spelling:
                    spelling, count = field, "1"
                forms.append((spelling, int(count) if count.isdigit() else 1))
            if forms:
                out[parts[0]] = forms
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    root = Path(sys.argv[1])

    print(f"{'language':<12} {'words':>8} {'reranked':>9} {'new forms':>10} "
          f"{'corpus words':>13}")
    print("-" * 58)

    for code in CODES:
        path = DATA / f"{code}.lexicon.tsv"
        if not path.exists():
            continue
        lex = load_lexicon(path)
        counts = corpus_counts(root, code)
        if not counts:
            print(f"{LANGUAGES[code].name:<12} no sentence corpus")
            continue

        reranked = added = 0
        for word, forms in lex.items():
            seen = counts.get(word)
            if not seen:
                continue
            preferred, sightings = seen.most_common(1)[0]
            if sightings < MIN_SIGHTINGS:
                continue
            existing = [f for f, _ in forms]
            if existing and existing[0].lower() == preferred.lower():
                continue
            # Promote the corpus favourite; keep everything else in order.
            rest = [(f, c) for f, c in forms if f.lower() != preferred.lower()]
            match = next((c for f, c in forms if f.lower() == preferred.lower()), 0)
            if not match:
                added += 1
            lex[word] = [(preferred, max(match, seen[preferred]))] + rest
            reranked += 1

        with open(path, "w", encoding="utf-8") as f:
            for word, forms in sorted(lex.items()):
                f.write(word + "\t" +
                        "\t".join(f"{s}:{c}" for s, c in forms[:4]) + "\n")

        print(f"{LANGUAGES[code].name:<12} {len(lex):>8,} {reranked:>9,} "
              f"{added:>10,} {len(counts):>13,}")

    print("-" * 58)
    print("lexicons rewritten")
    return 0


if __name__ == "__main__":
    sys.exit(main())
