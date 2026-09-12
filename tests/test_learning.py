#!/usr/bin/env python
"""How many corrections before it spells the way you do?

The README claims ten corrections cover 57% of spelling variation. That figure
came from exp5, which measured the *structure* of variation in the lexicon - it
never ran the actual learning loop. This does: it invents a user with a
consistent spelling style, puts them through the real pipeline, and measures how
fast the app converges on them.

The measurement that matters is on HELD-OUT sentences. Learning the words you
corrected is trivial and worthless; the whole premise of letter-level learning
is that correcting `mujhe` also fixes the 316 other words containing ज. So the
curve below is accuracy on words this simulated user never touched.

    python tests/test_learning.py [--rounds 40]
"""

from __future__ import annotations

import argparse
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper.console import setup as _console  # noqa: E402
from livewhisper.context import ScreenContext  # noqa: E402
from livewhisper.pipeline import Pipeline  # noqa: E402
from livewhisper.profile import ProfileStore  # noqa: E402
from livewhisper.script.languages import WORD, run_pattern  # noqa: E402
from livewhisper.script.lexicon import get_lexicon  # noqa: E402
from livewhisper.script.romanize import Romanizer  # noqa: E402

_console()

SEED = 7

# A style is a set of letter-level habits, which is how real variation actually
# works - exp5 found 1,200 such axes across 30,000 Hindi words, not 30,000
# independent word preferences. Ordered longest-first so "jh" wins over "j".
STYLES = {
    "z-for-jh": [("jh", "z")],
    "w-for-v": [("v", "w")],
    "three habits": [("jh", "z"), ("v", "w"), ("ph", "f")],
    "five habits": [("jh", "z"), ("v", "w"), ("ph", "f"), ("ksh", "x"),
                    ("chh", "ch")],
}

failures: list = []


def restyle(word: str, style: list) -> str:
    """Apply the user's habits to a default spelling."""
    out, i = [], 0
    while i < len(word):
        for a, b in style:
            if word.startswith(a, i):
                out.append(b)
                i += len(a)
                break
        else:
            out.append(word[i])
            i += 1
    return "".join(out)


def ctx(app: str, field: str) -> ScreenContext:
    return ScreenContext(app=app, title="t", text=field, focused_text=field,
                         method="uia")


def accuracy(pipe: Pipeline, sentences: list, style: list, lang: str) -> float:
    """Share of words spelled the way this user would spell them.

    Compares against the user's restyling of OUR default, not against Dakshina,
    so it isolates one thing: has the app picked up their habits?
    """
    pat = run_pattern(lang)
    plain = Romanizer(lang)                 # no conventions: the default speller
    right = total = 0
    for native in sentences:
        got = WORD.findall(pipe.process(native, ctx("t.exe", "")).text.lower())
        want = [restyle(plain.word(w)[0].lower(), style)
                for w in pat.findall(native)]
        if len(got) != len(want):
            continue
        for g, w in zip(got, want):
            total += 1
            right += (g == w)
    return right / total if total else 0.0


def words_needing_style(lang: str, style: list, n: int) -> list:
    """Native words whose default spelling this user would actually respell.

    Correcting words the style does not touch teaches nothing, and a real user
    only corrects what looks wrong to them.
    """
    lex = get_lexicon(lang)
    lex.load()
    out = []
    for native, forms in lex._entries.items():
        if not forms:
            continue
        d = forms[0]
        if restyle(d, style) != d and 3 <= len(d) <= 12:
            out.append(native)
        if len(out) >= max(n, 4000):
            break
    random.shuffle(out)
    return out[:n]


