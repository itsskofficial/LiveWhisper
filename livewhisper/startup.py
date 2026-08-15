"""Run-at-sign-in registration via the per-user Run key.

Per-user (HKCU) rather than machine-wide, so this never needs admin rights and
only ever affects the account that ticked the box.
"""

from __future__ import annotations

import logging
import sys
import winreg
from pathlib import Path

log = logging.getLogger(__name__)

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_NAME = "LiveWhisper"


def _command() -> str:
    """The pythonw + run.py invocation for this installation, console-free."""
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = exe
    entry = Path(__file__).resolve().parent.parent / "run.py"
    return f'"{pythonw}" "{entry}"'


def is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, _NAME)
        return True
    except OSError:
        return False


def set_enabled(enabled: bool) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, _NAME, 0, winreg.REG_SZ, _command())
            log.info("registered for start-up: %s", _command())
        else:
            try:
                winreg.DeleteValue(key, _NAME)
                log.info("removed from start-up")
            except FileNotFoundError:
                pass
