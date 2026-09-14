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

# Measured (tests/results/conversion_memory.md), converting alone:
#
#   Gujarati whisper-medium, 3.06 GB float32 pickle        peak 6.9 GB   2.25x
#   Urdu large-v3-turbo,     3.24 GB float32 safetensors   peak 7.9 GB   2.44x
#   Marathi whisper-large-v2, 6.17 GB float32 pickle       peak 11.4 GB  1.85x
#
# When Windows manages the pagefile it grows to cover that, and lone
# conversions succeeded starting from 3.0-3.9 GB committable - Marathi's with
# the commit limit visibly rising mid-run. What crashed was several heavy
# processes allocating at once, which the conversion lock and the benchmark
# gate prevent.
#
# So the bar depends on whether the pagefile can grow. Reserving the whole peak
# on a machine where it can left a conversion waiting forever on 16 GB with
# ordinary applications open.
PEAK_FACTOR = 2.5             # above the worst measured ratio, 2.44x
MANAGED_FACTOR = 0.5          # admits every lone conversion observed to succeed
MANAGED_MARGIN_GB = 1.5
FIXED_MARGIN_GB = 1.0

_MM_KEY = r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management"


def _managed_from_paging_files(entries: list) -> bool:
    """Whether any PagingFiles registry entry lets Windows size the pagefile.

    "?:\\pagefile.sys" and "C:\\pagefile.sys 0 0" are system-managed, and so is
    a bare path with no sizes. "C:\\pagefile.sys 4096 8192" is a custom size that
    cannot grow past its maximum, and an empty list means no pagefile at all.
    """
    for raw in entries or []:
        parts = str(raw).split()
        if not parts:
            continue
        if parts[0].startswith("?:"):
            return True
        sizes = parts[1:]
        if not sizes or all(s == "0" for s in sizes):
            return True
    return False


def pagefile_is_system_managed() -> bool | None:
    """True when Windows sizes the pagefile itself; None if it cannot be read."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _MM_KEY) as key:
            entries, _type = winreg.QueryValueEx(key, "PagingFiles")
        return _managed_from_paging_files(list(entries))
    except Exception:
        return None


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
    """Committable memory to wait for before starting a conversion.

    With a pagefile Windows can grow, only enough to avoid starting into an
    already exhausted machine. With a fixed one, the whole measured peak.
    Unreadable counts as managed, since that is Windows' default.
    """
    if pagefile_is_system_managed() is False:
        return weights_gb * PEAK_FACTOR + FIXED_MARGIN_GB
    return weights_gb * MANAGED_FACTOR + MANAGED_MARGIN_GB


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


def acquire_conversion_slot(folder: Path, need_gb: float, progress=print,
                            poll_s: float = 10.0):
    """Wait for memory, take the lock, and confirm the memory is still there.

    The order matters. Waiting for memory while holding the lock let one
    conversion that did not fit block every other conversion queued behind it,
    including ones that would have fit. Returns the open lock handle.
    """
    folder.mkdir(parents=True, exist_ok=True)
    handle = open(folder / ".convert.lock", "a+b")
    try:
        import msvcrt
    except ImportError:                               # not Windows
        import fcntl
        wait_for_memory(need_gb, progress=progress)
        fcntl.flock(handle, fcntl.LOCK_EX)
        return handle
    said = False
    while True:
        wait_for_memory(need_gb, progress=progress)
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            if not said:
                progress("Waiting for another model conversion to finish...")
                said = True
            time.sleep(poll_s)
            continue
        have = available_commit_gb()
        if have is None or have >= need_gb:
            return handle
        handle.seek(0)                                # memory went while waiting
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def peak_commit_gb() -> float | None:
    """This process's peak committed memory in GB - what calibration is based on.

    None off Windows or if the call fails.
    """
    try:
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # Without these declarations ctypes passes the process handle as a 32-bit
        # int; on 64-bit Windows it is truncated, the call fails, and the peak
        # silently reads as unavailable - which is what happened the first time.
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        get_info = getattr(kernel32, "K32GetProcessMemoryInfo", None)
        if get_info is None:
            get_info = ctypes.WinDLL("psapi").GetProcessMemoryInfo
        get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        get_info.restype = wintypes.BOOL

        counters = PMC()
        counters.cb = ctypes.sizeof(PMC)
        ok = get_info(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
        return counters.PeakPagefileUsage / 1e9 if ok else None
    except Exception:
        return None


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
