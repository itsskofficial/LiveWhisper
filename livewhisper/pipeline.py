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
import time
from dataclasses import dataclass

from . import context as ctx_mod
from . import format as fmt_mod
from . import llm_format, vocab
from .cleanup import remove_fillers
from .profile import ProfileStore
from .script import conventions as conv_mod
from .script.languages import (DEFAULT, has_indic, languages_for_script,
                               supported)
from .script.respell import respell
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
    style: str = "prose"          # formatting the target app asked for
    formatted_by: str = "rules"   # model | rules | shortcut | none


class Pipeline:
    def __init__(self, cfg: dict, profiles: ProfileStore):
        self.cfg = cfg
        self.profiles = profiles
        self._last: Delivery | None = None
        self._formatter = None
        self._formatter_key = None
        self._formatter_seen = (0.0, False)

    # ----------------------------------------------------------- formatter

    # How often to look again for the formatting model. Ollama being closed
    # must cost a dictation nothing, and being opened later must be noticed.
    FORMATTER_RECHECK_S = 60.0

    def formatter(self):
        """The small-model formatter when configured and reachable, else None."""
        fmt_cfg = ((self.cfg.get("output") or {}).get("format") or {})
        key = repr(sorted((k, str(v)) for k, v in fmt_cfg.items() if k != "shortcuts"))
        if key != self._formatter_key:
            self._formatter_key = key
            self._formatter = llm_format.build(fmt_cfg, self.profiles.path.parent)
            self._formatter_seen = (0.0, False)
        if self._formatter is None:
            return None
        checked, ok = self._formatter_seen
        if time.monotonic() - checked > self.FORMATTER_RECHECK_S:
            try:
                ok = bool(self._formatter.backend.available())
            except Exception:
                ok = False
            self._formatter_seen = (time.monotonic(), ok)
        return self._formatter if ok else None

    def warm_formatter(self) -> None:
        """Load the formatting model now, off the path anyone waits on."""
        model = self.formatter()
        warm = getattr(getattr(model, "backend", None), "warm", None)
        if warm:
            warm()

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

        The script in front of us decides, because it is the only hard evidence
        available. A setting and a language detector are both opinions about the
        audio; the text is a fact.

        This used to return the configured language outright, and the shipped
        config sets `language: hi`. So Tamil audio - which Whisper transcribed
        into correct Tamil script, having correctly detected Tamil - was handed to
        the Hindi lexicon, which found no Devanagari and passed the Tamil through
        untouched. The user got raw Tamil script, the exact thing this app exists
        to prevent, in five of twelve languages. Measured in tests/test_audio_e2e.py.

        Only Devanagari (Hindi/Marathi) and Arabic (Urdu/Sindhi) are shared
        between two languages. There the configured language wins, since the user
        told us explicitly, then Whisper's guess, then the more spoken of the two.
        """
        configured = (self.cfg.get("script", {}) or {}).get("language", "auto")
        configured = configured if (configured and configured != "auto"
                                    and supported(configured)) else None
        heard = heard if (heard and supported(heard)) else None

        candidates = languages_for_script(transcript)
        if not candidates:
            # No native script, so nothing will be looked up anyway.
            return configured or heard or DEFAULT
        if len(candidates) == 1:
            return candidates[0]
        if configured in candidates:
            return configured
        if heard in candidates:
            return heard
        return candidates[0]

    # A transcript can hold more than one script. Whisper does this on its own:
    # asked for Marathi it has returned Gurmukhi with a stray Devanagari letter
    # left in, and a Hindi transcript can carry a Bengali name. The main
    # romanizer only knows one script, so whatever it does not recognise would
    # reach the user as raw native characters. Two extra passes clear
    # essentially all of it without letting a pathological input loop.
    LEFTOVER_PASSES = 2

    def _romanize_leftovers(self, text: str, app: str, exclude: str) -> str:
        """Romanize native-script runs the main language could not read.

        Deliberately does not touch self._romanizer or the learning path: these
        are scraps from a misfired transcription, not something the user's
        spelling preferences should be inferred from.
        """
        for _ in range(self.LEFTOVER_PASSES):
            if not has_indic(text):
                return text
            others = [c for c in languages_for_script(text, include_minor=True)
                      if c != exclude]
            if not others:
                break
            text = Romanizer(others[0]).text(text)
        if has_indic(text):
            # Whatever script is still left - one no lexicon recognised - is
            # spelled letter by letter. Native script is never pasted into a
            # field that asked for Latin.
            from .script.letters import spell_text
            text = spell_text(text)
        return text

    def process(self, transcript: str, screen: ctx_mod.ScreenContext | None = None,
                force_script: str | None = None,
                heard_language: str | None = None,
                latin_output: bool = False, composed: bool = False) -> Delivery:
        """`composed`: the text was written by a model, not spoken, so the
        spoken-word passes - fillers, spoken punctuation, corrections - must
        not run on it."""
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
            text = self._romanize_leftovers(text, app, exclude=lang)
        elif (latin_output and script == "latin" and heard_language
              and supported(heard_language)):
            # A Hinglish speech model already wrote Latin text. Nothing to
            # romanize, but its long-vowel spellings (saamaan, vaala) are not
            # how people type. Gated on latin_output because the same rule run
            # over ordinary English could turn an unattested word into a Hindi
            # one.
            lang = heard_language
            text = respell(transcript, lang)

        out_cfg = self.cfg.get("output") or {}
        if out_cfg.get("remove_fillers", True) and not composed:
            text = remove_fillers(text)

        vocabulary = (self.cfg.get("transcription") or {}).get("vocabulary") or ""
        if vocabulary and not composed:
            text = vocab.apply(text, vocabulary)

        # Formatting runs before habits, not after: habits are what this user
        # does that the rules do not know about, so they get the last word.
        fmt_cfg = out_cfg.get("format") or {}
        style = fmt_mod.style_for(app, override=profile.style or fmt_cfg.get("style"),
                                  cfg=fmt_cfg)
        formatted_by = "none"
        if fmt_cfg.get("enabled", True) and not composed:
            expansion = fmt_mod.shortcut(text, fmt_cfg.get("shortcuts"))
            # Native script stays with the rules: the model is prompted for
            # Latin text, and a Devanagari reply has no capitals to add.
            model = (self.formatter()
                     if expansion is None and not has_indic(text) else None)
            if expansion is not None:
                text, formatted_by = expansion, "shortcut"
            elif model is not None:
                text = model.format(text, style.name, rules_style=style)
                formatted_by = "model" if model.last_reason == "ok" else "rules"
                if formatted_by == "rules":
                    log.info("formatted by rules: %s", model.last_reason)
            else:
                text, formatted_by = fmt_mod.finish(text, style), "rules"
        text = profile.habits.apply(text)

        d = Delivery(text=text, raw=transcript, app=app, script=script,
                     romanized=romanized, notes=notes, language=lang,
                     style=style.name, formatted_by=formatted_by)
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
