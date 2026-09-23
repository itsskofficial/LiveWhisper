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


COMPOSE_SYSTEM = """You write text for the user to send, as the user.

The screen shows what the user is looking at - usually a message someone else
sent them. The user tells you what to write back. You are the user replying:
never write as the other person, never address the user by name.

Rules:
- Output ONLY the finished text, ready to paste. No preamble ("Here's a
  draft"), no quotes around it, no explanation, no subject line.
- Match the register of the conversation on screen: a chat gets a chat reply,
  an email gets an email reply.
- An email reply is a whole email: a greeting with the sender's first name on
  its own line ("Hi Ananya,"), the message, then a sign-off on its own lines
  ("Thanks," and below it the user's name). A chat reply has neither.
- Keep the message itself as short as the situation allows.
- Never use placeholders like [Your Name] or [Date].
{name}
- If the instruction is in Hindi or Hinglish, write the reply in Hinglish,
  in Latin letters.
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


def windows_first_name() -> str:
    """The first word of the Windows account's display name, or ''."""
    try:
        import ctypes
        size = ctypes.c_ulong(256)
        buf = ctypes.create_unicode_buffer(size.value)
        # 3 = NameDisplay ("Sarthak Karandikar"); fails on some local accounts.
        if ctypes.windll.secur32.GetUserNameExW(3, buf, ctypes.byref(size)) and buf.value.strip():
            return buf.value.split()[0]
    except (AttributeError, OSError):
        pass
    import os
    return first_name_from_login(os.environ.get("USERNAME") or "")


def first_name_from_login(login: str) -> str:
    """A Microsoft-account login has no display name, but its user name is
    usually the person's name ("Sarthak Karandikar"); "admin" or "user1" is not."""
    words = login.split()
    if words and words[0].isalpha() and words[0].lower() not in (
            "admin", "administrator", "user", "owner", "pc", "runneradmin"):
        return words[0].capitalize()
    return ""


_ADDRESS = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_GREETING = re.compile(r"^(hi|hello|hey|dear|good (morning|afternoon|evening))\b", re.IGNORECASE)
_MAIL_APPS = ("outlook", "thunderbird", "mail", "gmail", "inbox")


def looks_like_email(screen_text: str, app: str = "", title: str = "") -> bool:
    """Is the thing being replied to an email, rather than a chat?"""
    where = f"{app} {title}".lower()
    return (any(m in where for m in _MAIL_APPS) or bool(_ADDRESS.search(screen_text or ""))
            or bool(re.search(r"^(from|subject):", screen_text or "", re.IGNORECASE | re.MULTILINE)))


def sender_first_name(screen_text: str) -> str:
    """Who wrote the email on screen: the From line, a 'Name <address>' line,
    or the name under their sign-off."""
    text = screen_text or ""
    m = re.search(r"^from:\s*([A-Z][\w'-]+)", text, re.IGNORECASE | re.MULTILINE)
    if m:
        return m.group(1).capitalize()
    m = re.search(r"^([A-Z][\w'-]+)(?:\s+[A-Z][\w'-]+)*\s*<[^>@]+@", text, re.MULTILINE)
    if m:
        return m.group(1)
    m = re.search(r"(?:thanks|regards|cheers|best)\s*,?\s*\n?\s*([A-Z][\w'-]+)\s*$", text.strip(),
                  re.IGNORECASE)
    return m.group(1).capitalize() if m else ""


