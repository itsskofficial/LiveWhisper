#!/usr/bin/env python
"""Build the shipped lexicons for every language from the Dakshina dataset.

    python tools/build_lexicons.py <path-to-dakshina_dataset_v1.0>

Writes data/<code>.lexicon.tsv - one line per native word, followed by its
attested Latin spellings ordered by how many people wrote them that way.

Dakshina is CC BY-SA 4.0; see data/LICENSE-DATA.md.
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper.script.languages import CODES, LANGUAGES  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
MAX_VARIANTS = 4        # beyond this the tail is noise and costs disk


def load(root: Path, lang: str) -> dict:
    files = sorted((root / lang / "lexicons").glob(f"{lang}.translit.sampled.*.tsv"))
    counts: dict[str, Counter] = defaultdict(Counter)
    for f in files:
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 2:
                    continue
                native, roman = parts[0].strip(), parts[1].strip()
                if not native or not roman:
                    continue
                n = int(parts[2]) if len(parts) > 2 and parts[2].strip().isdigit() else 1
                counts[native][roman] += n
    return {w: c.most_common(MAX_VARIANTS) for w, c in counts.items()}


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    root = Path(sys.argv[1])
    if not root.exists():
        print(f"not found: {root}")
        return 1
    DATA.mkdir(exist_ok=True)

    total_words = total_bytes = 0
    print(f"{'lang':<6} {'name':<12} {'words':>8} {'size':>9}  speakers")
    print("-" * 58)
    for code in CODES:
        lex = load(root, code)
        if not lex:
            print(f"{code:<6} {LANGUAGES[code].name:<12} {'-':>8}  no data")
            continue
        out = DATA / f"{code}.lexicon.tsv"
        with open(out, "w", encoding="utf-8") as f:
            for w, forms in sorted(lex.items()):
                f.write(w + "\t" + "\t".join(f"{r}:{n}" for r, n in forms) + "\n")
        size = out.stat().st_size
        total_words += len(lex)
        total_bytes += size
        print(f"{code:<6} {LANGUAGES[code].name:<12} {len(lex):>8,} "
              f"{size/1e6:>7.1f}MB  {LANGUAGES[code].speakers_m}M")

    print("-" * 58)
    print(f"{'':<6} {'TOTAL':<12} {total_words:>8,} {total_bytes/1e6:>7.1f}MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
