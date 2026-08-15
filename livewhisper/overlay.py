"""The floating recording pill: elapsed time, live level meter, stop and discard.

The level meter is the point of this widget. A flat meter means the meeting
audio is not reaching the capture - wrong output device, muted, or the call
routed elsewhere - and you want to discover that in the first ten seconds, not
after a forty minute call.

All methods must be called from the Tk main thread.
"""

from __future__ import annotations

import logging
import tkinter as tk

from .theme import palette

log = logging.getLogger(__name__)

_BARS = 9
_W, _H = 250, 46
_TRANSPARENT = "#010203"  # arbitrary colour keyed out to fake rounded corners


class RecordingOverlay:
    def __init__(self, root: tk.Tk, on_stop, on_cancel, theme: str = "dark-amber",
                 position=None, on_move=None, show_meter: bool = True):
        self.root = root
        self.on_stop = on_stop
        self.on_cancel = on_cancel
        self.on_move = on_move
        self.show_meter = show_meter
        self.c = palette(theme)
        self.position = position
        self._win: tk.Toplevel | None = None
        self._levels = [0.0] * _BARS
        self._tick = None
        self._elapsed = 0.0
        self._drag = None

    # -- lifecycle ----------------------------------------------------------

    def show(self) -> None:
        if self._win is not None:
            return
        w = tk.Toplevel(self.root)
        w.overrideredirect(True)          # no title bar
        w.attributes("-topmost", True)
        try:
            # Windows keys this colour out entirely, giving real rounded corners
            # rather than a rectangle with painted-on ones.
            w.attributes("-transparentcolor", _TRANSPARENT)
        except tk.TclError:
            log.debug("transparentcolor unsupported; pill will be rectangular")

        x, y = self.position or self._default_position(w)
        w.geometry(f"{_W}x{_H}+{int(x)}+{int(y)}")

        cv = tk.Canvas(w, width=_W, height=_H, bg=_TRANSPARENT,
                       highlightthickness=0, bd=0)
        cv.pack()
        self._win, self._canvas = w, cv

        cv.bind("<Button-1>", self._press)
        cv.bind("<B1-Motion>", self._drag_move)
        cv.bind("<ButtonRelease-1>", self._release)

        self._elapsed = 0.0
        self._levels = [0.0] * _BARS
        self._redraw()

    def hide(self) -> None:
        if self._tick is not None:
            self.root.after_cancel(self._tick)
            self._tick = None
        if self._win is not None:
            self._win.destroy()
            self._win = None

    def _default_position(self, w) -> tuple[int, int]:
        w.update_idletasks()
        sw = w.winfo_screenwidth()
        sh = w.winfo_screenheight()
        return sw - _W - 32, sh - _H - 96  # above the taskbar, right side

    # -- live update --------------------------------------------------------

    def update(self, elapsed: float, level: float) -> None:
        """Feed the widget the current elapsed seconds and 0..1 input level."""
        if self._win is None:
            return
        self._elapsed = elapsed
        self._levels = self._levels[1:] + [max(0.0, min(1.0, level))]
        self._redraw()

    # -- drawing ------------------------------------------------------------

    def _rounded(self, cv, x0, y0, x1, y1, r, **kw):
        cv.create_oval(x0, y0, x0 + 2 * r, y0 + 2 * r, outline="", **kw)
        cv.create_oval(x1 - 2 * r, y0, x1, y0 + 2 * r, outline="", **kw)
        cv.create_oval(x0, y1 - 2 * r, x0 + 2 * r, y1, outline="", **kw)
        cv.create_oval(x1 - 2 * r, y1 - 2 * r, x1, y1, outline="", **kw)
        cv.create_rectangle(x0 + r, y0, x1 - r, y1, outline="", **kw)
        cv.create_rectangle(x0, y0 + r, x1, y1 - r, outline="", **kw)

    def _redraw(self) -> None:
        cv = self._canvas
        cv.delete("all")
        c = self.c
        self._rounded(cv, 0, 0, _W, _H, _H // 2, fill=c["surface"])

        # Recording dot, pulsing on the half-second so a frozen UI is obvious.
        on = int(self._elapsed * 2) % 2 == 0
        cv.create_oval(16, _H // 2 - 5, 26, _H // 2 + 5,
                       fill=c["rec"] if on else c["surface_hi"], outline="")

        mins, secs = divmod(int(self._elapsed), 60)
        cv.create_text(38, _H // 2, anchor="w", text=f"{mins:02d}:{secs:02d}",
                       fill=c["text"], font=("Segoe UI", 11, "bold"))

        if self.show_meter:
            x = 92
            for lv in self._levels:
                h = max(3, int(lv * 22))
                y0, y1 = _H // 2 - h // 2, _H // 2 + h // 2
                # Amber while audio is arriving, dim grey when it is not.
                colour = c["accent"] if lv > 0.02 else c["border"]
                cv.create_rectangle(x, y0, x + 4, y1, fill=colour, outline="")
                x += 7

        # Stop (filled square) and discard (x).
        sx = _W - 58
        cv.create_rectangle(sx, _H // 2 - 6, sx + 12, _H // 2 + 6,
                            fill=c["text"], outline="", tags="stop")
        dx = _W - 30
        for a, b in (((0, 0), (1, 1)), ((1, 0), (0, 1))):
            cv.create_line(dx + a[0] * 12, _H // 2 - 6 + a[1] * 12,
                           dx + b[0] * 12, _H // 2 - 6 + b[1] * 12,
                           fill=c["muted"], width=2, tags="cancel")

    # -- interaction --------------------------------------------------------

    def _hit(self, event) -> str | None:
        for item in self._canvas.find_overlapping(event.x - 6, event.y - 6,
                                                  event.x + 6, event.y + 6):
            for tag in self._canvas.gettags(item):
                if tag in ("stop", "cancel"):
                    return tag
        return None

    def _press(self, event) -> None:
        self._hit_target = self._hit(event)
        self._drag = (event.x_root, event.y_root, self._win.winfo_x(),
                      self._win.winfo_y(), False)

    def _drag_move(self, event) -> None:
        if not self._drag:
            return
        x0, y0, wx, wy, _ = self._drag
        dx, dy = event.x_root - x0, event.y_root - y0
        if abs(dx) > 3 or abs(dy) > 3:
            self._drag = (x0, y0, wx, wy, True)  # a drag, not a click
            self._win.geometry(f"+{wx + dx}+{wy + dy}")

    def _release(self, event) -> None:
        moved = self._drag[4] if self._drag else False
        self._drag = None
        if moved:
            if self.on_move and self._win is not None:
                self.on_move(self._win.winfo_x(), self._win.winfo_y())
            return
        if self._hit_target == "stop":
            self.on_stop()
        elif self._hit_target == "cancel":
            self.on_cancel()
