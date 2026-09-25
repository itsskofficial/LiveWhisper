#!/usr/bin/env python
"""Write mode sees the email it is replying to.

Replying to an email in Chrome, Ctrl+Alt+W wrote "Hi," with no name and a
reply that ignored the email: the app had read nothing. The empty reply box
reports U+FFFC, the object placeholder, and that counted as the focused
text, so the window's text was never used; and the walk stopped at depth 6,
while Chrome's page sits at depth 7. Found recording the demo.

    python tests/test_screen_reading.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper import actions, context  # noqa: E402
from livewhisper.console import setup as _console  # noqa: E402

_console()
fails = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    fails += not ok
    print(f"[{'  ok  ' if ok else ' FAIL '}] {name}" + (f"  {detail}" if detail else ""))


class Value:
    def __init__(self, v):
        self.Value = v


class Node:
    """Enough of a uiautomation control for context._walk and _element_text."""

    def __init__(self, kind="PaneControl", name="", value=None, children=()):
        self.ControlTypeName, self.Name, self._value, self._children = kind, name, value, list(children)

    def GetChildren(self):
        return self._children

    def GetValuePattern(self):
        if self._value is None:
            raise AttributeError
        return Value(self._value)

    def GetTextPattern(self):
        raise AttributeError


EMAIL = "Ananya Rao <ananya@example.com> · to me\nHi,\n\nCould you join the design review on Friday?\n\nThanks,\nAnanya"


def main() -> int:
    print("=== the empty reply box ===")
    check("U+FFFC is not text", context._element_text(Node("EditControl", value="￼")) == "")
    check("real text in a box is kept", context._element_text(Node("EditControl", value="see you")) == "see you")

    print("\n=== Chrome's page, deep in the tree ===")
    page = Node("DocumentControl", children=[Node("TextControl", name=EMAIL)])
    tree = page
    for _ in range(8):                 # Chrome: the document at depth 7, its text below it
        tree = Node(children=[tree])
    out: list = []
    context._walk(tree, out, depth=0)
    text = "\n".join(out)
    check("the email is read", "Ananya Rao <ananya@example.com>" in text, repr(text[:80]))

    ctx = context.ScreenContext(app="chrome.exe", title="Mail", text=text, focused_text="", method="uia")
    screen = context.relevant_text(ctx)
    check("the sender is found", actions.sender_first_name(screen) == "Ananya", repr(screen[:60]))

    print(f"\n{'all passed' if not fails else f'{fails} FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
