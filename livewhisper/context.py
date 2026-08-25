"""Reading the screen: which app has focus, and what text is in it.

Two mechanisms, in order of preference:

  UI Automation - Windows' accessibility layer, built for screen readers. Well
      behaved apps expose their content as a tree of elements with real text.
      ~50ms, exact, free. This is the same permission Wispr Flow requests, and
      it grants reading as well as writing.

  OCR fallback - Chrome and Electron apps (Slack, Discord, web Gmail) only
      expose their content when a screen reader is detected, so for those we
      screenshot and recognise. Slower and structureless, but works anywhere.

This capability serves three features at once: reading an email to reply to,
reading text you typed so grammar can check it, and reading back what you
edited so the app can learn your style.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)

user32 = ctypes.windll.user32
MAX_CONTEXT_CHARS = 6000


@dataclass
class ScreenContext:
    app: str                  # "outlook.exe"
    title: str
    text: str                 # what we could read, possibly empty
    focused_text: str         # just the field under the cursor
    method: str               # uia | ocr | none


def foreground_app() -> tuple[str, str]:
    """(process name, window title) of whatever the user is looking at."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "", ""

    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    title = buf.value

    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    name = ""
    try:
        import psutil  # noqa
        name = psutil.Process(pid.value).name()
    except Exception:
        # psutil is optional; fall back to the Win32 API directly.
        try:
            PROCESS_QUERY_LIMITED = 0x1000
            h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED, False,
                                                   pid.value)
            if h:
                b = ctypes.create_unicode_buffer(512)
                size = ctypes.c_ulong(512)
                ctypes.windll.kernel32.QueryFullProcessImageNameW(
                    h, 0, b, ctypes.byref(size))
                ctypes.windll.kernel32.CloseHandle(h)
                name = b.value.rsplit("\\", 1)[-1]
        except Exception:
            log.debug("could not resolve process name", exc_info=True)
    return name.lower(), title


# --------------------------------------------------------------------- UIA

def _uia_read() -> tuple[str, str]:
    """(whole-window text, focused-element text) via UI Automation."""
    try:
        import uiautomation as auto
    except ImportError:
        return "", ""

    whole = focused = ""
    try:
        auto.SetGlobalSearchTimeout(1.0)
        el = auto.GetFocusedControl()
        if el:
            focused = _element_text(el)
        win = auto.GetForegroundControl()
        if win:
            parts: list[str] = []
            _walk(win, parts, depth=0)
            whole = "\n".join(p for p in parts if p.strip())[:MAX_CONTEXT_CHARS]
    except Exception:
        log.debug("uia read failed", exc_info=True)
    return whole, focused


def _element_text(el) -> str:
    for getter in ("GetValuePattern", "GetTextPattern"):
        try:
            pat = getattr(el, getter)()
            if getter == "GetValuePattern":
                v = pat.Value
            else:
                v = pat.DocumentRange.GetText(MAX_CONTEXT_CHARS)
            if v:
                return v
        except Exception:
            continue
    try:
        return el.Name or ""
    except Exception:
        return ""


def _walk(el, out: list, depth: int, budget: int = 220) -> None:
    """Shallow breadth-limited walk - deep trees are slow and mostly chrome."""
    if depth > 6 or len(out) > budget:
        return
    try:
        for child in el.GetChildren():
            t = ""
            try:
                if child.ControlTypeName in ("TextControl", "EditControl",
                                             "DocumentControl", "ListItemControl"):
                    t = _element_text(child)
            except Exception:
                pass
            if t and t.strip():
                out.append(t.strip())
            _walk(child, out, depth + 1, budget)
            if len(out) > budget:
                return
    except Exception:
        return


# --------------------------------------------------------------------- OCR

def _ocr_read() -> str:
    """Screenshot the foreground window and recognise the text.

    Optional dependency. Only needed for Chrome/Electron apps that do not
    expose their content through UI Automation.
    """
    try:
        from rapidocr_onnxruntime import RapidOCR
        from PIL import ImageGrab
    except ImportError:
        log.debug("rapidocr not installed - no OCR fallback")
        return ""
    try:
        hwnd = user32.GetForegroundWindow()
        rect = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
        result, _ = RapidOCR()(img)
        if not result:
            return ""
        return "\n".join(line[1] for line in result)[:MAX_CONTEXT_CHARS]
    except Exception:
        log.debug("ocr read failed", exc_info=True)
        return ""


# ------------------------------------------------------------------ public

def capture(use_ocr: bool = False) -> ScreenContext:
    """Read the foreground window. Called only on an explicit hotkey."""
    app, title = foreground_app()
    whole, focused = _uia_read()
    method = "uia" if (whole or focused) else "none"

    if not whole and use_ocr:
        whole = _ocr_read()
        method = "ocr" if whole else method

    return ScreenContext(app=app, title=title, text=whole,
                         focused_text=focused, method=method)


def relevant_text(ctx: ScreenContext, limit: int = 3000) -> str:
    """Trim window content down to something worth sending to a model."""
    text = ctx.focused_text or ctx.text
    if not text:
        return ""
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) <= limit:
        return text
    # Keep the end: in a reply the most recent message is usually last.
    return "..." + text[-limit:]
