#!/usr/bin/env python
"""Drive the wizard and settings window through their real flows.

Clicking through the widgets programmatically catches more than a screenshot
would: it proves the onboarding actually learns the right conventions, refuses
the unsafe ones, and that every setting is wired to a variable the save path
reads.

Runs against a throwaway profile, so your real one is never touched.

    python test_gui.py
"""
import sys
import tempfile
import tkinter as tk
from pathlib import Path

PROJ = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJ))

from livewhisper.main import App            # noqa: E402
from livewhisper.profile import ProfileStore  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {name}" + (f"  {detail}" if detail else ""))
    if not cond:
        failures.append(name)


app = App(PROJ / "config.yaml")
app.root = tk.Tk()
app.root.withdraw()

# isolate: never touch the real profile during the test
tmp = Path(tempfile.mkdtemp())
app.styles = ProfileStore(path=tmp / "profiles.json")

print("=== wizard ===")
from livewhisper.wizard import Wizard      # noqa: E402

from livewhisper.console import setup as _console

_console()

w = Wizard(app)
app.root.update()
check("wizard opens", w.winfo_exists())
check("has all five prompts", len(w.prompts) == 5, f"{len(w.prompts)}")
check("first sentence shown", bool(w.deva.cget("text")), w.deva.cget("text")[:40])

typed = [
    "muze kal office jana hai, too aa raha hai kya",
    "wo phir se der se aaya, bahut zyada time laga",
    "theek hai yaar, koi baat nahi, kal milte hain",
    "kaun sa chahiye tuze? kisi wajah se nahi aaya wo",
    "poora din kaam kiya phir bhi kuch nahi hua",
]
for i, t in enumerate(typed):
    w.entry.delete(0, "end")
    w.entry.insert(0, t)
    w._next()
    app.root.update()
    if i < len(typed) - 1:
        check(f"advanced to sentence {i + 2}", w.index == i + 1, f"index={w.index}")

check("finished after five", w.index == 5)

g = app.styles.get(ProfileStore.GLOBAL)
check("spelling conventions learned", bool(g.conventions.rules),
      str(g.conventions.rules))
check("jh -> z learned", g.conventions.rules.get("jh") == "z")
check("v -> w learned", g.conventions.rules.get("v") == "w")
check("no unsafe vowel rule", "u" not in g.conventions.rules,
      "u would break aur/bahut")
check("exact words remembered", len(g.conventions.overrides) >= 5,
      str(len(g.conventions.overrides)))
check("habits observed from typing", g.habits.samples >= 5,
      f"samples={g.habits.samples}")
check("lowercase habit detected", g.habits.capitalize < 0.3,
      f"capitalize={g.habits.capitalize:.2f}")
check("profile written to disk", app.styles.path.exists())

try:
    w.destroy()
except Exception:
    pass

print("\n=== settings window ===")
from livewhisper.gui import SECTIONS, SettingsWindow   # noqa: E402

s = SettingsWindow(app)
app.root.update()
check("settings opens", s.winfo_exists())
for name in SECTIONS:
    s._show(name)
    app.root.update()
    check(f"panel '{name}' renders", name in s._panels)

need = ["script.default", "script.language", "actions.models.provider",
        "actions.models.model", "actions.command_seconds",
        "context.ocr_fallback", "learning.enabled",
        "hotkeys.write", "hotkeys.fix", "hotkeys.notes", "hotkeys.devanagari"]
for k in need:
    check(f"setting exposed: {k}", k in s._vars)

s._show("Writing")
app.root.update()
learned = s._learned.get("1.0", "end").strip()
check("Writing panel lists what was learned", "jh -> z" in learned,
      learned.splitlines()[0] if learned else "empty")

# the destructive button, on the isolated copy only
s._forget()
app.root.update()
check("forget clears the rules",
      not app.styles.get(ProfileStore.GLOBAL).conventions.rules)

try:
    s.destroy()
except Exception:
    pass
app.root.destroy()

print()
if failures:
    print(f"{len(failures)} FAILED: {', '.join(failures)}")
    sys.exit(1)
print("all GUI flows passed")
