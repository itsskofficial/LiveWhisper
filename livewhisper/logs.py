"""Where the app writes its log, so a bug report can include it.

Every shortcut starts LiveWhisper with pythonw, which has no console: whatever
was logged went nowhere, and `sys.stderr` is None, which crashed anything that
writes a progress bar there - the 3 GB model download among them. So the log
goes to a rotating file under %LOCALAPPDATA%, and stdout/stderr are pointed at
it when there is no console to write to.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "LiveWhisper"


def log_path() -> Path:
    return log_dir() / "livewhisper.log"


def setup(verbose: bool = False) -> Path:
    """Log to a file (1 MB x 3) and, when there is one, the console."""
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    file_handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3,
                                       encoding="utf-8")
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    if sys.stderr is None or sys.stdout is None:
        # pythonw: give libraries that print or draw progress bars somewhere
        # harmless to write, instead of None.
        sink = open(path.with_name("console.log"), "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = sink
        if sys.stderr is None:
            sys.stderr = sink
    else:
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        root.addHandler(console)

    for noisy in ("PIL", "httpx", "httpcore", "urllib3", "filelock", "huggingface_hub",
                  "comtypes"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return path
