"""Remove the hesitation sounds speech engines sometimes write down.

Wispr Flow and its peers strip "um" and "uh" from dictation, and people notice
when a tool does not. Whisper usually drops them itself, but not reliably - on
hesitant or code-switched speech it writes them out, and they land in the chat
box looking like a typo.

What is deliberately NOT done here, because it would damage Indic text:

  - Repeated words are never collapsed. "dheere dheere", "kya kya", "alag alag"
    are reduplication, which is grammar in Hindi and most South Asian languages,
    not a stutter. A generic "remove repeated word" rule destroys them.
  - "hmm", "oh", "ah", "haan", "matlab", "toh" are kept. People type them on
    purpose, and the discourse words are meaningful.

Only sounds that are never words in English or in romanized Indic text are
removed: um, uh, uhm, erm, and their stretched spellings (ummm, uhhh).
"""

from __future__ import annotations

import re

_FILLER = r"(?:u+m+|u+h+m*|e+r+m+)"

# The space in front of the sound is consumed with it, so what follows keeps its
# own spacing: "go um." -> "go.", "line uh\n" -> "line\n". Not inside a word, a
# URL, a handle or a path; the comma or ellipsis that trails the sound goes too.
_PATTERN = re.compile(
    rf"((?<=\S)[ \t]+)?(?<![\w'’./@#:-])(?:{_FILLER})(?![\w'’/@-])(?!\.\w)"
    r"(?:[ \t]*(?:,|\.\.\.|…))?",
    re.IGNORECASE,
)
_CAP = "\x00"


def remove_fillers(text: str) -> str:
    """Strip um/uh/erm, repairing the commas and capital left behind.

    Only the text around a removed sound is touched. Spacing elsewhere - code
    indentation, a Markdown line break's two trailing spaces - is left alone.
    """
    if not text or not _PATTERN.search(text):
        return text

    def repl(m: re.Match) -> str:
        lead = m.group(1) or ""
        word = m.group(0)[len(lead):]
        before = text[:m.start()]
        sentence_start = not before.strip() or re.search(r"[.!?]\s*$", before)
        # A capitalised filler opened the sentence, so the next word inherits
        # the capital: "Um, let's go" -> "Let's go".
        return lead + _CAP if sentence_start and word[:1].isupper() else ""

    out = _PATTERN.sub(repl, text)
    out = re.sub(_CAP + r"[ \t]*(\w)", lambda k: k.group(1).upper(), out)
    out = out.replace(_CAP, "")

    out = re.sub(r",(?:[ \t]*,)+", ",", out)                      # ", ,"
    out = re.sub(r",(?=[.!?])", "", out)                          # ",."
    out = re.sub(r"(^|[.!?][ \t]+|\n)[ \t]*,[ \t]*", r"\1", out)   # leading ", "
    return out.strip() if text == text.strip() else out
