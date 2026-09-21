#!/usr/bin/env python
"""Open the real app window, visit every page, screenshot each, report JS errors.

The window runs against the real Api (config, history, components), so this
checks the page and the bridge together. It never records audio or registers
hotkeys.

    python tests/ui_tour.py [out_dir] [--onboarding] [--dark|--light]
"""

from __future__ import annotations

import ctypes
import json
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import webview  # noqa: E402
from PIL import ImageGrab  # noqa: E402

from livewhisper import paths  # noqa: E402
from livewhisper.main import App  # noqa: E402
from livewhisper.window import TITLE, AppWindow  # noqa: E402

PAGES = ["home", "history", "dictionary", "languages", "ai", "settings"]


def grab(path: Path) -> None:
    u = ctypes.windll.user32
    hwnd = u.FindWindowW(None, TITLE)
    u.SetForegroundWindow(hwnd)
    time.sleep(0.5)
    r = wintypes.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom), all_screens=True).save(path)


def demo_history(app) -> None:
    """A few days of believable dictations, for screenshots."""
    import time as _t
    now = _t.time()
    samples = [
        (0.1, "Hey Priya, just checking if the report is ready. I need it before tomorrow's call.", "slack.exe", "en"),
        (0.3, "kal main office thoda late aaunga, traffic bahut hai", "whatsapp.exe", "hi"),
        (2, "Thanks everyone for joining today. We covered the roadmap for next quarter.", "outlook.exe", "en"),
        (5, "Tasks for tomorrow:\n- Fix the login bug\n- Update the docs\n- Ship the release",
         "notion.exe", "en"),
        (26, "naan naalaikku varuven, konjam late aagum", "whatsapp.exe", "ta"),
        (30, "Can you send me the latest numbers when you get a chance?", "chrome.exe", "en"),
    ]
    for hours, text, exe, lang in samples:
        e = app.history.add(text, max(2.0, len(text.split()) / 2.6), app=exe, language=lang)
        e["ts"] = now - hours * 3600
    entries = list(reversed(app.history.entries()))
    for (hours, *_), e in zip(samples, entries):
        e["ts"] = now - hours * 3600
    app.history._rewrite(entries)


def main() -> int:
    ctypes.windll.user32.SetProcessDPIAware()
    out = Path(next((a for a in sys.argv[1:] if not a.startswith("--")), "build/ui_tour"))
    out.mkdir(parents=True, exist_ok=True)
    app = App(paths.ensure_config())
    if "--demo" in sys.argv:
        demo_history(app)
    if "--onboarding" not in sys.argv:
        app.cfg.setdefault("ui", {})["onboarded"] = True     # in memory only
    win = AppWindow(app)
    app.window = win
    errors = []
    app_js_error = win.api.js_error
    win.api.js_error = lambda m: (errors.append(m), app_js_error(m))

    def tour():
        time.sleep(2)
        win.window.show()
        theme = "dark" if "--dark" in sys.argv else "light" if "--light" in sys.argv else ""
        if theme:
            win.window.evaluate_js(f"document.documentElement.dataset.theme = '{theme}'")
        time.sleep(3)
        if "--onboarding" in sys.argv:
            for step in range(4):
                win.window.evaluate_js(f"onboarding({step})")
                time.sleep(2)
                grab(out / f"onboarding_{step}.png")
        else:
            for p in PAGES:
                win.window.evaluate_js(f"lw.go('{p}')")
                time.sleep(2.2)
                grab(out / f"{p}.png")
        print(json.dumps({"errors": errors, "shots": sorted(x.name for x in out.glob("*.png"))}))
        win.destroy()

    webview.start(tour, gui="edgechromium")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
