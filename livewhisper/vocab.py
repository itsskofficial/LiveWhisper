"""Words to know: put the user's own spelling back when the model was one letter off.

The vocabulary is already given to the speech model as a prompt, and that
fixes most names. It cannot fix a model that simply hears something else: the
Hinglish model writes "full request" for "pull request" whatever it is told, in
every end-to-end run of that sentence. So after transcription, a near miss of a
vocabulary entry is corrected - under rules strict enough that ordinary words
survive:

    phrases   same number of words, all identical but one, and that one a
              single letter off: "full request" -> "pull request"
    words     six letters or more and a single letter off:
              "Kubernetis" -> "Kubernetes"; "cat" is never turned into "bat"

Exact matches are respelled to the user's capitalisation ("kubernetes" ->
"Kubernetes"), which is what adding a name to the list is for.
"""

from __future__ import annotations

import re

_WORD = re.compile(r"[\w'’-]+", re.UNICODE)
MIN_SINGLE = 6


def entries(vocabulary: str) -> list:
    return [v.strip() for v in re.split(r"[,\n]", vocabulary or "") if v.strip()]


def _one_off(a: str, b: str) -> bool:
    """Exactly one substitution, insertion or deletion apart (case-insensitive)."""
    a, b = a.lower(), b.lower()
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


def apply(text: str, vocabulary: str) -> str:
    wanted = entries(vocabulary)
    if not wanted or not text:
        return text
    tokens = list(_WORD.finditer(text))
    replacements = []                      # (start, end, new)
    used = set()
    for phrase in sorted(wanted, key=lambda p: -len(p.split())):
        want = phrase.split()
        n = len(want)
        for i in range(len(tokens) - n + 1):
            if any(j in used for j in range(i, i + n)):
                continue
            got = [t.group(0) for t in tokens[i:i + n]]
            same = [g.lower() == w.lower() for g, w in zip(got, want)]
            if all(same):
                ok = got != want                       # respell the capitals
            elif n > 1:
                off = [k for k, s in enumerate(same) if not s]
                ok = (len(off) == 1 and len(want[off[0]]) >= 3
                      and _one_off(got[off[0]], want[off[0]]))
            else:
                ok = len(want[0]) >= MIN_SINGLE and _one_off(got[0], want[0])
            if ok:
                replacements.append((tokens[i].start(), tokens[i + n - 1].end(), phrase))
                used.update(range(i, i + n))
    for start, end, new in sorted(replacements, reverse=True):
        text = text[:start] + new + text[end:]
    return text
