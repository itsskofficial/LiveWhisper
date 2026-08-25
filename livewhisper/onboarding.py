"""One-minute setup that learns how you spell, before you dictate anything.

exp5 measured that romanization variation follows a small number of letter-level
conventions - the top ten explain 57% of it. Rather than waiting for corrections
to arrive one at a time, we can just ask.

The user is shown a few short sentences in Devanagari and types each one the way
they normally would. Because we know exactly which Devanagari word sits at each
position, every word they type is a labelled example. One minute of typing
replaces weeks of corrections.

It also captures capitalisation and punctuation habits for free, because these
are chat-register sentences and people type them the way they text.

exp6 computed an optimal sentence set from Dakshina, but those sentences are
Wikipedia-derived and read formally ("intruders captured six weightlifters"),
which would prompt formal typing and hide the very habits we want to observe.
The sentences below are hand-written in chat register to hit the same axes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .script.conventions import Conventions, similarity, tokenize
from .script.lexicon import get_lexicon
from .script.romanize import DEVA_RUN, Romanizer

log = logging.getLogger(__name__)


@dataclass
class Prompt:
    devanagari: str
    gloss: str          # so the user knows what they are typing
    axes: str           # which conventions it exercises, for our own notes


# Five sentences, chosen to exercise the highest-frequency spelling axes from
# exp5 while sounding like something you would actually send someone.
PROMPTS = [
    Prompt("मुझे कल ऑफिस जाना है, तू आ रहा है क्या?",
           "I have to go to the office tomorrow, are you coming?",
           "j/z (mujhe), oo/u (tu), ai/e (hai), c/k (kya)"),
    Prompt("वो फिर से देर से आया, बहुत ज्यादा टाइम लगा।",
           "He was late again, it took way too much time.",
           "v/w (vo), f/ph (phir), j/z (zyada)"),
    Prompt("ठीक है यार, कोई बात नहीं, कल मिलते हैं।",
           "It's fine mate, no problem, see you tomorrow.",
           "ee/i (theek, nahi), a/e"),
    Prompt("कौन सा चाहिए तुझे? किसी वजह से नहीं आया वो।",
           "Which one do you want? He didn't come for some reason.",
           "au/o (kaun), j/z (tujhe), v/w (vajah, vo)"),
    Prompt("पूरा दिन काम किया फिर भी कुछ नहीं हुआ।",
           "Worked all day and still nothing happened.",
           "oo/u (poora, kuch), i/y (kiya), f/ph (phir)"),
]


@dataclass
class Result:
    pairs: list            # (devanagari_word, our_default, what_you_typed)
    notes: list            # human-readable description of what was learned
    conventions: Conventions
    sample_text: str       # everything typed, for habit observation
    skipped: int


class Onboarding:
    """Turns typed sentences into a seeded profile."""

    def __init__(self, lang: str = "hi"):
        self.lang = lang
        self.lexicon = get_lexicon(lang)
        self.romanizer = Romanizer(lang)

    def prompts(self) -> list:
        return list(PROMPTS)

    # ------------------------------------------------------------ alignment

    def align(self, devanagari: str, typed: str) -> list:
        """Pair each Devanagari word with the Latin word the user wrote for it.

        Transliteration preserves word order, so when the counts match we can
        align by position. When they do not - a dropped word, or two words typed
        as one - we walk both sides and only accept a pair when the Latin word
        is a plausible spelling of that Devanagari word. That stops a single
        mismatch from corrupting every pair after it.
        """
        native = DEVA_RUN.findall(devanagari)
        latin = tokenize(typed)
        if not native or not latin:
            return []

        if len(native) == len(latin):
            return list(zip(native, latin))

        pairs, i, j = [], 0, 0
        while i < len(native) and j < len(latin):
            if self._plausible(native[i], latin[j]):
                pairs.append((native[i], latin[j]))
                i += 1
                j += 1
            elif i + 1 < len(native) and self._plausible(native[i + 1], latin[j]):
                i += 1                      # user skipped a word
            elif j + 1 < len(latin) and self._plausible(native[i], latin[j + 1]):
                j += 1                      # extra Latin word with no source
            else:
                i += 1
                j += 1
        return pairs

    def _plausible(self, native: str, latin: str) -> bool:
        """Is this Latin token a believable spelling of that Devanagari word?"""
        default = self.lexicon.lookup(native)
        candidates = [default] if default else []
        candidates += self.lexicon.variants(native)
        if not candidates:
            return True         # unknown word: accept rather than derail
        return any(similarity(c, latin) >= 0.45 for c in candidates if c)

    # ------------------------------------------------------------- learning

    def process(self, answers: list) -> Result:
        """answers: list of (devanagari_prompt, what_the_user_typed)."""
        conv = Conventions()
        pairs, notes, skipped = [], [], 0
        typed_all = []

        for devanagari, typed in answers:
            if not typed or not typed.strip():
                skipped += 1
                continue
            typed_all.append(typed.strip())
            for native, latin in self.align(devanagari, typed):
                default = self.lexicon.lookup(native)
                if not default:
                    continue
                if default.lower() == latin.lower():
                    continue                     # already spelled our way
                pairs.append((native, default, latin))

        # Feed every disagreement in. The two-word promotion rule in
        # Conventions.learn still applies, so a one-off typo stays a one-off.
        for native, default, latin in pairs:
            notes += conv.learn(native, default, latin)

        return Result(pairs=pairs, notes=notes, conventions=conv,
                      sample_text="\n".join(typed_all), skipped=skipped)

    # ------------------------------------------------------------- applying

    def apply(self, result: Result, store, app: str | None = None) -> list:
        """Write what was learned into the profile store."""
        from .profile import ProfileStore

        glob = store.get(ProfileStore.GLOBAL).conventions
        glob.rules.update(result.conventions.rules)
        glob.overrides.update(result.conventions.overrides)
        for k, v in result.conventions.evidence.items():
            glob.evidence.setdefault(k, set()).update(v)

        # Chat-register sentences, so the habits observed here are the chat ones.
        target = store.get(app) if app else store.get(ProfileStore.GLOBAL)
        for line in result.sample_text.splitlines():
            if line.strip():
                target.habits.observe(line)

        store.save()
        return result.notes

    # -------------------------------------------------------------- preview

    def preview(self, conventions: Conventions) -> list:
        """Show the effect: how a sample sentence looks before and after."""
        sample = "मुझे नहीं पता वो कब आएगा, फिर भी मैं ठीक हूँ"
        before = Romanizer(self.lang).text(sample)
        after = Romanizer(self.lang, conventions).text(sample)
        return [sample, before, after]
