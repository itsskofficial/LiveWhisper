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

from .script.conventions import LEN_RATIO as _LEN_RATIO
from .script.conventions import MIN_SIMILARITY as _MIN_SIMILARITY
from .script.conventions import Conventions, similarity, tokenize
from .script.languages import DEFAULT, LANGUAGES, run_pattern, supported
from .script.lexicon import get_lexicon
from .script.romanize import Romanizer

log = logging.getLogger(__name__)


@dataclass
class Prompt:
    devanagari: str
    gloss: str          # so the user knows what they are typing
    axes: str           # which conventions it exercises, for our own notes


# Five sentences, chosen to exercise the highest-frequency spelling axes from
# exp5 while sounding like something you would actually send someone.
SENTENCES = {
  "hi": [
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
  ],
  # The other eleven fall back to word prompts generated from their own
  # lexicon (see _word_prompts). Contributing natural chat-register sentences
  # for your language is the single most useful thing a native speaker can add
  # here - see CONTRIBUTING.md.
}

PROMPTS = SENTENCES["hi"]        # kept for callers that imported it


# A sentence per language to show the before/after effect at the end of setup.
PREVIEW = {
    "hi": "मुझे नहीं पता वो कब आएगा, फिर भी मैं ठीक हूँ",
    "mr": "मला माहीत नाही तो कधी येईल",
    "bn": "আমি জানি না সে কখন আসবে",
    "ta": "அவன் எப்போது வருவான் என்று தெரியாது",
    "te": "అతను ఎప్పుడు వస్తాడో నాకు తెలియదు",
    "kn": "ಅವನು ಯಾವಾಗ ಬರುತ್ತಾನೆ ಎಂದು ಗೊತ್ತಿಲ್ಲ",
    "ml": "അവൻ എപ്പോൾ വരുമെന്ന് എനിക്കറിയില്ല",
    "gu": "મને ખબર નથી તે ક્યારે આવશે",
    "pa": "ਮੈਨੂੰ ਨਹੀਂ ਪਤਾ ਉਹ ਕਦੋਂ ਆਵੇਗਾ",
    "ur": "مجھے نہیں معلوم وہ کب آئے گا",
    "si": "එයා කවදා එනවද කියලා මම දන්නේ නෑ",
}


@dataclass
class Result:
    pairs: list            # (devanagari_word, our_default, what_you_typed)
    notes: list            # human-readable description of what was learned
    conventions: Conventions
    sample_text: str       # everything typed, for habit observation
    skipped: int


class Onboarding:
    """Turns typed sentences into a seeded profile."""

    def __init__(self, lang: str = DEFAULT):
        # "auto" is a transcription setting, not something we can onboard for -
        # the user has to tell us which language they type.
        self.lang = lang if supported(lang) else DEFAULT
        self.language = LANGUAGES[self.lang]
        self.lexicon = get_lexicon(self.lang)
        self.romanizer = Romanizer(self.lang)
        self._pattern = run_pattern(self.lang)

    def prompts(self) -> list:
        """Sentences where we have them, generated word prompts otherwise."""
        hand_written = SENTENCES.get(self.lang)
        if hand_written:
            return list(hand_written)
        return self._word_prompts()

    def _word_prompts(self, count: int = 8) -> list:
        """Ask about common words whose spelling people disagree on.

        Hindi gets hand-written sentences, which are better - they reveal
        capitalisation and punctuation too. For the other eleven we generate
        from the lexicon until a native speaker contributes sentences, ranking
        by how many people attested the word so the questions are answerable.
        """
        out = []
        for word in self.lexicon.contested(limit=count * 3):
            forms = self.lexicon.variants(word)
            if len(forms) < 2:
                continue
            alts = ", ".join(forms[1:3])
            out.append(Prompt(
                devanagari=word,
                gloss=f"we spell this \"{forms[0]}\"" +
                      (f", others write {alts}" if alts else ""),
                axes="generated from lexicon variance"))
            if len(out) >= count:
                break
        return out

    # ------------------------------------------------------------ alignment

    def align(self, devanagari: str, typed: str) -> list:
        """Pair each Devanagari word with the Latin word the user wrote for it.

        Transliteration preserves word order, so when the counts match we can
        align by position. When they do not - a dropped word, or two words typed
        as one - we walk both sides and only accept a pair when the Latin word
        is a plausible spelling of that Devanagari word. That stops a single
        mismatch from corrupting every pair after it.
        """
        native = self._pattern.findall(devanagari)
        latin = tokenize(typed)
        if not native or not latin:
            return []

        # Always walk, never zip. Equal counts are not proof of alignment:
        # merging one pair of words while splitting another keeps the count
        # identical and shifts everything after it. Real wizard data failed
        # exactly this way.
        pairs, i, j = [], 0, 0
        while i < len(native) and j < len(latin):
            merged = self._merge_score(native, i, latin[j])
            direct = self._score(native[i], latin[j])

            # A merge scores higher than either half alone, so check it first.
            # "aa raha" typed as "araha" matches आ+रहा better than either word,
            # and no override is recorded because the spelling cannot honestly
            # be attributed to one of them.
            if merged > max(direct, 0.6):
                i += 2
                j += 1
                continue

            if direct >= self.MIN_SIMILARITY:
                pairs.append((native[i], latin[j]))
                i += 1
                j += 1
            elif (i + 1 < len(native)
                  and self._score(native[i + 1], latin[j]) >= self.MIN_SIMILARITY):
                i += 1                      # a native word the user skipped
            elif (j + 1 < len(latin)
                  and self._score(native[i], latin[j + 1]) >= self.MIN_SIMILARITY):
                j += 1                      # a Latin word with no native source
            else:
                i += 1                      # neither matches: drop both
                j += 1
        return pairs

    def _merge_score(self, native: list, i: int, latin: str) -> float:
        """Does this Latin token look like two native words typed as one?"""
        if i + 1 >= len(native):
            return 0.0
        a = self.lexicon.lookup(native[i])
        b = self.lexicon.lookup(native[i + 1])
        if not a or not b:
            return 0.0
        return similarity(a + b, latin)

    # Shared with correction learning, which had its own looser threshold until
    # that let a markdown link teach मैं -> "link". One place to tune, so the two
    # paths cannot drift apart again. See conventions.MIN_SIMILARITY.
    MIN_SIMILARITY = _MIN_SIMILARITY
    LEN_RATIO = _LEN_RATIO

    def _score(self, native: str, latin: str) -> float:
        """How believable is this Latin token as a spelling of that word?

        Best match across every attested spelling, but only for candidates of a
        sensible length - transliteration roughly preserves length, so a token
        much longer than the word is a merge rather than a respelling.
        """
        candidates = [c for c in ([self.lexicon.lookup(native)]
                                  + self.lexicon.variants(native)) if c]
        if not candidates:
            return 1.0          # unknown word: accept rather than derail
        best = 0.0
        for c in candidates:
            ratio = len(latin) / len(c)
            if not (self.LEN_RATIO[0] <= ratio <= self.LEN_RATIO[1]):
                continue
            best = max(best, similarity(c, latin))
        return best

    def _plausible(self, native: str, latin: str) -> bool:
        return self._score(native, latin) >= self.MIN_SIMILARITY

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
        sample = PREVIEW.get(self.lang)
        if not sample:
            words = [p.devanagari for p in self.prompts()[:6]]
            sample = " ".join(words)
        before = Romanizer(self.lang).text(sample)
        after = Romanizer(self.lang, conventions).text(sample)
        return [sample, before, after]
