"""The romanization pipeline: native script in, the user's Latin spelling out.

    कल मैं office जाऊंगा      ->  kal main office jaunga     (Hindi)
    நான் நாளைக்கு வருவேன்      ->  naan naalaikku varuven     (Tamil)
    আমি কাল আসব               ->  ami kal asbo               (Bengali)

English is never touched - only runs of the native script are converted, so a
transcript that mixes both keeps its English exactly as transcribed.
"""

from __future__ import annotations

import logging
import re

from .conventions import Conventions
from .languages import DEFAULT, get, has_indic, latin_ratio, run_pattern
from .lexicon import get_lexicon
from .oov import get_model

log = logging.getLogger(__name__)

# Kept for callers that imported these before multi-language support.
DEVA_RUN = run_pattern("hi")


def script_ratio(text: str) -> float:
    """1.0 = all Latin, 0.0 = all native script."""
    return latin_ratio(text)


class Romanizer:
    """lexicon -> model -> the user's conventions, in that order."""

    def __init__(self, lang: str = DEFAULT, conventions: Conventions | None = None):
        self.lang = (lang or DEFAULT).lower()
        self.language = get(self.lang)
        self.conventions = conventions or Conventions()
        self._pattern = run_pattern(self.lang)
        self._lex = get_lexicon(self.lang)
        self._oov = get_model()
        self._last_native: str | None = None

    # ------------------------------------------------------------ one word

    def word(self, native: str) -> tuple[str, str]:
        """Returns (spelling, source) where source is override|lexicon|model|none."""
        if native in self.conventions.overrides:
            return self.conventions.overrides[native], "override"

        base = self._lex.lookup(native)
        if base is not None:
            return self.conventions.apply(base), "lexicon"

        guess = self._resolve_unknown([native]).get(native)
        if guess:
            return self.conventions.apply(guess), "model"
        return native, "none"

    # How to treat a long word the lexicon does not contain:
    #   "first"     split it into known words before asking the character model
    #   "fallback"  split only when the model gives up (it refuses words over 22
    #               characters and its own looping output)
    #   "off"       never split
    # Agglutinative languages glue words together; the others mostly do not, and
    # a false split of a name hurts them. So the choice is per language, set from
    # tests/bench_romanization.py --compounds on two disjoint samples.
    # Measured on two disjoint 500-sentence samples of Dakshina's human
    # romanizations. The rule was fixed before the second sample was run:
    # "first" only where it beat "fallback" on both, otherwise "fallback".
    #
    #                 first vs fallback, WER points    fallback vs off
    #                 sample 1     sample 2            (never worse anywhere)
    #   Kannada        -1.1         -1.1
    #   Gujarati       -0.3         -0.3
    #   Sindhi         -0.3         -0.3
    #   Sinhala        -0.2         -0.4
    #   Tamil          +0.2         +0.2               splitting names hurts it
    #
    # "fallback" also cuts the words left in native script (Malayalam 2.8% ->
    # 2.5%) without second-guessing a single word the model could spell.
    COMPOUND_POLICY = {"default": "fallback",
                       "kn": "first", "gu": "first", "sd": "first", "si": "first"}

    # A mode string here overrides the policy for every language. The benchmark
    # uses it to compare modes; None means "follow COMPOUND_POLICY".
    COMPOUNDS: str | None = None

    @property
    def compound_mode(self) -> str:
        if self.COMPOUNDS:
            return self.COMPOUNDS
        return self.COMPOUND_POLICY.get(self.lang, self.COMPOUND_POLICY["default"])

    def _resolve_unknown(self, words: list) -> dict:
        """Spell words the lexicon does not contain: compounds, then the model."""
        out: dict = {}
        mode = self.compound_mode
        if mode == "first":
            for w in words:
                parts = self._lex.segment(w)
                if parts:
                    out[w] = "".join(self._lex.lookup(p) for p in parts)
        rest = [w for w in words if w not in out]
        if rest:
            out.update(self._oov.spell(rest, self.lang))
        if mode == "fallback":
            for w in words:
                if w not in out:
                    parts = self._lex.segment(w)
                    if parts:
                        out[w] = "".join(self._lex.lookup(p) for p in parts)
        return out

    # ------------------------------------------------------------ one text

    def text(self, text: str) -> str:
        if not self._pattern.search(text):
            return text

        # Resolve every unknown word in one batched model call rather than one
        # call per word - the difference is milliseconds vs. seconds.
        natives = self._pattern.findall(text)
        unknown = [w for w in dict.fromkeys(natives)
                   if w not in self.conventions.overrides
                   and self._lex.lookup(w) is None]
        guesses = self._resolve_unknown(unknown) if unknown else {}

        def repl(m: re.Match) -> str:
            native = m.group(0)
            if native in self.conventions.overrides:
                return self.conventions.overrides[native]
            base = self._lex.lookup(native)
            if base is None:
                base = guesses.get(native)
            return self.conventions.apply(base) if base else native

        return self._pattern.sub(repl, text)

    # ------------------------------------------------------------ learning

    def remember_source(self, native_text: str) -> None:
        """Keep the pre-romanization text so corrections can be traced back."""
        self._last_native = native_text

    def learn_from_correction(self, before: str, after: str) -> list:
        """Compare what we produced with what the user changed it to.

        Only respellings are learned. A nearby token that merely resembles our
        word is a different word, and an override taken from one is permanent and
        applies everywhere, so the bar to cross is `plausible_correction`.
        """
        from .conventions import plausible_correction, similarity, tokenize

        notes: list = []
        b_words, a_words = tokenize(before), tokenize(after)
        if not b_words or not a_words:
            return notes

        produced = {}
        for native in dict.fromkeys(self._pattern.findall(self._last_native or "")):
            spelling, _ = self.word(native)
            produced[spelling.lower()] = native

        # Words the user left alone are evidence that they are already spelled
        # right, so they must not be claimed as the correction for some other
        # word sitting next to them.
        unchanged = {w.lower() for w in a_words} & {w.lower() for w in b_words}

        for i, bw in enumerate(b_words):
            native = produced.get(bw.lower())
            if not native:
                continue
            window = a_words[max(0, i - 2):i + 3] or a_words
            cands = [aw for aw in window
                     if aw.lower() != bw.lower()
                     and aw.lower() not in unchanged
                     and plausible_correction(bw, aw)]
            if not cands:
                continue
            best = max(cands, key=lambda aw: similarity(bw, aw))
            notes += self.conventions.learn(native, bw, best)
        return notes


def romanize_text(text: str, lang: str = DEFAULT,
                  conventions: Conventions | None = None) -> str:
    return Romanizer(lang, conventions).text(text)


__all__ = ["Romanizer", "romanize_text", "has_indic", "script_ratio", "DEVA_RUN"]
