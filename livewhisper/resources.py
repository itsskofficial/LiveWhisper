"""Memory and locking guards for the heavy one-off jobs: converting a model.

Converting a speech model loads the whole checkpoint into memory before writing
the half-size copy. On Windows, when the memory cannot be committed, torch's
native loader does not raise MemoryError - it dies with an access violation and
no traceback, so a user would see an install that simply stops.

That happened here repeatedly while several models were benchmarked at once:
Windows logged "low virtual memory condition" (Resource-Exhaustion-Detector,
event 2004) in the same minutes, with the checkpoint's SHA-256 intact and a
plain load of the same file succeeding once memory was free. The app itself
holds large-v3 in memory, so a user installing a specialist while it runs is in
exactly that position.

Two guards, used by livewhisper.specialists and scripts/convert_ct2.py:

  conversion_lock   one conversion at a time on this machine
  wait_for_memory   block until Windows can commit enough, instead of crashing
"""

from __future__ import annotations

import time
from pathlib import Path

# 2x the checkpoint leaves room for the float16 copy being built; the fixed
# margin covers other processes growing during a conversion that takes minutes.
# A single check with 1.5x and no margin was measured to be not enough.
MEMORY_FACTOR = 2.0
MEMORY_MARGIN_GB = 3.0


def available_commit_gb() -> float | None:
    """How much more memory Windows can commit right now, in GB.

    None where it cannot be read (not Windows, or the call failed) - callers
    treat that as "do not block", since guessing wrong would hang forever.
    """
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return status.ullAvailPageFile / 1e9          # commit limit minus committed
    except Exception:
        return None


def memory_needed_gb(weights_gb: float) -> float:
    return weights_gb * MEMORY_FACTOR + MEMORY_MARGIN_GB


def wait_for_memory(need_gb: float, progress=print, poll_s: float = 30.0) -> None:
    """Block until the machine can commit `need_gb` more, rather than crash."""
    said = False
    while True:
        have = available_commit_gb()
        if have is None or have >= need_gb:
            return
        if not said:
            progress(f"Waiting for {need_gb:.1f} GB of memory to convert safely "
                     f"(have {have:.1f}). Closing other programs will speed this up.")
            said = True
        time.sleep(poll_s)


def conversion_lock(folder: Path, progress=print, poll_s: float = 10.0):
    """Block until no other conversion holds the lock; return the open handle.

    Keep the returned handle alive for as long as the lock should be held. The
    operating system releases it if the process dies, so a crash cannot leave
    the lock stuck.
    """
    folder.mkdir(parents=True, exist_ok=True)
    handle = open(folder / ".convert.lock", "a+b")
    try:
        import msvcrt
    except ImportError:                               # not Windows
        import fcntl
        fcntl.flock(handle, fcntl.LOCK_EX)
        return handle
    said = False
    while True:
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return handle
        except OSError:
            if not said:
                progress("Waiting for another model conversion to finish...")
                said = True
            time.sleep(poll_s)


def release(handle) -> None:
    """Release a handle returned by conversion_lock."""
    try:
        import msvcrt
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    except Exception:
        pass
    try:
        handle.close()
    except Exception:
        pass
