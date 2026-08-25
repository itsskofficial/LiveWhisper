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
from .script.romanize import Romanizer, has_devanagari, script_ratio

log = logging.getLogger(__name__)


@dataclass
class Delivery:
    text: str
    raw: str                 # transcript before any processing
    app: str
    script: str              # latin | devanagari | n/a
    romanized: bool
    notes: list


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
        if forced in ("latin", "devanagari"):
            return forced

        if screen:
            existing = screen.focused_text or ""
            if len(existing.strip()) >= 8:
                return "devanagari" if script_ratio(existing) < 0.5 else "latin"
        return self.cfg.get("script", {}).get("default", "latin")

    # -------------------------------------------------------------- forward

    def process(self, transcript: str, screen: ctx_mod.ScreenContext | None = None,
                force_script: str | None = None) -> Delivery:
        app = (screen.app if screen else "") or ""
        profile = self.profiles.get(app)
        notes: list = []

        script = force_script or self.choose_script(app, screen)
        text = transcript
        romanized = False

        if has_devanagari(transcript) and script == "latin":
            lang = self.cfg.get("script", {}).get("language", "hi")
            r = Romanizer(lang, self.profiles.merged_conventions(app))
            r.remember_source(transcript)
            text = r.text(transcript)
            romanized = True
            self._romanizer = r

        text = profile.habits.apply(text)

        d = Delivery(text=text, raw=transcript, app=app, script=script,
                     romanized=romanized, notes=notes)
        self._last = d
        return d

    # -------------------------------------------------------------- reverse

    def learn_from_screen(self, screen: ctx_mod.ScreenContext | None) -> list:
        """Compare what we pasted with what is in the field now.

        Called at the START of the next dictation, which is the cheap moment to
        do it - no background watching, no keylogging, and the user is already
        in the same field.
        """
        if not self._last or not screen:
            return []
        current = (screen.focused_text or "").strip()
        if not current or current == self._last.text.strip():
            return []
        if self._last.text.strip() not in current and len(current) < 4:
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
