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
    print("\n=== pagefile ===")
    parse = resources._managed_from_paging_files
    check("'?:\\pagefile.sys' is system-managed", parse(["?:\\pagefile.sys"]) is True)
    check("sizes of 0 0 are system-managed", parse(["C:\\pagefile.sys 0 0"]) is True)
    check("a bare path is system-managed", parse(["D:\\pagefile.sys"]) is True)
    check("custom sizes are not", parse(["C:\\pagefile.sys 4096 8192"]) is False)
    check("no pagefile at all is not", parse([]) is False and parse([""]) is False)
    check("any managed entry among several counts",
          parse(["C:\\pagefile.sys 2048 2048", "D:\\pagefile.sys 0 0"]) is True)
    if sys.platform == "win32":
        live = resources.pagefile_is_system_managed()
        check("this machine's setting is readable", live in (True, False), f"{live}")

    saved_managed = resources.pagefile_is_system_managed
    try:
        resources.pagefile_is_system_managed = lambda: True
        managed = resources.memory_needed_gb(3.06)
        resources.pagefile_is_system_managed = lambda: False
        fixed = resources.memory_needed_gb(3.06)
        resources.pagefile_is_system_managed = lambda: None
        unknown = resources.memory_needed_gb(3.06)
    finally:
        resources.pagefile_is_system_managed = saved_managed
    check("a growable pagefile needs only enough to start safely",
          abs(managed - (3.06 * resources.MANAGED_FACTOR
                         + resources.MANAGED_MARGIN_GB)) < 1e-9, f"{managed:.2f} GB")
    check("a fixed pagefile needs the whole measured peak",
          abs(fixed - (3.06 * resources.PEAK_FACTOR
                       + resources.FIXED_MARGIN_GB)) < 1e-9, f"{fixed:.2f} GB")
    # Every conversion measured so far: (checkpoint GB, peak commit GB).
    measured = {"Gujarati": (3.06, 6.9), "Urdu": (3.24, 7.9), "Marathi": (6.17, 11.4)}
    try:
        resources.pagefile_is_system_managed = lambda: False
        for name, (weights, peak) in measured.items():
            bar = resources.memory_needed_gb(weights)
            check(f"{name}'s measured peak ({peak} GB) fits under the fixed-pagefile bar",
                  bar >= peak, f"bar {bar:.1f} GB")
    finally:
        resources.pagefile_is_system_managed = saved_managed
    check("every lone success observed (started at 3.9 GB) passes the managed bar",
          managed <= 3.9, f"{managed:.2f} GB")
    check("an unreadable setting falls back to Windows' default, managed",
          unknown == managed)

    if sys.platform == "win32":
        # The first version returned None on 64-bit Windows because ctypes
        # truncated the process handle - and nothing noticed, since None is a
        # legal answer. So check the number moves with a real allocation.
        before = resources.peak_commit_gb()
        blob = bytearray(300 * 1024 * 1024)
        for i in range(0, len(blob), 4096):
            blob[i] = 1
        after = resources.peak_commit_gb()
        del blob
        check("peak commit is readable and rises across a 300 MB allocation",
              before is not None and after is not None and after - before > 0.25,
              f"{before} -> {after}")

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

        # The deadlock this guards against: a conversion that did not fit held
        # the lock while waiting for memory, and every conversion behind it -
        # including ones that would have fit - waited too.
        # The starved process ends itself. Killing it is not enough on Windows:
        # a venv's python.exe is a launcher that runs the real interpreter as a
        # child, kill() stops only the launcher, and the orphan keeps looping
        # with the lock file open.
        starved = subprocess.Popen(
            [sys.executable, "-c",
             "import os, sys, threading, time; sys.path.insert(0, r'%s'); "
             "from livewhisper import resources; from pathlib import Path; "
             "resources.available_commit_gb = lambda: 0.1; "
             "threading.Thread(target=resources.acquire_conversion_slot, "
             "args=(Path(r'%s'), 5.0), "
             "kwargs={'progress': lambda m: None, 'poll_s': 0.05}, "
             "daemon=True).start(); "
             "print('waiting', flush=True); time.sleep(4); os._exit(0)"
             % (ROOT, folder)],
            stdout=subprocess.PIPE, text=True)
        try:
            starved.stdout.readline()                   # it is now in its wait
            time.sleep(1.0)
            t = time.time()
            h3 = resources.acquire_conversion_slot(folder, 0.001,
                                                   progress=lambda m: None,
                                                   poll_s=0.05)
            took = time.time() - t
            check("a conversion short of memory does not hold the lock",
                  h3 is not None and took < 2.0, f"took {took:.2f}s")
            resources.release(h3)
        finally:
            try:
                starved.wait(timeout=20)
            except subprocess.TimeoutExpired:
                starved.kill()
                starved.wait(timeout=10)

    print(f"\n{'all passed' if not fails else f'{fails} FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
