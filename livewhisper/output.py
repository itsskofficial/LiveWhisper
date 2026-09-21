"""Getting the finished text into whatever field currently has focus."""

from __future__ import annotations

import logging
import threading
import time

import keyboard
import pyperclip

log = logging.getLogger(__name__)

_MODIFIERS = ("ctrl", "alt", "shift", "windows")


class ClipboardBusy(RuntimeError):
    """Another app is holding the clipboard open; nothing could be pasted."""


def _copy(text: str, attempts: int = 6) -> None:
    """Put text on the clipboard, waiting out an app that has it open.

    Windows lets one process open the clipboard at a time, and clipboard
    managers, remote-desktop sessions and some editors hold it for a moment.
    One failed attempt used to be reported as a failed transcription.
    """
    delay = 0.03
    for i in range(attempts):
        try:
            pyperclip.copy(text)
            return
        except Exception:
            if i == attempts - 1:
                raise ClipboardBusy("the clipboard is in use by another app")
            time.sleep(delay)
            delay *= 2


def compose(prompt: str, transcript: str) -> str:
    """Prepend the active profile's prompt to the transcript."""
    prompt = (prompt or "").rstrip()
    if not prompt:
        return transcript
    return f"{prompt}\n\n{transcript}"


def _foreground() -> str:
    """The window a paste is about to land in, for the log."""
    try:
        from .context import foreground_app
        app, title = foreground_app()
        return f"{app or '?'} ({title[:40]!r})"
    except Exception:
        return "?"


def deliver(text: str, auto_paste: bool = True, copy_to_clipboard: bool = True,
            restore_clipboard: bool = False) -> tuple[bool, bool]:
    """Deliver `text`. Returns (pasted, left_on_clipboard).

    Pasting goes through the clipboard, so `copy_to_clipboard=False` with
    `auto_paste=True` still uses it briefly and then puts the old contents back.
    """
    if not text or not (auto_paste or copy_to_clipboard):
        return False, False

    # Restore whenever the user asked for it, or whenever we are only borrowing
    # the clipboard to perform a paste they did not want it kept for.
    restore = restore_clipboard or not copy_to_clipboard

    previous = None
    if restore:
        try:
            previous = pyperclip.paste()
        except Exception:
            log.warning("could not read existing clipboard", exc_info=True)

    _copy(text)

    pasted = False
    if auto_paste:
        # The record hotkey is Ctrl+Alt+<key>. If those are still physically
        # held, our synthetic Ctrl+V arrives as Ctrl+Alt+V and lands somewhere
        # unintended. Drop the modifiers first.
        for mod in _MODIFIERS:
            try:
                keyboard.release(mod)
            except Exception:
                pass
        time.sleep(0.08)
        try:
            target = _foreground()
            keyboard.send("ctrl+v")
            pasted = True
            log.info("pasted %d characters into %s", len(text), target)
        except Exception:
            log.error("auto-paste failed; text is on the clipboard", exc_info=True)

    if restore and previous is not None:
        # Give the target app time to actually read the clipboard first.
        threading.Timer(2.0, lambda: pyperclip.copy(previous)).start()
        return pasted, False

    return pasted, True
