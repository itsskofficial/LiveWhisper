"""Colour palettes shared by the settings window, the overlay and the tray icon.

Keeping the tray icon's state colours and the UI accent in one place is what
makes the app read as a single system rather than three separate widgets.
"""

from __future__ import annotations

PALETTES = {
    "dark-amber": {
        "bg": "#14140F",
        "surface": "#1F1E18",
        "surface_hi": "#2B2A22",
        "border": "#3A3830",
        "accent": "#E0A02B",
        "accent_hi": "#F0B44A",
        "accent_text": "#14140F",
        "rec": "#E0342B",
        "ok": "#5FB87A",
        "text": "#EDEAE2",
        "muted": "#9A9486",
    },
    "dark-indigo": {
        "bg": "#0F1115",
        "surface": "#191C24",
        "surface_hi": "#232733",
        "border": "#333949",
        "accent": "#6C7CE0",
        "accent_hi": "#8593EC",
        "accent_text": "#0F1115",
        "rec": "#E0342B",
        "ok": "#5FB87A",
        "text": "#E6E8EE",
        "muted": "#8B93A7",
    },
}

# `system` follows Windows and needs a palette that survives on both; the dark
# variant is used for the overlay either way, since it floats over arbitrary
# content and must stay legible.
PALETTES["system"] = PALETTES["dark-indigo"]

# Tray icon state colours, resolved per palette.
STATE_COLOURS = {
    "idle": "muted",
    "recording": "rec",
    "transcribing": "accent",
}


def palette(name: str) -> dict:
    return PALETTES.get(name, PALETTES["dark-amber"])


def appearance_mode(name: str) -> str:
    """customtkinter appearance mode for a palette name."""
    return "system" if name == "system" else "dark"
