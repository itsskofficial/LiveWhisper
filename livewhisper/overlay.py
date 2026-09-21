"""The floating recording pill.

    recording   ✕  ▁▃▆▃▂▅▇▅▂  ✓     live waveform; ✕ discards, ✓ finishes
    working          • • •          while the words are transcribed and pasted
    message     Nothing was heard   a short note in place of a toast

A per-pixel-alpha layered window rendered with Pillow, on its own thread with
its own message loop, so it has anti-aliased edges and a soft shadow and keeps
animating while the Tk thread is busy. It is created WS_EX_NOACTIVATE and
answers MA_NOACTIVATE: clicking it never takes focus away from the field the
words are going to. It opens bottom-centre on the monitor you are working on;
drag it anywhere and it stays there.

Every public method is safe to call from any thread.
"""

from __future__ import annotations

import ctypes
import logging
import math
import queue
import threading
import time
from ctypes import wintypes
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

log = logging.getLogger(__name__)

# ---------------------------------------------------------------- the look

BG = (17, 17, 19, 238)
EDGE = (255, 255, 255, 26)
WAVE = (245, 245, 247)
WAVE_COMMAND = (180, 160, 255)
BUTTON = (255, 255, 255, 30)
BUTTON_HOT = (255, 255, 255, 56)
ICON = (225, 225, 230)
DONE = (255, 255, 255)
DONE_ICON = (17, 17, 19)
TEXT = (235, 235, 240)

H = 40                    # logical pixels; scaled by the monitor's DPI
W_RECORD = 188
W_WORK = 76
BUTTON_R = 13
BARS = 17
MARGIN = 14               # room for the shadow around the pill
SS = 3                    # supersampling factor for smooth edges
FPS = 30
FADE_S = 0.16
MESSAGE_S = 2.4

# ------------------------------------------------------------------- win32

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)

WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WM_DESTROY, WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0002, 0x0200, 0x0201, 0x0202
WM_MOUSEACTIVATE, WM_SETCURSOR, WM_NCHITTEST = 0x0021, 0x0020, 0x0084
WM_EXITSIZEMOVE, WM_MOUSELEAVE, WM_DPICHANGED, WM_APP = 0x0232, 0x02A3, 0x02E0, 0x8000
MA_NOACTIVATE, HTCLIENT, HTCAPTION = 3, 1, 2
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
ULW_ALPHA, AC_SRC_ALPHA = 2, 1
PM_REMOVE, QS_ALLINPUT, WAIT_TIMEOUT = 1, 0x04FF, 0x102
TME_LEAVE = 2
IDC_ARROW, IDC_HAND = 32512, 32649
MONITOR_DEFAULTTONEAREST, MONITOR_DEFAULTTONULL = 2, 0


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


class TRACKMOUSEEVENT(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("hwndTrack", wintypes.HWND), ("dwHoverTime", wintypes.DWORD)]


user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                   wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                   wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
user32.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT),
                                       ctypes.POINTER(wintypes.SIZE), wintypes.HDC,
                                       ctypes.POINTER(wintypes.POINT), wintypes.COLORREF,
                                       ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, wintypes.LPVOID]
user32.LoadCursorW.restype = wintypes.HANDLE
user32.SetCursor.argtypes = [wintypes.HANDLE]
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HANDLE
user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
user32.MonitorFromPoint.restype = wintypes.HANDLE
user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.MsgWaitForMultipleObjects.argtypes = [wintypes.DWORD, wintypes.LPVOID, wintypes.BOOL,
                                             wintypes.DWORD, wintypes.DWORD]
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT,
                                wintypes.UINT, wintypes.UINT]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.TrackMouseEvent.argtypes = [ctypes.POINTER(TRACKMOUSEEVENT)]
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFOHEADER), wintypes.UINT,
                                   ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


def _lo(v: int) -> int:
    return ctypes.c_short(v & 0xFFFF).value


def _hi(v: int) -> int:
    return ctypes.c_short((v >> 16) & 0xFFFF).value


def _font(size: float, bold: bool = False):
    fonts = Path(r"C:\Windows\Fonts")
    for name in (("seguisb.ttf", "segoeuib.ttf") if bold else ("segoeui.ttf",)):
        try:
            return ImageFont.truetype(str(fonts / name), int(size))
        except OSError:
            continue
    return ImageFont.load_default()


def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


# ------------------------------------------------------------------ the pill

