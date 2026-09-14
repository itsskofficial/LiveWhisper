#!/usr/bin/env python
"""The memory gate and conversion lock that keep model installs from crashing.

    python tests/test_resources.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper import resources  # noqa: E402
from livewhisper.console import setup as _console  # noqa: E402

_console()
ROOT = Path(__file__).resolve().parent.parent
fails = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    fails += not ok
    print(f"[{'  ok  ' if ok else ' FAIL '}] {name}" + (f"  {detail}" if detail else ""))


def main() -> int:
    print("=== memory ===")
    have = resources.available_commit_gb()
    if sys.platform == "win32":
        check("committable memory is readable on Windows",
              isinstance(have, float) and have > 0, f"{have}")
    else:
        check("reads None off Windows rather than guessing", have is None)
    check("need scales with the checkpoint and includes the margin",
          abs(resources.memory_needed_gb(3.0) - (3.0 * resources.MEMORY_FACTOR
                                                 + resources.MEMORY_MARGIN_GB)) < 1e-9)

    t = time.time()
    resources.wait_for_memory(0.001, progress=lambda m: None, poll_s=0.01)
    check("enough memory returns immediately", time.time() - t < 1.0)

    # Unreadable memory must never block: a guess that is wrong would hang.
    saved = resources.available_commit_gb
    try:
        resources.available_commit_gb = lambda: None
        t = time.time()
        resources.wait_for_memory(10_000, progress=lambda m: None, poll_s=0.01)
        check("unreadable memory does not block", time.time() - t < 1.0)

        readings = iter([1.0, 1.0, 50.0])
        messages: list = []
        resources.available_commit_gb = lambda: next(readings)
        resources.wait_for_memory(10.0, progress=messages.append, poll_s=0.01)
        check("waits while short, proceeds once memory frees, tells the user once",
              len(messages) == 1 and "Waiting" in messages[0], str(messages))
    finally:
        resources.available_commit_gb = saved

    print("\n=== lock ===")
    with tempfile.TemporaryDirectory() as td:
        folder = Path(td)
        h = resources.conversion_lock(folder, progress=lambda m: None, poll_s=0.05)
        check("lock acquired", h is not None)

        # A second process must wait while this one holds it.
        holder = subprocess.Popen(
            [sys.executable, "-c",
             "import sys, time; sys.path.insert(0, r'%s'); "
             "from livewhisper import resources; from pathlib import Path; "
             "t=time.time(); h=resources.conversion_lock(Path(r'%s'), "
             "progress=lambda m: None, poll_s=0.1); "
             "print(round(time.time()-t, 1), flush=True); resources.release(h)"
             % (ROOT, folder)],
            stdout=subprocess.PIPE, text=True)
        time.sleep(1.5)
        resources.release(h)
        waited = float(holder.communicate(timeout=30)[0].strip())
        check("a second process waits for the lock, then gets it",
              waited >= 1.0, f"waited {waited}s")

        h2 = resources.conversion_lock(folder, progress=lambda m: None, poll_s=0.05)
        check("released lock can be taken again", h2 is not None)
        resources.release(h2)

    print(f"\n{'all passed' if not fails else f'{fails} FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
