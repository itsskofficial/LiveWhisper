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

        guess = self._oov.spell([native], self.lang).get(native)
        if guess:
            return self.conventions.apply(guess), "model"
        return native, "none"

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
        guesses = self._oov.spell(unknown, self.lang) if unknown else {}

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
        """Compare what we produced with what the user changed it to."""
        from .conventions import similarity, tokenize

        notes: list = []
        b_words, a_words = tokenize(before), tokenize(after)
        if not b_words or not a_words:
            return notes

        produced = {}
        for native in dict.fromkeys(self._pattern.findall(self._last_native or "")):
            spelling, _ = self.word(native)
            produced[spelling.lower()] = native

        for i, bw in enumerate(b_words):
            native = produced.get(bw.lower())
            if not native:
                continue
            window = a_words[max(0, i - 2):i + 3] or a_words
            best = max(window, key=lambda aw: similarity(bw, aw), default=None)
            if best and best.lower() != bw.lower() and similarity(bw, best) > 0.45:
                notes += self.conventions.learn(native, bw, best)
        return notes


def romanize_text(text: str, lang: str = DEFAULT,
                  conventions: Conventions | None = None) -> str:
    return Romanizer(lang, conventions).text(text)


__all__ = ["Romanizer", "romanize_text", "has_indic", "script_ratio", "DEVA_RUN"]
