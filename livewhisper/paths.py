"""Where things live, for a source checkout and for the installed app.

A source checkout keeps everything beside the code, as it always has:
config.yaml, profiles.json, .env, models/ and transcripts/ in the repo.

The installed app (a PyInstaller bundle under Program Files) cannot write
beside itself, so it splits the two:

    bundled, read-only     the code, data/ (lexicons, romanizer), assets/,
                           ui/ and the default config
    %APPDATA%\\LiveWhisper  config.yaml, profiles.json, .env, notes,
                           transcripts, history - small, and roams with the user
    %LOCALAPPDATA%\\LiveWhisper
                           models, GPU libraries, the writing model - gigabytes,
                           machine-specific, never roamed

LIVEWHISPER_HOME overrides the per-user folder, for tests and portable use.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))

# Read-only resources: the unpacked bundle, or the repository root.
BUNDLE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def _appdata(var: str, fallback: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / "AppData" / fallback) / "LiveWhisper"


if os.environ.get("LIVEWHISPER_HOME"):
    HOME = Path(os.environ["LIVEWHISPER_HOME"])
    CACHE = HOME / "cache"
elif FROZEN:
    HOME = _appdata("APPDATA", "Roaming")
    CACHE = _appdata("LOCALAPPDATA", "Local")
else:
    HOME = BUNDLE
    CACHE = BUNDLE

DATA = BUNDLE / "data"
ASSETS = BUNDLE / "assets"
UI = BUNDLE / "livewhisper" / "ui"
DEFAULT_CONFIG = BUNDLE / "config.yaml"

CONFIG = HOME / "config.yaml"
ENV = HOME / ".env"
PROFILES = HOME / "profiles.json"
HISTORY = HOME / "history.jsonl"
NOTES = HOME / "notes"
TRANSCRIPTS = HOME / "transcripts"

MODELS = CACHE / "models"
CUDA = CACHE / "cuda"
LLM = CACHE / "llm"


def ensure_config() -> Path:
    """The user's config, copied from the bundled default on first launch and
    fitted to the machine (hardware.fit)."""
    if not CONFIG.exists():
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        from . import config as cfgio
        from . import hardware
        cfg = cfgio.load(DEFAULT_CONFIG)
        try:
            hardware.fit(cfg)
        except Exception:
            pass                        # the default still works, just slower
        cfgio.save(CONFIG, cfg)
    return CONFIG
