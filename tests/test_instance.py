#!/usr/bin/env python
"""A second launch shows the running app instead of starting another copy.

    python tests/test_instance.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

HOME = Path(tempfile.mkdtemp())
os.environ["LIVEWHISPER_HOME"] = str(HOME)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper import instance  # noqa: E402

fails = 0


def check(name: str, ok: bool) -> None:
    global fails
    fails += not ok
    print(f"[{'  ok  ' if ok else ' FAIL '}] {name}")


def main() -> int:
    try:
        check("nothing running: a launch goes ahead", instance.signal_running() is False)
        shown = threading.Event()
        instance.serve(shown.set)
        check("with one running, a second launch defers to it",
              instance.signal_running() is True)
        check("...and the running one is asked to show its window", shown.wait(2))
        instance.PORT_FILE.write_text("1")          # a stale file from a crash
        check("a stale port file does not block a launch",
              instance.signal_running() is False)
    finally:
        shutil.rmtree(HOME, ignore_errors=True)
    print(f"\n{'all passed' if not fails else f'{fails} FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
