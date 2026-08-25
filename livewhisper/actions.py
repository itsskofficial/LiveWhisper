"""What the app does with your voice besides typing it out.

    compose  - "write a reply saying I can't make Thursday" -> reads the email
               on screen, writes the reply in your style
    fix      - grammar and clarity pass over text already in the field
    rewrite  - "make this shorter", "more formal"

All three share the same shape: read the screen, ask a model, return text. The
style profile is injected as few-shot guidance rather than a tone slider, so
output follows the habits actually observed from your writing.
"""

from __future__ import annotations

import logging
import re

from . import context as ctx_mod
from . import providers
from .profile import AppProfile

log = logging.getLogger(__name__)

# Spoken phrases that mean "do something" rather than "type this".
COMMAND_HINTS = re.compile(
    r"^\s*(write|draft|reply|respond|answer|summar|rewrite|make (it|this)|"
    r"shorten|expand|translate|fix|correct|turn (this|it) into|compose)\b",
    re.IGNORECASE)


def looks_like_command(text: str) -> bool:
    """Cheap intent check so plain dictation is never sent to a model."""
    return bool(COMMAND_HINTS.match(text.strip()))


def _style_brief(profile: AppProfile) -> str:
    """Describe the user's observed habits to the model in plain terms."""
    h = profile.habits
    bits = []
    if h.trusted:
        if h.capitalize < 0.25:
            bits.append("writes in all lowercase, does not capitalise sentences")
        elif h.capitalize > 0.8:
            bits.append("capitalises sentences normally")
        if h.terminal_period < 0.25:
            bits.append("does not end messages with a full stop")
    if not bits:
        return ""
    # Deliberately NOT mentioning romanization rules here. Telling the model
    # "this person spells jh as z" makes it answer in Hinglish even when the
    # instruction was English. Spelling is applied afterwards by the romanizer,
    # which is the correct place for it.
    return "The person you are writing as: " + "; ".join(bits) + "."


COMPOSE_SYSTEM = """You write on behalf of the user, in their voice.

Rules:
- Output ONLY the finished text. No preamble, no "Here's a draft:", no quotes
  around it, no explanation.
- Match the register of the surrounding context and of the user's own style.
- Keep it about as long as the situation needs. Do not pad.
- If the user's instruction is in Hindi/Hinglish, answer in the same mix they use.
{style}"""


FIX_SYSTEM = """You correct grammar, spelling and punctuation.

Rules:
- Output ONLY the corrected text. Nothing else.
- Change as little as possible. Do not rewrite, restructure, or improve style.
- Preserve the writer's voice exactly, including deliberate informality,
  lowercase, slang, and romanised Hindi or Marathi spellings. Those are not
  errors.
- If the text is already correct, output it unchanged."""


REWRITE_SYSTEM = """You rewrite text as instructed.

Rules:
- Output ONLY the rewritten text.
- Follow the instruction exactly and change nothing else.
- Preserve the writer's voice and any romanised Hindi or Marathi spellings.
{style}"""


class Actions:
    def __init__(self, cfg: dict):
        self.cfg = cfg or {}
        self._provider = None

    def provider(self):
        if self._provider is None:
            self._provider = providers.build(self.cfg.get("models", {}))
        return self._provider

    def reset(self) -> None:
        self._provider = None

    # ------------------------------------------------------------ compose

    def compose(self, instruction: str, profile: AppProfile,
                screen: ctx_mod.ScreenContext | None = None) -> str:
        screen_text = ctx_mod.relevant_text(screen) if screen else ""
        style = _style_brief(profile)

        parts = []
        if screen_text:
            parts.append("What is on screen right now:\n"
                         "-----\n" + screen_text + "\n-----\n")
        parts.append(f"Instruction: {instruction}")
        if screen_text:
            parts.append("\nWrite the text the instruction asks for, using the "
                         "screen content above as the thing being responded to.")

        return self.provider().chat(
            COMPOSE_SYSTEM.format(style=style), "\n".join(parts), temperature=0.4)

    # ---------------------------------------------------------------- fix

    def fix(self, text: str) -> str:
        if not text.strip():
            return text
        out = self.provider().chat(FIX_SYSTEM, text, temperature=0.0)
        return _unwrap(out, text)

    # ------------------------------------------------------------ rewrite

    def rewrite(self, text: str, instruction: str, profile: AppProfile) -> str:
        out = self.provider().chat(
            REWRITE_SYSTEM.format(style=_style_brief(profile)),
            f"Instruction: {instruction}\n\nText:\n{text}", temperature=0.3)
        return _unwrap(out, text)


def _unwrap(out: str, original: str) -> str:
    """Models like to add quotes or a preamble even when told not to."""
    out = out.strip()
    for prefix in ("Here's", "Here is", "Corrected:", "Output:", "Sure,"):
        if out.lower().startswith(prefix.lower()):
            nl = out.find("\n")
            out = out[nl + 1:].strip() if nl != -1 else out
    if len(out) > 1 and out[0] == out[-1] and out[0] in "\"'":
        inner = out[1:-1]
        if '"' not in inner and "'" not in inner:
            out = inner
    return out or original
