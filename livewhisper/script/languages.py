"""The twelve South Asian languages LiveWhisper can romanize.

Hinglish is not a special case. Tanglish, Banglish, Thanglish, Manglish and the
rest are the same phenomenon: people speak the language, and type it in Latin
letters because that is what the keyboard and the culture settled on. Every
speech engine writes the native script, so voice typing produces text in the
wrong script for roughly 1.5 billion people.

Google's Dakshina dataset covers all twelve, so the pipeline that solved Hindi
solves the rest unchanged - only the lexicon and the script range differ.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


# ZWNJ and ZWJ appear *inside* Indic words - Marathi अधिकार्‍यांच्या, Malayalam
# അക്‌ബർ, Sinhala අංශුමාත්‍ර - so a script range that excludes them splits words
# in half. Measured on the shipped lexicons: 5% of Sinhala words, and a
# scattering of Marathi and Malayalam. Those words would silently never
# romanize.
JOINERS = "\u200c\u200d"


def _mark_ranges() -> str:
    r"""Character-class body covering every Unicode combining mark.

    Needed because Python's `\w` is defined by `str.isalnum()`, and a combining
    mark is not alphanumeric. So the obvious word pattern `[^\W\d_]+` tears
    Indic words apart at every vowel sign and virama:

        \u0d05\u0d27\u0d4d\u0d2f\u0d3e\u0d2a\u0d15\u0d38\u0d02\u0d18\u0d1f\u0d28\u0d15\u0d33\u0d41\u0d02  ->  ['\u0d05\u0d27', '\u0d2f', '\u0d2a\u0d15\u0d38', '\u0d18\u0d1f\u0d28\u0d15\u0d33']

    One Malayalam word became four. That inflated word counts wherever native
    script survived into the output, and fed fragments into convention learning.
    Malayalam and Sinhala suffer most, being the most conjunct-heavy.

    Scanning all of Unicode at import would cost half a second, so this covers
    the blocks that carry marks for Latin and the twelve Indic scripts.
    """
    spans: list = []
    start = prev = None
    for cp in (list(range(0x0300, 0x1B00)) + list(range(0x1DC0, 0x1E00))
               + list(range(0x20D0, 0x2100)) + list(range(0xFE00, 0xFE30))):
        if unicodedata.category(chr(cp)).startswith("M"):
            if start is None:
                start = cp
            prev = cp
        elif start is not None:
            spans.append((start, prev))
            start = None
    if start is not None:
        spans.append((start, prev))
    return "".join(chr(a) if a == b else f"{chr(a)}-{chr(b)}" for a, b in spans)


MARKS = _mark_ranges()

# A word is a letter, followed by any letters, the marks that attach to them and
# the joiners that sit inside them. Apostrophes ride along so "don't" stays one
# word. Anchoring on a letter keeps a stray mark from starting a token.
#
# The mark class has to be a positive alternative, not another member of the
# negated class - putting it inside `[^...]` excludes marks twice over, which is
# exactly the bug this is here to fix.
WORD = re.compile("[^\\W\\d_](?:[^\\W\\d_]|[" + MARKS + JOINERS + "'\u2019])*",
                  re.UNICODE)


@dataclass(frozen=True)
class Language:
    code: str            # ISO 639-1, matches what Whisper reports
    name: str            # English name
    endonym: str         # what speakers call it, for the UI
    nickname: str        # what the romanized mix is actually called
    script: str          # script name
    ranges: tuple        # unicode ranges of that script
    speakers_m: int      # rough millions, for prioritising work

    @property
    def pattern(self) -> str:
        return "".join(f"{a}-{b}" for a, b in self.ranges) + JOINERS


# Ordered by speaker population, which is also roughly the order in which
# getting each one right matters.
LANGUAGES = {
    l.code: l for l in [
        Language("hi", "Hindi", "हिन्दी", "Hinglish", "Devanagari",
                 (("ऀ", "ॿ"),), 610),
        Language("bn", "Bengali", "বাংলা", "Banglish", "Bengali",
                 (("ঀ", "৿"),), 270),
        Language("ur", "Urdu", "اردو", "Urdish", "Arabic",
                 (("؀", "ۿ"), ("ݐ", "ݿ"),
                  ("ﭐ", "﷿"), ("ﹰ", "﻿")), 230),
        Language("pa", "Punjabi", "ਪੰਜਾਬੀ", "Punglish", "Gurmukhi",
                 (("਀", "੿"),), 125),
        Language("mr", "Marathi", "मराठी", "Minglish", "Devanagari",
                 (("ऀ", "ॿ"),), 83),
        Language("te", "Telugu", "తెలుగు", "Thanglish", "Telugu",
                 (("ఀ", "౿"),), 83),
        Language("ta", "Tamil", "தமிழ்", "Tanglish", "Tamil",
                 (("஀", "௿"),), 79),
        Language("gu", "Gujarati", "ગુજરાતી", "Gujlish", "Gujarati",
                 (("઀", "૿"),), 57),
        Language("kn", "Kannada", "ಕನ್ನಡ", "Kanglish", "Kannada",
                 (("ಀ", "೿"),), 44),
        Language("ml", "Malayalam", "മലയാളം", "Manglish", "Malayalam",
                 (("ഀ", "ൿ"),), 38),
        Language("si", "Sinhala", "සිංහල", "Singlish", "Sinhala",
                 (("඀", "෿"),), 17),
        Language("sd", "Sindhi", "سنڌي", "Sindhlish", "Arabic",
                 (("؀", "ۿ"), ("ݐ", "ݿ")), 32),
    ]
}

CODES = list(LANGUAGES)
DEFAULT = "hi"


def get(code: str | None) -> Language:
    return LANGUAGES.get((code or DEFAULT).lower(), LANGUAGES[DEFAULT])


def supported(code: str | None) -> bool:
    return bool(code) and code.lower() in LANGUAGES


# One regex matching every non-Latin script we handle, so text can be scanned
# without knowing the language up front.
ALL_RANGES = sorted({r for l in LANGUAGES.values() for r in l.ranges})
ANY_INDIC = re.compile("[" + "".join(f"{a}-{b}" for a, b in ALL_RANGES)
                       + JOINERS + "]+")

_PER_LANG = {code: re.compile("[" + l.pattern + "]+")
             for code, l in LANGUAGES.items()}


def run_pattern(code: str | None) -> re.Pattern:
    """Regex matching runs of the given language's script."""
    return _PER_LANG.get((code or DEFAULT).lower(), _PER_LANG[DEFAULT])


