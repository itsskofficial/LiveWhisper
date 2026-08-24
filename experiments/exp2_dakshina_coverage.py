#!/usr/bin/env python
"""Experiment 2: how far does a Dakshina lexicon lookup get us?

exp1/exp1b showed prompting cannot make Whisper emit Latin-script Hindi, so a
transliteration stage is required. The cheapest possible stage is a dictionary:
Devanagari word -> attested romanization, straight from Google's Dakshina
romanization lexicon.

This measures whether that is enough, on REAL Whisper output from real Hinglish
audio rather than on Dakshina's own held-out data.

Questions
---------
1. Token coverage - what share of Devanagari tokens are in the lexicon at all?
2. Ambiguity     - how many attested romanizations does a typical word have?
3. Naturalness   - does the most-attested form look like what people type?

    python experiments/exp2_dakshina_coverage.py <path-to-dakshina-root>
"""

from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

OUT = Path("experiments/results")
DEVA_TOKEN = re.compile(r"[ऀ-ॿ]+")

# Real large-v3 output from accuracy_runs/hinglish.wav (Raj Shamani podcast, 75s).
SAMPLE = """
You were saying, MNCs से ज्यादा start-up job create करेंगे, that's your take. क्यूं?
I mean, that's one take. My other take is that, a lot of MNCs are going to shut shop
because of start-ups. I mean, MNCs बंद हो जाएंगे start-ups की बारे से. Yes, and I'll
tell you, like, three reasons मैं बताता हूँ, because, MNCs खरीद नहीं लेंगी start-up को,
जो कर रही हो रही है. It's possible, and we'll look at some, you know, examples also,
कुछ interesting, जैसे for example, एक आपको, call the innovator's dilemma बहुत सही concept
है वो innovator's dilemma essentially ये है I'm sure like people must have read about it
it essentially means that समझो आप एक business चला रहे हो and 80% of your business comes
from a revenue line A अगर दुनिया तेजी से change हो रही है और वो A का आपको B करना पड़ेगा तो
you face a massive dilemma and the dilemma that you face is that यार मेरा 80% revenue,
मैं इतनी बड़ी company हूँ मेरा, 80% revenue A से आ रहा है, अब मुझे मेरे आखों के सामने दिख
रहा है कि A भी बनने वाला है, but मैं कैसे रोकू इस चीज को, and startups जो है न, they come
with no baggage, no hangover, कुछ नहीं है उनका revenue.
"""


def load_lexicon(root: Path, lang: str) -> dict[str, list[tuple[str, int]]]:
    """native word -> [(romanization, attestation_count), ...] best first."""
    files = sorted((root / lang / "lexicons").glob(f"{lang}.translit.sampled.*.tsv"))
    if not files:
        files = sorted(root.rglob(f"{lang}.translit.sampled.*.tsv"))
    if not files:
        return {}

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

    return {w: c.most_common() for w, c in counts.items()}


def report(name: str, lex: dict, tokens: list[str], lines: list[str]) -> None:
    types = sorted(set(tokens))
    tok_hits = [t for t in tokens if t in lex]
    typ_hits = [t for t in types if t in lex]

    tok_cov = len(tok_hits) / len(tokens) * 100 if tokens else 0
    typ_cov = len(typ_hits) / len(types) * 100 if types else 0

    variants = [len(lex[t]) for t in typ_hits]
    avg_var = sum(variants) / len(variants) if variants else 0
    multi = sum(1 for v in variants if v > 1)

    print(f"\n--- {name} ---")
    print(f"  lexicon entries      {len(lex):,}")
    print(f"  token coverage       {tok_cov:5.1f}%  ({len(tok_hits)}/{len(tokens)})")
    print(f"  type coverage        {typ_cov:5.1f}%  ({len(typ_hits)}/{len(types)})")
    print(f"  avg romanizations    {avg_var:.1f} per covered word")
    print(f"  words with >1 form   {multi}/{len(typ_hits)}")

    lines.append(f"\n## {name}\n\n"
                 f"- lexicon entries: {len(lex):,}\n"
                 f"- token coverage: **{tok_cov:.1f}%** ({len(tok_hits)}/{len(tokens)})\n"
                 f"- type coverage: **{typ_cov:.1f}%** ({len(typ_hits)}/{len(types)})\n"
                 f"- average romanizations per covered word: {avg_var:.1f}\n"
                 f"- words with more than one attested form: {multi}/{len(typ_hits)}\n")

    print(f"\n  {'word':<12} {'top':<12} {'n':>3}  alternatives")
    lines.append("\n| word | top romanization | variants | alternatives |\n|---|---|---|---|\n")
    for t in types[:26]:
        if t not in lex:
            print(f"  {t:<12} {'-- MISSING --':<12}")
            lines.append(f"| {t} | **missing** | - | - |\n")
            continue
        forms = lex[t]
        alts = ", ".join(f for f, _ in forms[1:5])
        print(f"  {t:<12} {forms[0][0]:<12} {len(forms):>3}  {alts[:40]}")
        lines.append(f"| {t} | `{forms[0][0]}` | {len(forms)} | {alts or '-'} |\n")

    missing = [t for t in types if t not in lex]
    if missing:
        lines.append(f"\nMissing ({len(missing)}): {' '.join(missing)}\n")


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("dakshina_dataset_v1.0")
    if not root.exists():
        print(f"dakshina root not found: {root}")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)

    tokens = DEVA_TOKEN.findall(SAMPLE)
    print(f"sample: {len(tokens)} devanagari tokens, "
          f"{len(set(tokens))} unique\n")

    lines = ["# Experiment 2 - Dakshina lexicon coverage\n",
             f"\nMeasured on real large-v3 output from `accuracy_runs/hinglish.wav` "
             f"({len(tokens)} Devanagari tokens, {len(set(tokens))} unique).\n"]

    for lang, label in (("hi", "Hindi"), ("mr", "Marathi")):
        lex = load_lexicon(root, lang)
        if not lex:
            print(f"--- {label} ---\n  no lexicon files found")
            continue
        report(label, lex, tokens, lines)

    # Combined: Hinglish speakers use both, and Marathi shares the script.
    hi, mr = load_lexicon(root, "hi"), load_lexicon(root, "mr")
    if hi and mr:
        merged = dict(mr)
        merged.update(hi)          # Hindi wins on conflict
        report("Hindi + Marathi merged", merged, tokens, lines)

    path = OUT / "exp2_dakshina_coverage.md"
    path.write_text("".join(lines), encoding="utf-8")
    print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