def shape_email(reply: str, sender: str, signer: str) -> str:
    """An email reply gets a greeting and the user's sign-off, whatever the model did.

    The built-in writing model ignored the prompt's email rules on every email
    case of tests/bench_compose.py - "Sure, will be there." with no greeting,
    and once "Thanks, Priya", signing as the person being replied to."""
    lines = [ln.rstrip() for ln in reply.strip().splitlines()]
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return reply
    if not _GREETING.match(lines[0].strip()):
        lines = [f"Hi {sender}," if sender else "Hi,", ""] + lines
    last = lines[-1].strip()
    signed_by_user = bool(signer) and signer.lower() in last.lower()
    if not signed_by_user:
        # A sign-off the model already wrote - "Thanks!", or one signed with the
        # sender's name - is replaced rather than stacked under a second one,
        # whether it has a line of its own or ends the last sentence.
        lines[-1] = re.sub(r"(?<=[.!?])\s+(thanks|thank you|cheers|regards)[!.,]?(\s*,?\s*[A-Z][\w'-]*)?[.!]?$",
                           "", lines[-1], flags=re.IGNORECASE)
        last = lines[-1].strip()
        if re.fullmatch(r"(thanks|thank you|regards|best|cheers)[!.,]?(\s*,?\s*\w+)?[.!]?", last,
                        re.IGNORECASE):
            lines.pop()
            while lines and not lines[-1].strip():
                lines.pop()
        lines += ["", "Thanks,"] + ([signer] if signer else [])
    return "\n".join(lines)


class Actions:
    def __init__(self, cfg: dict):
        self.cfg = cfg or {}
        self._provider = None

    def signer(self) -> str:
        """Who emails from Ctrl+Alt+W are signed as.

        Replies stopped at one line - no "Hi Ananya," and no sign-off - because
        the prompt said to leave the sign-off out without the user's name, and
        nothing gave it the name."""
        return (self.cfg.get("sign_as") or "").strip() or windows_first_name()

    def provider(self):
        if self._provider is None:
            self._provider = providers.build(self.cfg.get("models", {}))
        return self._provider

    def reset(self) -> None:
        self._provider = None

    def unavailable(self) -> str | None:
        """Why Ctrl+Alt+W / Ctrl+Alt+F cannot run right now, or None if they can.

        Asked before listening, so the user learns about a missing model
        before speaking an instruction rather than after.
        """
        try:
            self.provider()
            return None
        except providers.ProviderError as e:
            self._provider = None
            return str(e)

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

        name = self.signer()
        signer = (f"- The user's name is {name}; sign emails with it." if name else
                  '- You do not know the user\'s name: end an email with "Thanks," alone.')
        out = self.provider().chat(
            COMPOSE_SYSTEM.format(style=style, name=signer), "\n".join(parts), temperature=0.4)
        if screen and looks_like_email(screen_text, screen.app, screen.title):
            out = shape_email(_unwrap(out, instruction), sender_first_name(screen_text), name)
        return out

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


_PLAIN = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                        "‐": "-", "‑": "-", " ": " ", " ": " "})


def _unwrap(out: str, original: str) -> str:
    """Models like to add quotes or a preamble even when told not to."""
    # Typeset punctuation reads as pasted-from-elsewhere in a chat box, and a
    # non-breaking hyphen ("stand‑up", from gpt-oss) does not search.
    out = out.translate(_PLAIN).strip()
    for prefix in ("Here's", "Here is", "Corrected:", "Output:", "Sure,"):
        if out.lower().startswith(prefix.lower()):
            nl = out.find("\n")
            out = out[nl + 1:].strip() if nl != -1 else out
    # A placeholder sign-off is worse than none: drop any line that is only one.
    out = "\n".join(line for line in out.splitlines()
                    if not re.fullmatch(r"\s*[-,]?\s*\[[^\]]{2,30}\]\s*", line))
    out = re.sub(r"\[[^\]\n]{0,40}\b(?:name|sign[- ]?off|signature|date|time|"
                 r"company|email|phone|placeholder)\b[^\]\n]{0,40}\]", " ", out,
                 flags=re.IGNORECASE)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"[ \t]+([,.!?])", r"\1", out).strip()
    # "Thanks, [Your Name]" leaves "Thanks," - end on the word instead.
    out = re.sub(r",\s*$", "", out)
    if len(out) > 1 and out[0] == out[-1] and out[0] in "\"'":
        inner = out[1:-1]
        if '"' not in inner and "'" not in inner:
            out = inner
    return out or original
