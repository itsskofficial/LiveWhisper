"""Never paste words nobody said.

Given silence or room noise, Whisper does not return nothing: it returns a
confident sentence. With a muted or wrong microphone a dictation came back
"Aapke liye aapke liye aapke liye aapke liye." and was pasted into Notepad. The
voice-activity filter had let four seconds of noise through.

Two tell-tales, either of which drops the result:

    looping     one short phrase repeated three or more times back to back,
                making up most of the text - not how anyone dictates
    stock text  on a recording at the microphone's noise floor, the phrases
                Whisper is known to produce from nothing ("Thank you for
                watching", "धन्यवाद", "aapke liye")

The level alone is not enough: a quiet microphone can carry real speech at the
level another one idles at. So quiet audio is only a reason to distrust stock
phrases, never a reason to drop a real sentence.
"""

from __future__ import annotations

import re

import numpy as np

# Measured on a laptop microphone in a quiet room: frame RMS p95 0.007 with no
# one speaking. Speech into the same microphone sits several times above that.
QUIET_P95 = 0.012

_STOCK = [
    r"thank(?:s| you)(?: (?:so|very) much)?(?: for watching| for listening)?",
    r"(?:please )?(?:like and )?subscribe(?: to (?:my|the|our) channel)?",
    r"see you (?:next time|in the next (?:video|one))",
    r"you", r"bye", r"okay", r"hmm+",
    r"aapke liye", r"dhanyavaad", r"dhanyawad", r"shukriya",
    r"धन्यवाद", r"आपके लिए", r"शुक्रिया",
    r"subtitles? by .*", r"transcribed by .*",
]
_STOCK_RE = re.compile(r"^\s*(?:(?:" + "|".join(_STOCK) + r")[\s.,!?।]*)+$", re.IGNORECASE)
# Words split on spaces and punctuation, not on \w: Indic vowel signs are
# not \w, and splitting on them turned चाचा into two "words" that repeat.
_WORD = re.compile(r"[^\s.,!?;:\"'()\[\]{}।॥-]+")


def loudness(audio: np.ndarray, rate: int = 16000) -> float:
    """95th percentile of 30 ms frame RMS: how loud the loudest speech was."""
    frame = int(rate * 0.03)
    if audio is None or len(audio) < frame:
        return 0.0
    f = np.asarray(audio[: len(audio) // frame * frame], dtype=np.float32).reshape(-1, frame)
    return float(np.percentile(np.sqrt((f ** 2).mean(axis=1)), 95))


def looping(text: str) -> bool:
    """One phrase of one to six words, three or more times in a row, as at least
    three quarters of the text. On 239,516 real sentences from Dakshina, no
    sentence qualifies ("Hanse Janwar ho ho ho" does not)."""
    words = [w.lower() for w in _WORD.findall(text)]
    if len(words) < 3:
        return False
    for n in range(1, 7):
        i = 0
        while i + 3 * n <= len(words):
            gram = words[i:i + n]
            reps = 1
            while words[i + reps * n:i + (reps + 1) * n] == gram:
                reps += 1
            if reps >= 3 and reps * n >= 0.75 * len(words):
                return True
            i += 1
    return False


def invented(text: str, audio: np.ndarray | None = None) -> bool:
    """Is this transcript most likely made up rather than said?"""
    if not text.strip():
        return False
    if looping(text):
        return True
    quiet = audio is not None and loudness(audio) < QUIET_P95
    return quiet and bool(_STOCK_RE.match(text))
