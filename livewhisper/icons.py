"""App and tray iconography.

The level-meter motif is shared by the .ico, the taskbar, and the tray glyph, so
the tray colour can carry state (idle / recording / transcribing) while the shape
stays recognisably the same app.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from pathlib import Path

from . import paths

from PIL import Image, ImageDraw

log = logging.getLogger(__name__)

ASSETS = paths.ASSETS
ICON_PATH = ASSETS / "livewhisper.ico"

APP_ID = "LiveWhisper.Tray.1"

# The brand: a violet plate with a white level meter - the same bars the
# recording pill animates and the app window's logo shows.
VIOLET_TOP = (140, 115, 255)
VIOLET_BOTTOM = (84, 55, 230)
WHITE = "#FFFFFF"
IDLE, RECORDING, WORKING = "#8B75FF", "#EF4444", "#F5B942"

BARS = [0.34, 0.62, 1.0, 0.72, 0.44]


def _plate(s: int) -> Image.Image:
    """A rounded square with a top-left to bottom-right violet gradient."""
    grad = Image.new("RGBA", (s, s))
    px = grad.load()
    for y in range(s):
        for x in range(s):
            t = (x + y) / (2 * (s - 1))
            px[x, y] = tuple(int(a + (b - a) * t) for a, b in zip(VIOLET_TOP, VIOLET_BOTTOM)) + (255,)
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.24), fill=255)
    out = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    out.paste(grad, (0, 0), mask)
    return out


def render(size: int, accent: str = WHITE, highlight: str | None = None,
           chrome: bool = True) -> Image.Image:
    """Level-meter glyph. `chrome=False` drops the plate for tray use."""
    s = size * 4 if size >= 64 else size * 8
    img = _plate(s) if chrome else Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    n = len(BARS)
    bw, gap = s * 0.085, s * 0.058
    if not chrome:
        bw, gap = s * 0.105, s * 0.065  # fill the tray cell more fully
    total = n * bw + (n - 1) * gap
    x, cy = (s - total) / 2, s / 2
    max_h = s * (0.50 if chrome else 0.68)

    for i, rel in enumerate(BARS):
        h = max_h * rel
        colour = (highlight or accent) if i == n // 2 else accent
        d.rounded_rectangle([x, cy - h / 2, x + bw, cy + h / 2],
                            radius=bw / 2, fill=colour)
        x += bw + gap

    return img.resize((size, size), Image.LANCZOS)


def tray_image(colour: str) -> Image.Image:
    """Tray glyph tinted to the current state colour."""
    return render(64, accent=colour, chrome=False)


def write_ico(path: Path | None = None) -> Path:
    path = path or ICON_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    frames = [render(n) for n in sizes]
    frames[-1].save(path, format="ICO", sizes=[(n, n) for n in sizes],
                    append_images=frames[:-1])
    render(256).save(path.with_suffix(".png"))
    return path


def set_app_id() -> None:
    """Give Windows an explicit AppUserModelID.

    Without this the shell groups our windows under python.exe and shows the
    Python icon in the taskbar no matter what icon the window itself carries.
    Must run before any window exists.
    """
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        log.debug("could not set AppUserModelID", exc_info=True)


def apply(window) -> None:
    """Attach the .ico to a Tk window (taskbar + title bar)."""
    if not ICON_PATH.exists():
        try:
            write_ico()
        except Exception:
            log.debug("could not generate icon", exc_info=True)
            return
    try:
        window.iconbitmap(str(ICON_PATH))
    except Exception:
        log.debug("iconbitmap failed", exc_info=True)
