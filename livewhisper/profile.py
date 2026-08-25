"""Per-app writing profile: how you write, learned from what you change.

Wispr Flow does read your edits, but its documentation says it deliberately
discards "capitalization-only changes" and style fixes - it keeps only
vocabulary. A word->word dictionary has nowhere to store "don't capitalise in
WhatsApp but do in Outlook", so their data model cannot express style even if
they wanted to.

This is that missing piece: a profile per application, holding
  - orthographic habits (capitalisation, terminal punctuation) as observed rates
  - romanization conventions (letter-level, from livewhisper.script)
  - vocabulary

It is plain readable JSON, not model weights. You can open it, edit it, or
delete it, and one correction takes effect immediately.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .script.conventions import Conventions

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "profiles.json"

MIN_SAMPLES = 3          # before a habit is trusted enough to apply
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


@dataclass
class Habits:
    """Observed rates, not settings. 0.04 means 4% of your sentences do this."""

    capitalize: float = 1.0
    terminal_period: float = 1.0
    samples: int = 0

    def observe(self, text: str) -> None:
        sentences = [s for s in SENT_SPLIT.split(text.strip()) if s.strip()]
        if not sentences:
            return
        caps = sum(1 for s in sentences if s[:1].isupper())
        cap_rate = caps / len(sentences)
        period = 1.0 if text.rstrip().endswith((".", "!", "?")) else 0.0

        # Running mean, so recent evidence moves it without erasing history.
        n = self.samples
        self.capitalize = (self.capitalize * n + cap_rate) / (n + 1)
        self.terminal_period = (self.terminal_period * n + period) / (n + 1)
        self.samples = n + 1

    @property
    def trusted(self) -> bool:
        return self.samples >= MIN_SAMPLES

    def apply(self, text: str) -> str:
        """Reshape output to match the habits, once there is enough evidence."""
        if not self.trusted or not text.strip():
            return text
        out = text
        if self.capitalize < 0.25:
            out = out.lower()
        if self.terminal_period < 0.25:
            out = re.sub(r"[.]+\s*$", "", out).rstrip()
        return out

    def to_dict(self) -> dict:
        return {"capitalize": round(self.capitalize, 3),
                "terminal_period": round(self.terminal_period, 3),
                "samples": self.samples}

    @classmethod
    def from_dict(cls, d: dict | None) -> "Habits":
        d = d or {}
        return cls(capitalize=float(d.get("capitalize", 1.0)),
                   terminal_period=float(d.get("terminal_period", 1.0)),
                   samples=int(d.get("samples", 0)))


@dataclass
class AppProfile:
    app: str
    habits: Habits = field(default_factory=Habits)
    conventions: Conventions = field(default_factory=Conventions)
    vocabulary: dict = field(default_factory=dict)
    script: str | None = None        # "latin" | "devanagari" | None = auto

    def to_dict(self) -> dict:
        return {"habits": self.habits.to_dict(),
                "conventions": self.conventions.to_dict(),
                "vocabulary": dict(self.vocabulary),
                "script": self.script}

    @classmethod
    def from_dict(cls, app: str, d: dict) -> "AppProfile":
        return cls(app=app,
                   habits=Habits.from_dict(d.get("habits")),
                   conventions=Conventions.from_dict(d.get("conventions")),
                   vocabulary=dict(d.get("vocabulary") or {}),
                   script=d.get("script"))


class ProfileStore:
    """All app profiles, plus a global one used as the fallback."""

    GLOBAL = "_global"

    def __init__(self, path: Path = STORE):
        self.path = path
        self.profiles: dict[str, AppProfile] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.profiles = {k: AppProfile.from_dict(k, v) for k, v in raw.items()}
            log.info("loaded %d app profiles", len(self.profiles))
        except Exception:
            log.warning("could not read %s", self.path, exc_info=True)

    def save(self) -> None:
        try:
            data = {k: v.to_dict() for k, v in self.profiles.items()}
            self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                                 encoding="utf-8")
        except Exception:
            log.warning("could not write %s", self.path, exc_info=True)

    def get(self, app: str | None) -> AppProfile:
        key = (app or self.GLOBAL).lower()
        if key not in self.profiles:
            self.profiles[key] = AppProfile(app=key)
        return self.profiles[key]

    def merged_conventions(self, app: str | None) -> Conventions:
        """App rules layered over global ones, so a habit learned anywhere helps."""
        g = self.get(self.GLOBAL).conventions
        a = self.get(app).conventions
        out = Conventions(rules=dict(g.rules), overrides=dict(g.overrides),
                          evidence={k: set(v) for k, v in g.evidence.items()})
        out.rules.update(a.rules)
        out.overrides.update(a.overrides)
        for k, v in a.evidence.items():
            out.evidence.setdefault(k, set()).update(v)
        return out

    def learn_correction(self, app: str | None, notes_target: str,
                         native: str, default: str, corrected: str) -> list[str]:
        """Spelling corrections are learned globally - how you spell ज does not
        change between apps - while habits stay per app."""
        return self.get(self.GLOBAL).conventions.learn(native, default, corrected)

    def observe_text(self, app: str | None, text: str) -> None:
        self.get(app).habits.observe(text)
