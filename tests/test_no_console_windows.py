#!/usr/bin/env python
"""Nothing the app starts opens a console window.

hardware.py ran nvidia-smi without CREATE_NO_WINDOW. From the windowed app every
call opened a console, and Windows Terminal left each one on the desktop as an
empty see-through frame: dozens of them, stacked over the app window, catching
its clicks. The settings page asked twice on every visit, so it also took 5 s
to open. Found recording the demo; the frames were in every shot of the window.

    python tests/test_no_console_windows.py
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from livewhisper import hardware  # noqa: E402
from livewhisper.console import setup as _console  # noqa: E402

_console()
fails = 0
SPAWNERS = {"run", "Popen", "check_output", "check_call", "call"}
CREATE_NO_WINDOW = 0x08000000


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    fails += not ok
    print(f"[{'  ok  ' if ok else ' FAIL '}] {name}" + (f"  {detail}" if detail else ""))


def unhidden_spawns() -> list:
    """subprocess calls in the app's own code that do not pass creationflags."""
    found = []
    for path in sorted((ROOT / "livewhisper").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in SPAWNERS and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "subprocess"
                    and not any(k.arg == "creationflags" for k in node.keywords)):
                found.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    return found


def main() -> int:
    print("=== every child process is started hidden ===")
    bad = unhidden_spawns()
    check("no subprocess call without creationflags", not bad, ", ".join(bad))

    print("\n=== nvidia-smi ===")
    calls = []

    class Done:
        returncode, stdout = 0, "NVIDIA GeForce RTX 4060 Laptop GPU\n"

    real_run, real_which = subprocess.run, hardware.shutil.which
    subprocess.run = lambda cmd, **kw: calls.append(kw) or Done()
    hardware.shutil.which = lambda name: "C:/Windows/System32/nvidia-smi.exe"
    getattr(hardware._nvidia_smi, "cache_clear", lambda: None)()
    try:
        for _ in range(3):
            hardware.detect()
    finally:
        subprocess.run, hardware.shutil.which = real_run, real_which
        getattr(hardware._nvidia_smi, "cache_clear", lambda: None)()
    if sys.platform == "win32":
        check("started without a console window",
              all(kw.get("creationflags", 0) & CREATE_NO_WINDOW for kw in calls), repr(calls[:1]))
    check("asked once per question, not on every page", len(calls) == 2, f"{len(calls)} calls for 3 detects")

    print(f"\n{'all passed' if not fails else f'{fails} FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
