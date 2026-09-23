"""Second opinion on the language, from the words Whisper wrote.

Whisper decides the language from the first seconds of sound, and between
languages that sound alike it guesses: a Marathi speaker's "tu AI system
design kuthun shikla" was heard as Hindi on all four voices tried, then
decoded as Hindi ("kuchhun" for kuthun). The transcript usually gives the
language away - कुठून and शिकला are Marathi words, not Hindi ones - so when a
language the speaker uses shares the script of the one Whisper chose, count
the words that only one of the two languages' lexicons contains. The other
language wins with at least two such words and more of them.

Measured on reference text before any audio (FLEURS dev + test, Hindi and
Marathi code-switched sentences, 370 in all): 357 recovered from the wrong
sibling, 0 correct ones flipped. End to end: tests/eval_codeswitch.py.
"""

from __future__ import annotations

import re
import threading

# Languages among the twelve that share a script, so one can be heard as the
# other and still be written plausibly. Bengali, Gujarati, Gurmukhi, the
# Dravidian scripts and Sinhala each belong to one language here.
_SIBLINGS = {"hi": ("mr",), "mr": ("hi",), "ur": ("sd",), "sd": ("ur",)}
MIN_WORDS = 2
_TOKEN = re.compile(r"[ऀ-ॿ؀-ۿݐ-ݿ]+")

_lexicons: dict = {}
_lock = threading.Lock()


def _words(lang: str) -> set:
    with _lock:
        if lang not in _lexicons:
            from .lexicon import get_lexicon
            lex = get_lexicon(lang)
            lex.load()
            _lexicons[lang] = frozenset(lex._entries)
        return _lexicons[lang]


def evidence(text: str, heard: str, rival: str) -> tuple:
    """(words only `rival` knows, words only `heard` knows)."""
    a, b = _words(rival), _words(heard)
    ws = _TOKEN.findall(text)
    return (sum(w in a and w not in b for w in ws), sum(w in b and w not in a for w in ws))


def reconsider(text: str, heard: str | None, languages: list) -> str | None:
    """The language the transcript is really in, if not `heard`; else None.

    Only languages the speaker uses are considered, and only a sibling that
    shares `heard`'s script (_SIBLINGS): a different script would already show."""
    if not heard or not text:
        return None
    for rival in _SIBLINGS.get(heard, ()):
        if rival not in languages:
            continue
        for_rival, for_heard = evidence(text, heard, rival)
        if for_rival >= MIN_WORDS and for_rival > for_heard:
            return rival
    return None
