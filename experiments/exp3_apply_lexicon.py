#!/usr/bin/env python
"""Experiment 3: apply the Dakshina lexicon to real Whisper output.

exp2 measured coverage statistically. This shows what the pipeline actually
produces end to end, which is the only way to judge whether the output looks
like something a person would type on WhatsApp.

    python experiments/exp3_apply_lexicon.py <dakshina-root>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from exp2_dakshina_coverage import SAMPLE, load_lexicon  # noqa: E402

OUT = Path("experiments/results")
DEVA_RUN = re.compile(r"[ऀ-ॿ]+")


def romanize(text: str, lex: dict, mark_oov: bool = True) -> tuple[str, list[str]]:
    oov: list[str] = []

    def sub(m: re.Match) -> str:
        word = m.group(0)
        if word in lex:
            return lex[word][0][0]
        oov.append(word)
        return f"<{word}>" if mark_oov else word

    return DEVA_RUN.sub(sub, text), oov


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("dakshina_dataset_v1.0")
    lex = load_lexicon(root, "hi")
    if not lex:
        print(f"no hindi lexicon under {root}")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)

    sample = " ".join(SAMPLE.split())
    out, oov = romanize(sample, lex)

    print("=== BEFORE (whisper large-v3 output) ===\n")
    print(sample)
    print("\n=== AFTER (dakshina lexicon, top form; <> = out of vocabulary) ===\n")
    print(out)
    print(f"\nOOV: {len(oov)} tokens -> {' '.join(oov)}")

    OUT.joinpath("exp3_apply_lexicon.md").write_text(
        "# Experiment 3 - lexicon applied to real output\n\n"
        "## Before (Whisper large-v3)\n\n" + sample +
        "\n\n## After (Dakshina lexicon, most-attested form)\n\n" + out +
        f"\n\n## Out of vocabulary\n\n{len(oov)} tokens: {' '.join(oov)}\n",
        encoding="utf-8")
    print(f"\nwrote {OUT / 'exp3_apply_lexicon.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