def detect_script(text: str) -> str | None:
    """Which language's script is this text written in?

    Devanagari is shared by Hindi and Marathi and Arabic by Urdu and Sindhi, so
    this returns the more widely spoken of each pair. The user's configured
    language wins over this when one is set.
    """
    counts: dict[str, int] = {}
    for ch in text:
        if ch in JOINERS:
            continue
        for code, pat in _PER_LANG.items():
            if pat.match(ch):
                counts[code] = counts.get(code, 0) + 1
                break
    if not counts:
        return None
    # Prefer the most-spoken language among those whose script matched.
    best = max(counts.values())
    tied = [c for c, n in counts.items() if n == best]
    return max(tied, key=lambda c: LANGUAGES[c].speakers_m)


def has_indic(text: str) -> bool:
    return any(m.strip(JOINERS) for m in ANY_INDIC.findall(text))


def latin_ratio(text: str) -> float:
    """1.0 = all Latin, 0.0 = all native script. Used to pick output script."""
    latin = sum(1 for c in text if "a" <= c.lower() <= "z")
    native = sum(len(m.strip(JOINERS)) for m in ANY_INDIC.findall(text))
    return latin / (latin + native) if (latin + native) else 1.0


def total_speakers() -> int:
    return sum(l.speakers_m for l in LANGUAGES.values())