class RecordingOverlay:
    """recording -> working -> gone, or a message in between."""

    def __init__(self, on_stop, on_cancel, position=None, on_move=None):
        self.on_stop = on_stop
        self.on_cancel = on_cancel
        self.on_move = on_move
        self.position = position          # [x, y] of the pill's top-left, or None
        self._q: queue.Queue = queue.Queue()
        self._hwnd = None
        self._ready = threading.Event()

        # State below is owned by the overlay thread.
        self.mode = "hidden"              # hidden | recording | working | message
        self.command = False
        self.level_fn = None
        self.text = ""
        self._levels = [0.0] * BARS
        self._smooth = 0.0
        self._t0 = time.monotonic()
        self._shown_at = 0.0
        self._closing_at = None
        self._message_until = 0.0
        self._return_to = None            # what a message gives way to
        self._width = float(W_RECORD)
        self._hot = None                  # "cancel" | "done" | None
        self._scale = 1.0
        self._anchor = None               # bottom-centre point, physical pixels
        self._tracking = False
        self._shadow_cache: dict = {}
        self._origin = (0, 0, 0, 0)
        self._thread = threading.Thread(target=self._run, name="overlay", daemon=True)
        self._thread.start()
        if not self._ready.wait(3) or not self._hwnd:
            raise RuntimeError("the recording overlay window could not be created")

    # ------------------------------------------------ public, any thread

    def show(self, level_fn=None, command: bool = False) -> None:
        self._send("show", level_fn, command)

    def working(self) -> None:
        self._send("working")

    def message(self, text: str) -> None:
        self._send("message", text)

    def hide(self) -> None:
        self._send("hide")

    def close(self) -> None:
        self._send("close")

    # Older callers fed the level in themselves.
    def update(self, elapsed: float, level: float) -> None:  # noqa: ARG002
        self._send("level", level)

    def _send(self, *cmd) -> None:
        self._q.put(cmd)
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_APP, 0, 0)

    # --------------------------------------------------- overlay thread

    def _run(self) -> None:
        try:
            # Per-monitor DPI for this thread only: a crisp pill on a 150%
            # display without changing how the rest of the app is scaled.
            try:
                user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
            except (AttributeError, OSError):
                pass
            self._create()
        except Exception:
            log.exception("could not create the recording overlay")
            self._ready.set()
            return
        self._ready.set()
        msg = wintypes.MSG()
        while True:
            animating = self.mode != "hidden"
            timeout = int(1000 / FPS) if animating else 0xFFFFFFFF
            user32.MsgWaitForMultipleObjects(0, None, False, timeout, QS_ALLINPUT)
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            if not self._drain():
                break
            if self.mode != "hidden":
                try:
                    self._frame()
                except Exception:
                    log.exception("overlay frame failed")
                    self._hide_now()

    def _create(self) -> None:
        self._proc = WNDPROC(self._wndproc)          # must outlive the window
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinst
        wc.lpszClassName = "LiveWhisperPill"
        wc.hCursor = user32.LoadCursorW(None, ctypes.c_void_p(IDC_ARROW))
        user32.RegisterClassExW(ctypes.byref(wc))
        self._hwnd = user32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
            "LiveWhisperPill", "LiveWhisper", WS_POPUP, 0, 0, 1, 1,
            None, None, hinst, None)
        if not self._hwnd:
            raise ctypes.WinError(ctypes.get_last_error())

    def _drain(self) -> bool:
        while True:
            try:
                cmd, *args = self._q.get_nowait()
            except queue.Empty:
                return True
            now = time.monotonic()
            if cmd == "close":
                user32.DestroyWindow(self._hwnd)
                return False
            if cmd == "show":
                self.level_fn, self.command = args
                self._levels = [0.0] * BARS
                self._smooth = 0.0
                fresh = self.mode == "hidden" or self._closing_at is not None
                self.mode = "recording"
                self._return_to = None
                self._closing_at = None
                if fresh:
                    self._place()
                    self._shown_at = now
                    self._width = float(W_RECORD)
                    user32.ShowWindow(self._hwnd, SW_SHOWNOACTIVATE)
            elif cmd == "working" and self.mode != "hidden":
                self._hot = None
                if self.mode == "message":
                    self._return_to = "working"
                else:
                    self.mode = "working"
            elif cmd == "message":
                self.text = args[0]
                if self.mode in ("recording", "working") and self._closing_at is None:
                    self._return_to = self.mode
                elif self.mode != "message":
                    self._return_to = None
                if self.mode == "hidden" or self._closing_at is not None:
                    self._place()
                    self._shown_at = now
                    self._width = float(W_WORK)
                    user32.ShowWindow(self._hwnd, SW_SHOWNOACTIVATE)
                self._closing_at = None
                self.mode = "message"
                self._message_until = now + MESSAGE_S
            elif cmd == "hide":
                if self.mode == "message" and now < self._message_until:
                    self._return_to = None    # close once the note is read
                    continue
                if self.mode != "hidden" and self._closing_at is None:
                    self._closing_at = now
            elif cmd == "level":
                self.level_fn = (lambda v=args[0]: v)

    def _hide_now(self) -> None:
        self.mode = "hidden"
        self._closing_at = None
        user32.ShowWindow(self._hwnd, SW_HIDE)

    # ------------------------------------------------------- placement

    def _place(self) -> None:
        """Bottom-centre of the monitor in use, or where the user left it."""
        dpi = 96
        try:
            dpi = user32.GetDpiForWindow(self._hwnd) or 96
        except (AttributeError, OSError):
            pass
        if self.position:
            pt = wintypes.POINT(int(self.position[0]), int(self.position[1]))
            mon = user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONULL)
            if mon:
                self._anchor = (pt.x, pt.y)
                self._scale = self._monitor_scale(mon, dpi)
                return
        mon = user32.MonitorFromWindow(user32.GetForegroundWindow(),
                                       MONITOR_DEFAULTTONEAREST)
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(mon, ctypes.byref(info))
        self._scale = self._monitor_scale(mon, dpi)
        work = info.rcWork
        self._anchor = ((work.left + work.right) // 2,
                        work.bottom - int(28 * self._scale))

    @staticmethod
    def _monitor_scale(mon, fallback_dpi: int) -> float:
        try:
            x, y = ctypes.c_uint(), ctypes.c_uint()
            ctypes.windll.shcore.GetDpiForMonitor(mon, 0, ctypes.byref(x), ctypes.byref(y))
            return x.value / 96
        except (AttributeError, OSError):
            return fallback_dpi / 96

    # --------------------------------------------------------- drawing

    def _target_width(self) -> float:
        if self.mode == "recording":
            return W_RECORD
        if self.mode == "message":
            f = _font(12.5 * self._scale, bold=True)
            return f.getlength(self.text) / self._scale + 40
        return W_WORK

    def _frame(self) -> None:
        now = time.monotonic()
        if self.mode == "message" and now >= self._message_until and self._closing_at is None:
            if self._return_to:
                self.mode, self._return_to = self._return_to, None
            else:
                self._closing_at = now
        if self._closing_at is not None and now - self._closing_at >= FADE_S:
            self._hide_now()
            return

        if self.mode == "recording":
            level = 0.0
            if self.level_fn:
                try:
                    level = float(self.level_fn() or 0.0)
                except Exception:
                    level = 0.0
            # Speech meters sit low; lift quiet speech so the bars move.
            level = min(1.0, math.sqrt(max(0.0, level)) * 1.6)
            self._smooth += (level - self._smooth) * (0.6 if level > self._smooth else 0.25)
            self._levels = self._levels[1:] + [self._smooth]

        target = self._target_width()
        self._width += (target - self._width) * 0.3
        if abs(target - self._width) < 0.5:
            self._width = target

        appear = _ease((now - self._shown_at) / FADE_S)
        if self._closing_at is not None:
            appear = min(appear, 1 - _ease((now - self._closing_at) / FADE_S))
        self._blit(self._render(now), appear)

    def _render(self, now: float) -> Image.Image:
        s = self._scale
        m = int(MARGIN * s)
        pw, ph = int(round(self._width * s)), int(round(H * s))
        img = Image.new("RGBA", (pw + 2 * m, ph + 2 * m), (0, 0, 0, 0))
        img.alpha_composite(self._shadow(pw, ph, m))

        k = SS
        big = Image.new("RGBA", (pw * k, ph * k), (0, 0, 0, 0))
        d = ImageDraw.Draw(big)
        r = ph * k // 2
        d.rounded_rectangle((0, 0, pw * k - 1, ph * k - 1), r, fill=BG,
                            outline=EDGE, width=max(1, int(s * k)))
        cy = ph * k / 2

        if self.mode == "recording":
            self._draw_buttons(d, pw * k, cy, s * k)
            self._draw_wave(d, pw * k, cy, s * k)
        elif self.mode == "working":
            self._draw_dots(d, pw * k, cy, s * k, now)

        pill = big.resize((pw, ph), Image.LANCZOS)
        if self.mode == "message":
            ImageDraw.Draw(pill).text((pw / 2, ph / 2), self.text, fill=TEXT,
                                      font=_font(12.5 * s, bold=True), anchor="mm")
        img.alpha_composite(pill, (m, m))
        return img

    def _shadow(self, pw: int, ph: int, m: int) -> Image.Image:
        key = (pw, ph, m)
        if key not in self._shadow_cache:
            if len(self._shadow_cache) > 64:
                self._shadow_cache.clear()
            sh = Image.new("RGBA", (pw + 2 * m, ph + 2 * m), (0, 0, 0, 0))
            off = max(1, m // 4)
            ImageDraw.Draw(sh).rounded_rectangle(
                (m, m + off, m + pw, m + ph + off), ph // 2, fill=(0, 0, 0, 110))
            self._shadow_cache[key] = sh.filter(ImageFilter.GaussianBlur(m / 2.4))
        return self._shadow_cache[key]

    def _button_centres(self, width: float, unit: float) -> tuple:
        pad = (H / 2) * unit
        return pad, width - pad

    def _draw_buttons(self, d, width, cy, u) -> None:
        cx_cancel, cx_done = self._button_centres(width, u)
        r = BUTTON_R * u
        # Discard: a quiet ✕ on a translucent disc.
        d.ellipse((cx_cancel - r, cy - r, cx_cancel + r, cy + r),
                  fill=BUTTON_HOT if self._hot == "cancel" else BUTTON)
        a = 4.2 * u
        lw = max(1, int(1.8 * u))
        d.line((cx_cancel - a, cy - a, cx_cancel + a, cy + a), fill=ICON, width=lw)
        d.line((cx_cancel - a, cy + a, cx_cancel + a, cy - a), fill=ICON, width=lw)
        # Finish: a solid disc with a ✓, the obvious thing to press.
        rr = r * (1.07 if self._hot == "done" else 1.0)
        fill = WAVE_COMMAND if self.command else DONE
        d.ellipse((cx_done - rr, cy - rr, cx_done + rr, cy + rr), fill=fill)
        pts = [(cx_done - 4.8 * u, cy + 0.2 * u), (cx_done - 1.4 * u, cy + 3.6 * u),
               (cx_done + 5.0 * u, cy - 3.4 * u)]
        d.line(pts, fill=DONE_ICON, width=max(1, int(2.2 * u)), joint="curve")

    def _draw_wave(self, d, width, cy, u) -> None:
        cx_cancel, cx_done = self._button_centres(width, u)
        left = cx_cancel + (BUTTON_R + 9) * u
        right = cx_done - (BUTTON_R + 9) * u
        step = (right - left) / BARS
        bw = max(1.0, step * 0.46)
        colour = WAVE_COMMAND if self.command else WAVE
        top = (H / 2 - 9) * u
        for i, lv in enumerate(self._levels):
            # Taper toward the ends, so the wave reads as a shape, not a meter.
            x = (i + 0.5) / BARS
            env = 0.45 + 0.55 * math.sin(math.pi * x)
            h = max(bw, (0.08 + 0.92 * lv) * top * env)
            xc = left + (i + 0.5) * step
            d.rounded_rectangle((xc - bw / 2, cy - h, xc + bw / 2, cy + h),
                                bw / 2, fill=colour + (235,))

    def _draw_dots(self, d, width, cy, u, now) -> None:
        colour = WAVE_COMMAND if self.command else WAVE
        gap = 9 * u
        r = 2.6 * u
        for i in range(3):
            phase = (now - self._shown_at) * 5.0 - i * 0.7
            lift = max(0.0, math.sin(phase)) * 3.2 * u
            alpha = int(120 + 135 * max(0.0, math.sin(phase)))
            x = width / 2 + (i - 1) * gap
            d.ellipse((x - r, cy - r - lift, x + r, cy + r - lift), fill=colour + (alpha,))

    def _blit(self, img: Image.Image, opacity: float) -> None:
        w, h = img.size
        a = np.asarray(img, dtype=np.uint16)
        alpha = a[..., 3:4]
        bgra = np.empty((h, w, 4), dtype=np.uint8)
        bgra[..., :3] = (a[..., 2::-1] * alpha // 255).astype(np.uint8)
        bgra[..., 3] = a[..., 3].astype(np.uint8)
        data = bgra.tobytes()

        screen = user32.GetDC(None)
        mem = gdi32.CreateCompatibleDC(screen)
        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth, bmi.biHeight = w, -h          # top-down
        bmi.biPlanes, bmi.biBitCount = 1, 32
        bits = ctypes.c_void_p()
        bmp = gdi32.CreateDIBSection(screen, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        try:
            ctypes.memmove(bits, data, len(data))
            old = gdi32.SelectObject(mem, bmp)
            ax, ay = self._anchor
            rise = int((1 - opacity) * 8 * self._scale)
            pos = wintypes.POINT(int(ax - w / 2), int(ay - h + int(MARGIN * self._scale) + rise))
            size = wintypes.SIZE(w, h)
            src = wintypes.POINT(0, 0)
            blend = BLENDFUNCTION(0, 0, int(255 * max(0.0, min(1.0, opacity))), AC_SRC_ALPHA)
            user32.UpdateLayeredWindow(self._hwnd, screen, ctypes.byref(pos), ctypes.byref(size),
                                       mem, ctypes.byref(src), 0, ctypes.byref(blend), ULW_ALPHA)
            self._origin = (pos.x, pos.y, w, h)
            gdi32.SelectObject(mem, old)
        finally:
            gdi32.DeleteObject(bmp)
            gdi32.DeleteDC(mem)
            user32.ReleaseDC(None, screen)

    # ----------------------------------------------------------- input

    def _hit(self, x: int, y: int) -> str | None:
        """Client coordinates -> the button under them."""
        if self.mode != "recording":
            return None
        s = self._scale
        m = MARGIN * s
        cx_cancel, cx_done = self._button_centres(self._width * s, 1 * s)
        cy = H * s / 2
        r = (BUTTON_R + 3) * s
        px, py = x - m, y - m
        if (px - cx_cancel) ** 2 + (py - cy) ** 2 <= r * r:
            return "cancel"
        if (px - cx_done) ** 2 + (py - cy) ** 2 <= r * r:
            return "done"
        return None

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_MOUSEACTIVATE:
                return MA_NOACTIVATE
            if msg == WM_NCHITTEST:
                pt_x, pt_y = _lo(lparam), _hi(lparam)
                ox, oy = getattr(self, "_origin", (0, 0, 0, 0))[:2]
                # Buttons are buttons; everywhere else drags the pill.
                return HTCLIENT if self._hit(pt_x - ox, pt_y - oy) else HTCAPTION
            if msg == WM_SETCURSOR:
                if self._hot:
                    user32.SetCursor(user32.LoadCursorW(None, ctypes.c_void_p(IDC_HAND)))
                    return 1
            if msg == WM_MOUSEMOVE:
                self._hot = self._hit(_lo(lparam), _hi(lparam))
                if not self._tracking:
                    tme = TRACKMOUSEEVENT(ctypes.sizeof(TRACKMOUSEEVENT), TME_LEAVE, hwnd, 0)
                    user32.TrackMouseEvent(ctypes.byref(tme))
                    self._tracking = True
                return 0
            if msg == WM_MOUSELEAVE:
                self._hot = None
                self._tracking = False
                return 0
            if msg == WM_LBUTTONUP:
                hit = self._hit(_lo(lparam), _hi(lparam))
                if hit == "done" and self.on_stop:
                    threading.Thread(target=self.on_stop, daemon=True).start()
                elif hit == "cancel" and self.on_cancel:
                    threading.Thread(target=self.on_cancel, daemon=True).start()
                return 0
            if msg == WM_EXITSIZEMOVE:
                rect = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                w = rect.right - rect.left
                m = int(MARGIN * self._scale)
                self._anchor = (rect.left + w // 2, rect.bottom - m)
                self.position = list(self._anchor)
                if self.on_move:
                    try:
                        self.on_move(*self._anchor)
                    except Exception:
                        log.debug("could not remember the pill position", exc_info=True)
                return 0
            if msg == WM_DPICHANGED:
                self._scale = _lo(wparam) / 96
                return 0
        except Exception:
            log.debug("overlay input handling failed", exc_info=True)
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