def run_style(label: str, style: list, rounds: int, lang: str = "hi") -> list:
    """Feed corrections in one at a time, measuring held-out accuracy as we go."""
    random.seed(SEED)
    lex = get_lexicon(lang)
    lex.load()

    # Probe on words the style DOES touch but the user never corrected.
    # Probing on words the habits do not affect measures nothing: the first run
    # of this test scored 100% before learning anything, because the probe
    # sentences happened to contain no "jh" at all.
    affected = words_needing_style(lang, style, 4000)
    teach = affected[:rounds]
    probe_pool = affected[rounds:rounds + 240]
    if len(probe_pool) < 40:
        raise SystemExit(f"not enough {lang} words affected by {style}")
    probes = [" ".join(probe_pool[i:i + 8])
              for i in range(0, len(probe_pool) - 7, 8)]

    curve = []
    with tempfile.TemporaryDirectory() as td:
        store = ProfileStore(Path(td) / "p.json")
        pipe = Pipeline({"language": lang, "script": {"mode": "auto"}}, store)
        plain = Romanizer(lang)

        curve.append((0, accuracy(pipe, probes, style, lang)))
        for k, native in enumerate(teach, 1):
            # Dictate the word, then leave the user's spelling in the field -
            # exactly what learn_from_screen sees on the next dictation.
            d = pipe.process(native, ctx("t.exe", ""))
            mine = d.text
            theirs = restyle(plain.word(native)[0], style)
            pipe.learn_from_screen(ctx("t.exe", theirs))
            if mine.lower() == theirs.lower():
                pass                       # already matched; no signal to give
            if k in (1, 2, 3, 5, 10, 15, 20, 30, 40, 60):
                curve.append((k, accuracy(pipe, probes, style, lang)))
        if rounds not in [c[0] for c in curve]:
            curve.append((rounds, accuracy(pipe, probes, style, lang)))

        conv = store.get(ProfileStore.GLOBAL).conventions
        rules = dict(conv.rules)
        # How many of the corrected words contained each habit. A rule needs two
        # distinct words (PROMOTE_AT) before it generalises, so a habit landing
        # in only one of the sampled words is expected to stay a per-word
        # override - that is the guard working, not a failure.
        seen = {f"{a}>{b}": len(conv.evidence.get(f"{a}>{b}", ()))
                for a, b in style}
    print(f"\n  {label}: target habits {style}")
    print(f"  {'corrections':>12} {'held-out accuracy':>18}")
    for k, a in curve:
        print(f"  {k:>12} {a:>17.1%}")
    print(f"  learned rules: {rules}")

    for a, b in style:
        if rules.get(a) == b:
            continue
        n = seen.get(f"{a}>{b}", 0)
        why = (f"appeared in only {n} corrected word(s); needs 2"
               if n < 2 else "rejected by the collateral guard")
        print(f"  [ note ] {a} -> {b} stayed a per-word override: {why}")
    return curve


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=40)
    args = ap.parse_args()

    print("=== convergence on held-out words ===")
    results = {}
    for label, style in STYLES.items():
        results[label] = run_style(label, style, args.rounds)

    print("\n=== what this has to satisfy ===")
    for label, curve in results.items():
        start = curve[0][1]
        at10 = next((a for k, a in curve if k >= 10), curve[-1][1])
        end = curve[-1][1]
        ok = end > start + 0.02
        print(f"[{'  ok  ' if ok else ' FAIL '}] {label}: "
              f"{start:.1%} -> {at10:.1%} at 10 -> {end:.1%}")
        if not ok:
            failures.append(f"{label} did not improve ({start:.1%} -> {end:.1%})")

    # The single-habit case is the cleanest claim: one letter rule, learned from
    # two words, should transfer to essentially every word containing it.
    single = results["z-for-jh"]
    at2 = next((a for k, a in single if k >= 2), 0.0)
    gain = at2 - single[0][1]
    print(f"[{'  ok  ' if gain > 0.0 else ' FAIL '}] "
          f"one habit generalises after 2 corrections  (+{gain:.1%})")
    if gain <= 0.0:
        failures.append("jh -> z did not generalise after two corrections")

    if failures:
        print(f"\n{len(failures)} FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nlearning converges, and generalises beyond the corrected words")
    return 0


if __name__ == "__main__":
    sys.exit(main())
