#!/usr/bin/env python
"""Does Write mode see the email in an ordinary Chrome or Edge window?

Opens a local email page in the browser with a fresh profile (no flags, no
extensions), reads the screen the way Ctrl+Alt+W does (context.capture), and
reports how much text came back, how long the read took, and whether the
sender was found. With --ocr it times the screenshot-OCR fallback on the same
window for comparison. Takes the foreground for about 10 s per trial.

    python tests/bench_browser_reading.py --browser chrome,edge --trials 3 [--ocr]

Chromium builds its page tree for UI Automation only when an accessibility
client is about; the result can differ between machines, so the report also
says whether any UIA client was listening (UiaClientsAreListening).
"""

from __future__ import annotations

import argparse
import ctypes
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uiautomation as auto  # noqa: E402

from livewhisper import actions, context  # noqa: E402
from livewhisper.console import setup as _console  # noqa: E402

_console()
BROWSERS = {"chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            "edge": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"}
PAGE = """<!doctype html><meta charset="utf-8"><title>Mail</title>
<body style="font:18px 'Segoe UI';margin:40px">
<h2>Design review on Friday</h2>
<div>Ananya Rao &lt;ananya@example.com&gt; &middot; to me</div>
<p>Hi,</p><p>Could you join the design review on Friday at 5 pm? We'll go through the new
onboarding screens and decide what ships next week.</p><p>Thanks,<br>Ananya</p>
<label>Reply</label><br><textarea id=r rows=8 cols=80 autofocus></textarea>"""
user32 = ctypes.windll.user32


def window(title: str, timeout: float = 20) -> int:
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def each(h, _):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(h, buf, 256)
            if buf.value == title and user32.IsWindowVisible(h):
                found.append(h)
            return True
        user32.EnumWindows(each, 0)
        if found:
            return found[0]
        time.sleep(0.3)
    raise RuntimeError("the browser window never appeared")


def front(h: int) -> bool:
    """Windows lets a process take the foreground only from the thread that
    has it, so borrow that thread's input for the switch."""
    me = ctypes.windll.kernel32.GetCurrentThreadId()
    for _ in range(10):
        if user32.GetForegroundWindow() == h:
            return True
        other = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
        user32.AttachThreadInput(me, other, True)
        user32.ShowWindow(h, 3)
        user32.BringWindowToTop(h)
        user32.SetForegroundWindow(h)
        user32.AttachThreadInput(me, other, False)
        time.sleep(0.25)
    return False


def trial(exe: str, page: Path, ocr: bool) -> dict:
    profile = tempfile.mkdtemp(prefix="lw_read_")
    proc = subprocess.Popen([exe, f"--app={page.as_uri()}", f"--user-data-dir={profile}", "--start-maximized",
                             "--no-first-run", "--no-default-browser-check"])
    out = {}
    try:
        h = window("Mail")
        time.sleep(2.0)
        if not front(h):
            return {"error": "could not bring the browser to the front"}
        t0 = time.perf_counter()
        while True:
            s = time.perf_counter()
            ctx = context.capture()
            took = time.perf_counter() - s
            sender = actions.sender_first_name(context.relevant_text(ctx))
            out.setdefault("first_chars", len(ctx.text))
            out.setdefault("read_s", round(took, 2))
            if sender == "Ananya" or time.perf_counter() - t0 > 6:
                out["sender_after_s"] = round(time.perf_counter() - t0, 1) if sender == "Ananya" else None
                break
            time.sleep(0.5)
        if ocr:
            s = time.perf_counter()
            text = context._ocr_read()
            out["ocr_s"] = round(time.perf_counter() - s, 2)
            out["ocr_sender"] = actions.sender_first_name(text)
    finally:
        subprocess.run(["powershell", "-c", "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "
                        f"'*{profile}*' }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force "
                        "-ErrorAction SilentlyContinue }"], capture_output=True)
        proc.wait(10)
        time.sleep(1.0)
        shutil.rmtree(profile, ignore_errors=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--browser", default="chrome,edge")
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--ocr", action="store_true", help="also time the OCR fallback (needs rapidocr_onnxruntime)")
    args = ap.parse_args()
    auto.GetRootControl()
    listening = bool(ctypes.windll.uiautomationcore.UiaClientsAreListening())
    print(f"UIA clients listening: {listening}")
    with tempfile.TemporaryDirectory() as d:
        page = Path(d) / "mail.html"
        page.write_text(PAGE, encoding="utf-8")
        for name in args.browser.split(","):
            exe = BROWSERS[name]
            ver = subprocess.run(["powershell", "-c", f"(Get-Item '{exe}').VersionInfo.ProductVersion"],
                                 capture_output=True, text=True).stdout.strip()
            print(f"\n=== {name} {ver} ===")
            for n in range(args.trials):
                print(f"  trial {n}: {trial(exe, page, args.ocr)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
