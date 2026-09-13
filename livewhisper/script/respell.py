"""Bring a Hinglish speech model's spelling in line with how people type.

Some speech models skip the native script entirely and write romanized text
straight from audio (Oriserve's Whisper-Hindi2Hinglish family). That is the
right shape for this app - English words come out as English, "Television
report", instead of टेलीविजन रिपोर्ट romanized letter by letter - but they spell
long vowels the way a transliteration scheme does:

    saamaan   basaaya   vaala   yaatra   dikhaaya   paribhaasha

where people type samaan, basaya, wala, yatra, dikhaya, paribhasha. On FLEURS,
61% of that model's word "errors" against human spellings were exactly this.

The fix is deliberately narrow. A word is only changed if nobody in the
Dakshina lexicon spells it that way AND shortening its doubled vowels produces
a spelling that people do use. Already-attested words, including the English
words the model writes, are never touched, and neither are capitalised words in
the middle of a sentence, which are names and English nouns.

Only for text a Latin-output model produced. Run on arbitrary English it could
still turn an unattested word into a Hindi one, so the pipeline gates it.
"""

from __future__ import annotations

import itertools
import re
from functools import lru_cache

from .lexicon import COMMON_WORDS, get_lexicon

# Doubled vowel -> the short form people usually type.
LONG = (("aa", "a"), ("ee", "i"), ("oo", "u"), ("ii", "i"), ("uu", "u"))
MAX_SPOTS = 6            # beyond this the combinations stop being a spelling fix
_LATIN = re.compile(r"[A-Za-z]+")


@lru_cache(maxsize=16)
def attested(lang: str) -> frozenset:
    """Every Latin spelling anyone offered for any word in this language."""
    lex = get_lexicon(lang)
    lex.load()
    out = {f.lower() for forms in lex._entries.values() for f in forms}
    out.update(v.lower() for v in COMMON_WORDS.get(lang, {}).values())
    return frozenset(out)


def respell_word(word: str, lang: str) -> str:
    """The closest attested spelling reachable by shortening vowels, or the word."""
    known = attested(lang)
    lw = word.lower()
    if lw in known or not lw.isascii():
        return word
    spots = sorted({(m.start(), a, b) for a, b in LONG
                    for m in re.finditer(f"(?={a})", lw)})[:MAX_SPOTS]
    for k in range(1, len(spots) + 1):                  # fewest changes first
        for combo in itertools.combinations(spots, k):
            s, shift, ok = lw, 0, True
            for pos, a, b in combo:
                p = pos - shift
                if s[p:p + len(a)] != a:                # overlapping spots
                    ok = False
                    break
                s = s[:p] + b + s[p + len(a):]
                shift += len(a) - len(b)
            if ok and s in known:
                return s[:1].upper() + s[1:] if word[:1].isupper() else s
    return word


def respell(text: str, lang: str) -> str:
    """Respell every eligible word in a Hinglish model's transcript."""
    if not text:
        return text

    def repl(m: re.Match) -> str:
        word = m.group(0)
        before = text[:m.start()].rstrip()
        sentence_start = not before or before[-1] in ".!?\n"
        if word[:1].isupper() and not sentence_start:
            return word                                 # a name, or English
        return respell_word(word, lang)

    return _LATIN.sub(repl, text)
