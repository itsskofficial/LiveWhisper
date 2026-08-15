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

from PIL import Image, ImageDraw

log = logging.getLogger(__name__)

ASSETS = Path(__file__).resolve().parent.parent / "assets"
ICON_PATH = ASSETS / "livewhisper.ico"

APP_ID = "LiveWhisper.Tray.1"

BG = "#14140F"
SURFACE = "#221F17"
AMBER = "#E0A02B"
AMBER_HI = "#F5C25C"

BARS = [0.34, 0.62, 1.0, 0.72, 0.44]


def render(size: int, accent: str = AMBER, highlight: str | None = None,
           chrome: bool = True) -> Image.Image:
    """Level-meter glyph. `chrome=False` drops the plate for tray use."""
    s = size * 8
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    if chrome:
        d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=BG)
        inset = int(s * 0.06)
        d.rounded_rectangle([inset, inset, s - inset - 1, s - inset - 1],
                            radius=int(s * 0.17), fill=SURFACE)

    n = len(BARS)
    bw, gap = s * 0.088, s * 0.055
    if not chrome:
        bw, gap = s * 0.105, s * 0.065  # fill the tray cell more fully
    total = n * bw + (n - 1) * gap
    x, cy = (s - total) / 2, s / 2
    max_h = s * (0.52 if chrome else 0.68)

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
    frames = [render(n, highlight=AMBER_HI) for n in sizes]
    frames[-1].save(path, format="ICO", sizes=[(n, n) for n in sizes],
                    append_images=frames[:-1])
    render(256, highlight=AMBER_HI).save(path.with_suffix(".png"))
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
