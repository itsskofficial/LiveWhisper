#!/usr/bin/env python
"""Emails from Ctrl+Alt+W are signed with the user's name.

Replies to an email stopped at one line - "Sure, I'll be there." - with no
greeting and no sign-off: the prompt said to leave the sign-off out without the
user's name, and nothing gave it the name. tests/bench_compose.py measures the
writing; this pins where the name comes from.

    python tests/test_compose_prompt.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper import actions  # noqa: E402
from livewhisper.console import setup as _console  # noqa: E402

_console()
fails = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    fails += not ok
    print(f"[{'  ok  ' if ok else ' FAIL '}] {name}" + (f"  {detail}" if detail else ""))


class Capture:
    """A provider that records the prompt instead of calling a model."""

    def __init__(self):
        self.system = ""

    def chat(self, system, user, temperature=0.3):
        self.system = system
        return "ok"


def main() -> int:
    print("=== who signs ===")
    check("the setting wins", actions.Actions({"sign_as": "Sarthak K"}).signer() == "Sarthak K")
    for login, want in (("Sarthak Karandikar", "Sarthak"), ("priya", "Priya"),
                        ("admin", ""), ("user1", ""), ("runneradmin", ""), ("", "")):
        got = actions.first_name_from_login(login)
        check(f"Windows login {login!r} signs as {want!r}", got == want, repr(got))
    real = actions.windows_first_name

    print("\n=== the prompt ===")
    a = actions.Actions({"sign_as": "Sarthak"})
    cap = Capture()
    a._provider = cap
    a.compose("reply saying I'll be there", actions.AppProfile(app="chrome.exe"))
    check("the name is in the prompt", "The user's name is Sarthak" in cap.system)
    check("emails are asked to greet and sign off", "Hi Ananya," in cap.system and "sign-off" in cap.system)
    check("chat replies are told to have neither", "A chat reply has neither" in cap.system)
    check("no unfilled template field", "{" not in cap.system, cap.system[-120:])

    b = actions.Actions({"sign_as": ""})
    actions.windows_first_name = lambda: ""
    cap = Capture()
    b._provider = cap
    b.compose("reply saying I'll be there", actions.AppProfile(app="chrome.exe"))
    actions.windows_first_name = real
    check("no name: a plain \"Thanks,\" and never a placeholder",
          '"Thanks," alone' in cap.system and "[Your Name]" in cap.system)

    print("\n=== an email reply is shaped as an email ===")
    mail = "Design review on Friday\nAnanya Rao <ananya@example.com> to me\nHi,\n\nCan you join?\n\nThanks,\nAnanya"
    check("a mail window is an email", actions.looks_like_email("hello", "chrome.exe", "Mail"))
    check("an address on screen is an email", actions.looks_like_email(mail))
    check("a chat is not", not actions.looks_like_email("#release Marcus: is it merged?", "slack.exe", "Slack"))
    check("sender from 'Name <address>'", actions.sender_first_name(mail) == "Ananya")
    check("sender from 'From:'", actions.sender_first_name("From: Priya Raghavan\nHi") == "Priya")
    got = actions.shape_email("Sure, will be there.", "Ananya", "Sarthak")
    check("greeting and sign-off added", got == "Hi Ananya,\n\nSure, will be there.\n\nThanks,\nSarthak", repr(got))
    got = actions.shape_email("Tonight, I'll send you the deck. Thanks, Priya.", "Priya", "Sarthak")
    check("a sign-off as the sender is replaced, not stacked",
          got.endswith("send you the deck.\n\nThanks,\nSarthak") and got.count("Thanks") == 1, repr(got))
    done = "Hi Ananya,\n\nI'll be there.\n\nBest,\nSarthak"
    check("a reply that is already an email is left alone", actions.shape_email(done, "Ananya", "Sarthak") == done)
    got = actions.shape_email("Thanks for the invite, I'll be there.", "Ananya", "Sarthak")
    check("thanks inside the message is kept", "Thanks for the invite, I'll be there." in got, repr(got))
    got = actions.shape_email("Sure.", "", "")
    check("no names known: plain greeting and sign-off, no placeholder",
          got == "Hi,\n\nSure.\n\nThanks," and "[" not in got, repr(got))

    print(f"\n{'all passed' if not fails else f'{fails} FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
