"""The romanization pipeline: Devanagari spans in, the user's spelling out.

    कल मैं office जाऊंगा   ->   kal main office jaunga

English is never touched - only Devanagari runs are converted, so a transcript
that mixes both keeps its English exactly as transcribed.
"""

from __future__ import annotations

import logging
import re

from .conventions import Conventions
from .lexicon import get_lexicon
from .oov import get_model

log = logging.getLogger(__name__)

DEVA_RUN = re.compile(r"[ऀ-ॿ]+")


def has_devanagari(text: str) -> bool:
    return bool(DEVA_RUN.search(text))


def script_ratio(text: str) -> float:
    """Share of letters written in Latin. 1.0 = pure Latin, 0.0 = pure Devanagari."""
    latin = sum(1 for c in text if "a" <= c.lower() <= "z")
    deva = sum(1 for c in text if "ऀ" <= c <= "ॿ")
    return latin / (latin + deva) if (latin + deva) else 1.0


class Romanizer:
    """lexicon -> model -> the user's conventions, in that order."""

    def __init__(self, lang: str = "hi", conventions: Conventions | None = None):
        self.lang = lang
        self.conventions = conventions or Conventions()
        self._lex = get_lexicon(lang)
        self._oov = get_model()

    # ------------------------------------------------------------ one word

    def word(self, native: str) -> tuple[str, str]:
        """Returns (spelling, source) where source is override|lexicon|model|none."""
        if native in self.conventions.overrides:
            return self.conventions.overrides[native], "override"

        base = self._lex.lookup(native)
        if base is not None:
            return self.conventions.apply(base), "lexicon"

        guess = self._oov.spell([native]).get(native)
        if guess:
            return self.conventions.apply(guess), "model"
        return native, "none"

    # ------------------------------------------------------------ one text

    def text(self, text: str) -> str:
        if not has_devanagari(text):
            return text

        # Resolve every unknown word in one batched model call rather than one
        # call per word - the difference is milliseconds vs. seconds.
        natives = DEVA_RUN.findall(text)
        unknown = [w for w in dict.fromkeys(natives)
                   if w not in self.conventions.overrides
                   and self._lex.lookup(w) is None]
        guesses = self._oov.spell(unknown) if unknown else {}

        def repl(m: re.Match) -> str:
            native = m.group(0)
            if native in self.conventions.overrides:
                return self.conventions.overrides[native]
            base = self._lex.lookup(native)
            if base is None:
                base = guesses.get(native)
            return self.conventions.apply(base) if base else native

        return DEVA_RUN.sub(repl, text)

    # ------------------------------------------------------------ learning

    def learn_from_correction(self, before: str, after: str) -> list[str]:
        """Compare what we produced with what the user changed it to.

        Only word pairs whose native source we can identify teach us anything,
        so this walks the words we romanized and looks for what replaced them.
        """
        from .conventions import similarity, tokenize

        notes: list[str] = []
        b_words, a_words = tokenize(before), tokenize(after)
        if not b_words or not a_words:
            return notes

        # Map each romanized word back to the Devanagari it came from.
        produced = {}
        for native in dict.fromkeys(DEVA_RUN.findall(self._last_native or "")):
            spelling, _ = self.word(native)
            produced[spelling.lower()] = native

        for i, bw in enumerate(b_words):
            native = produced.get(bw.lower())
            if not native:
                continue
            # find the closest word in the corrected text near the same position
            window = a_words[max(0, i - 2):i + 3] or a_words
            best = max(window, key=lambda aw: similarity(bw, aw), default=None)
            if best and best.lower() != bw.lower() and similarity(bw, best) > 0.45:
                notes += self.conventions.learn(native, bw, best)
        return notes

    _last_native: str | None = None

    def remember_source(self, native_text: str) -> None:
        """Keep the pre-romanization text so corrections can be traced back."""
        self._last_native = native_text


def romanize_text(text: str, lang: str = "hi",
                  conventions: Conventions | None = None) -> str:
    return Romanizer(lang, conventions).text(text)
