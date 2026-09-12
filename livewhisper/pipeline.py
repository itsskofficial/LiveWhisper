"""Everything that happens between the transcript and your cursor.

    transcript
        -> pick script (Latin or Devanagari) from what is on screen
        -> romanize Devanagari spans, applying your spelling conventions
        -> apply your orthographic habits for this app
        -> deliver

Plus the reverse direction: when you edit what was pasted, work out what
changed and feed it back into the profile.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from . import context as ctx_mod
from .profile import ProfileStore
from .script import conventions as conv_mod
from .script.languages import detect_script, has_indic, supported
from .script.romanize import Romanizer, script_ratio

log = logging.getLogger(__name__)


@dataclass
class Delivery:
    text: str
    raw: str                 # transcript before any processing
    app: str
    script: str              # latin | native
    romanized: bool
    notes: list
    language: str | None = None   # which lexicon was used


class Pipeline:
    def __init__(self, cfg: dict, profiles: ProfileStore):
        self.cfg = cfg
        self.profiles = profiles
        self._last: Delivery | None = None

    # --------------------------------------------------------------- script

    def choose_script(self, app: str, screen: ctx_mod.ScreenContext | None) -> str:
        """Latin or Devanagari?

        Priority: an explicit per-app setting, then what is already in the
        field. Replying inside a Devanagari thread means you want Devanagari;
        replying in a Latin one means you do not. That needs no configuration
        and is right nearly always.
        """
        forced = self.profiles.get(app).script
        if forced in ("latin", "native", "devanagari"):
            return "native" if forced == "devanagari" else forced

        if screen:
            existing = screen.focused_text or ""
            if len(existing.strip()) >= 8:
                return "native" if script_ratio(existing) < 0.5 else "latin"
        return self.cfg.get("script", {}).get("default", "latin")

    # -------------------------------------------------------------- forward

    def resolve_language(self, transcript: str, heard: str | None) -> str:
        """Which lexicon should romanize this?

        Whisper reports the language it heard, which is right far more often
        than any setting the user would remember to change - somebody who
        speaks Tamil at work and Hindi at home should not have to toggle. A
        configured language wins when set to something other than `auto`,
        because detection is weak on short or code-switched clips.
        """
        configured = (self.cfg.get("script", {}) or {}).get("language", "auto")
        if configured and configured != "auto" and supported(configured):
            return configured
        if heard and supported(heard):
            return heard
        # Fall back to whichever script is actually on the page.
        return detect_script(transcript) or "hi"

    def process(self, transcript: str, screen: ctx_mod.ScreenContext | None = None,
                force_script: str | None = None,
                heard_language: str | None = None) -> Delivery:
        app = (screen.app if screen else "") or ""
        profile = self.profiles.get(app)
        notes: list = []

        script = force_script or self.choose_script(app, screen)
        text = transcript
        romanized = False
        lang = None

        if has_indic(transcript) and script == "latin":
            lang = self.resolve_language(transcript, heard_language)
            r = Romanizer(lang, self.profiles.merged_conventions(app))
            r.remember_source(transcript)
            text = r.text(transcript)
            romanized = True
            self._romanizer = r

        text = profile.habits.apply(text)

        d = Delivery(text=text, raw=transcript, app=app, script=script,
                     romanized=romanized, notes=notes, language=lang)
        self._last = d
        return d

    # -------------------------------------------------------------- reverse

    # How much of what we pasted has to still be there for the field to count as
    # an edit of our text. Below this the user has moved on, cleared the box, or
    # written something else entirely, and there is nothing to learn from.
    EDIT_OVERLAP = 0.5

    @staticmethod
    def _is_edit_of_mine(mine: str, current: str) -> bool:
        """Is this field plausibly our text with corrections applied?

        The old test was `len(current) < 4`, which only rejected near-empty
        fields. Everything else was treated as a correction of our dictation -
        including a field the user had since filled with unrelated text, whose
        words then got aligned against ours and learned as respellings.

        Containment is the common case (the user fixed a word or two, or typed
        around our text). Otherwise require that most of our words survived -
        where a word counts as surviving if it is still there verbatim OR a
        plausible respelling of it is.

        That second clause is essential, not a nicety: correcting a one-word
        dictation replaces the only word we produced, so an exact-match test
        scores 0% and refuses the clearest correction there is.
        """
        if mine in current:
            return True
        mine_words = [w.lower() for w in conv_mod.tokenize(mine)]
        if not mine_words:
            return False
        theirs = [w.lower() for w in conv_mod.tokenize(current)]
        if not theirs:
            return False
        kept = sum(w in theirs
                   or any(conv_mod.plausible_correction(w, t) for t in theirs)
                   for w in mine_words)
        return kept / len(mine_words) >= Pipeline.EDIT_OVERLAP

    def learn_from_screen(self, screen: ctx_mod.ScreenContext | None) -> list:
        """Compare what we pasted with what is in the field now.

        Called at the START of the next dictation, which is the cheap moment to
        do it - no background watching, no keylogging, and the user is already
        in the same field.
        """
        if not self._last or not screen:
            return []
        current = (screen.focused_text or "").strip()
        mine = self._last.text.strip()
        if not current or current == mine:
            return []
        if not self._is_edit_of_mine(mine, current):
            return []

        notes: list = []
        # Orthographic habits: learn from whatever the user actually left there.
        self.profiles.observe_text(self._last.app, current)

        # Spelling: only meaningful if we romanized something.
        if self._last.romanized and getattr(self, "_romanizer", None):
            try:
                notes = self._romanizer.learn_from_correction(
                    self._last.text, current)
                if notes:
                    glob = self.profiles.get(ProfileStore.GLOBAL).conventions
                    glob.rules.update(self._romanizer.conventions.rules)
                    glob.overrides.update(self._romanizer.conventions.overrides)
                    for k, v in self._romanizer.conventions.evidence.items():
                        glob.evidence.setdefault(k, set()).update(v)
            except Exception:
                log.debug("correction learning failed", exc_info=True)

        self.profiles.save()
        return notes

    def seed_from_onboarding(self, pairs: list) -> list:
        """(devanagari_word, default_spelling, user_spelling) triples."""
        conv = self.profiles.get(ProfileStore.GLOBAL).conventions
        notes = conv.seed(pairs)
        self.profiles.save()
        return notes
