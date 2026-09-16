"""Names from the screen, handed to the decoder before it starts.

Whisper writes down what it expects to hear, and it has never heard of the
people you work with. "Sarthak" comes out as "Sar tak", a colleague's surname
becomes three English words, and your product's name becomes whatever is
closest in the training data. Commercial dictation apps solve this by reading
the window you are typing into and sending it to their servers with the audio.
The reading is the useful half; the sending is not.

So this takes what the app already captures - the window in front of you, which
context.py reads through the same accessibility layer a screen reader uses -
and pulls out the words a speech model is likely to get wrong: names, product
names, acronyms. They go into the decoder's prompt, on this machine, and are
gone when the dictation ends. Nothing is stored and nothing leaves.

The risk is real and runs the other way: a prompt full of words that have
nothing to do with what you said can pull the transcript toward them, and
Whisper in particular will happily repeat prompt text it never heard. That is
why this is deliberately stingy - a few dozen short candidates, ranked, capped,
and measured in tests/bench_bias.py against the case where the screen has
nothing to do with the speech.
"""

from __future__ import annotations

import re
from collections import Counter

# A capitalised word is only interesting if it is not just a sentence opening.
# These are the words that start sentences, plus the ones any English model
# already knows. Kept small on purpose: the frequency and position rules below
# do most of the work, and a long stop list would be a second vocabulary to
# maintain.
_COMMON = {
    "the", "a", "an", "and", "but", "or", "if", "then", "so", "because",
    "i", "you", "he", "she", "it", "we", "they", "this", "that", "these",
    "those", "there", "here", "what", "when", "where", "who", "why", "how",
    "is", "are", "was", "were", "be", "been", "being", "do", "does", "did",
    "have", "has", "had", "will", "would", "can", "could", "should", "may",
    "might", "must", "shall", "let", "please", "thanks", "thank", "hi",
    "hello", "hey", "dear", "regards", "best", "yes", "no", "not", "for",
    "from", "with", "without", "about", "into", "over", "under", "after",
    "before", "just", "only", "also", "very", "all", "any", "some", "more",
    "most", "other", "such", "new", "old", "good", "great", "sure", "ok",
    "okay", "today", "tomorrow", "yesterday", "now", "soon", "again", "still",
    "sent", "subject", "to", "cc", "bcc", "reply", "forward", "inbox",
    "file", "edit", "view", "help", "search", "settings", "home", "back",
}

# A name, a product, or an acronym - the three shapes worth biasing.
_CANDIDATE = re.compile(
    r"\b("
    r"[A-Z][a-z]{2,15}(?:[A-Z][a-z]+)*"     # Sarthak, LiveWhisper, McDonald
    r"|[A-Z]{2,6}"                          # API, WASAPI, GST
    r")\b")

MAX_PHRASES = 32
MAX_CHARS = 240


def candidates(text: str) -> Counter:
    """Score the name-shaped words in some text.

    A word is scored by how often it appears and by whether it ever appears
    somewhere other than the start of a sentence, which is the only evidence
    available that the capital is part of the word rather than punctuation.
    """
    found: Counter = Counter()
    if not text:
        return found
    for sentence in re.split(r"(?<=[.!?\n])\s+", text):
        for i, m in enumerate(_CANDIDATE.finditer(sentence)):
            word = m.group(1)
            if word.lower() in _COMMON or len(word) < 2:
                continue
            opens_sentence = m.start() == 0
            found[word] += 1 if opens_sentence else 2
    return found


def phrases(screen_text: str = "", focused_text: str = "",
            extra: str = "", limit: int = MAX_PHRASES,
            max_chars: int = MAX_CHARS) -> str:
    """The biasing string for one dictation, or "" when there is nothing worth it.

    `focused_text` - the field being typed into - is weighted above the rest of
    the window: the names in the thread you are replying to matter more than
    the ones in the sidebar. `extra` is the user's own vocabulary setting and
    always goes first, because they typed it deliberately.
    """
    scores = candidates(screen_text)
    for word, score in candidates(focused_text).items():
        scores[word] += score * 2
    ranked = [w for w, _ in scores.most_common(limit * 2)]

    out: list = []
    budget = max_chars
    for word in [w.strip() for w in re.split(r"[,\n]", extra) if w.strip()] + ranked:
        if word in out:
            continue
        if len(word) + 2 > budget or len(out) >= limit:
            break
        out.append(word)
        budget -= len(word) + 2
    return ", ".join(out)
