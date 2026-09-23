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
import os
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
    # This process's own window: FindWindowW by title found the installed
    # app's hidden 129x84 window instead whenever it was running.
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(h, _):
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        buf = ctypes.create_unicode_buffer(256)
        u.GetWindowTextW(h, buf, 256)
        if pid.value == os.getpid() and buf.value == TITLE and u.IsWindowVisible(h):
            found.append(h)
        return True

    u.EnumWindows(each, 0)

    def area(h):
        r = wintypes.RECT()
        u.GetWindowRect(h, ctypes.byref(r))
        return (r.right - r.left) * (r.bottom - r.top)

    # The largest: this process also owns small hidden helper windows with the
    # same title, and which one EnumWindows reaches first varies between runs.
    hwnd = max(found, key=area) if found else u.FindWindowW(None, TITLE)
    r = wintypes.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    box = (r.left, r.top, r.right, r.bottom)
    shot = _print_window(hwnd, r.right - r.left, r.bottom - r.top)
    if shot is None:
        # PrintWindow gave nothing (it can, with hardware-composited content):
        # fall back to grabbing the screen, which needs the window in front.
        for _ in range(10):
            u.ShowWindow(hwnd, 9)              # SW_RESTORE
            u.BringWindowToTop(hwnd)
            u.SetForegroundWindow(hwnd)
            time.sleep(0.3)
            if u.GetForegroundWindow() == hwnd:
                break
        time.sleep(0.4)
        shot = ImageGrab.grab(bbox=box, all_screens=True)
    shot.save(path)


def _print_window(hwnd, width: int, height: int):
    """The window's own pixels, without bringing it to the front.

    Grabbing the screen instead caught whatever was on top when raising the
    window lost to Windows' foreground lock - once, the tester's mail.
    """
    from PIL import Image
    u, gdi = ctypes.windll.user32, ctypes.windll.gdi32
    src = u.GetWindowDC(hwnd)
    dc = gdi.CreateCompatibleDC(src)
    bmp = gdi.CreateCompatibleBitmap(src, width, height)
    gdi.SelectObject(dc, bmp)
    try:
        # 2 = PW_RENDERFULLCONTENT, which WebView2 needs
        if not u.PrintWindow(hwnd, dc, 2):
            return None
        buf = ctypes.create_string_buffer(width * height * 4)
        header = ctypes.c_buffer(40)
        ctypes.memmove(header, ctypes.c_int32(40), 4)
        info = (ctypes.c_int32 * 11)(40, width, -height, 1 | (32 << 16), 0, 0, 0, 0, 0, 0, 0)
        if not gdi.GetDIBits(dc, bmp, 0, height, buf, info, 0):
            return None
        image = Image.frombuffer("RGB", (width, height), buf, "raw", "BGRX", 0, 1)
        return None if not image.getbbox() else image
    finally:
        gdi.DeleteObject(bmp)
        gdi.DeleteDC(dc)
        u.ReleaseDC(hwnd, src)


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
