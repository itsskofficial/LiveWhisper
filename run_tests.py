#!/usr/bin/env python
"""Run the test suites and print one table.

    python run_tests.py            fast, deterministic, no GPU or network
    python run_tests.py --audio    also the speech model and loopback capture
    python run_tests.py --all      also the Groq fallback (needs a key) and
                                   the install readiness check

The suites are plain scripts so each can still be run on its own; this only
exists so "run the tests" means one command.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent

FAST = [
    ("data integrity", ["-m", "tools.check_data"]),
    ("core logic", ["-m", "tools.check_core"]),
    ("pipeline", ["test_pipeline.py"]),
    ("onboarding alignment", ["test_alignment.py"]),
    ("settings GUI", ["test_gui.py"]),
    ("robustness (118 checks)", ["tests/test_robustness.py"]),
    ("filler removal", ["tests/test_cleanup.py"]),
    ("hinglish respelling", ["tests/test_respell.py"]),
    ("specialist install", ["tests/test_specialists.py"]),
    ("compound splitting", ["tests/test_compounds.py"]),
    ("learning convergence", ["tests/test_learning.py"]),
]
AUDIO = [
    ("speech end to end", ["tests/test_audio_e2e.py", "build/audio"]),
    ("loopback capture", ["tests/test_loopback.py", "--audio", "build/audio"]),
]
ALL = [
    ("groq fallback", ["test_fallback.py"]),
    ("install readiness", ["verify.py"]),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="print each suite's output, not just failures")
    args = ap.parse_args()

    suites = FAST + (AUDIO if args.audio or args.all else []) + (ALL if args.all else [])
    env = {"PYTHONIOENCODING": "utf-8"}
    import os
    env = {**os.environ, **env}

    results = []
    for label, cmd in suites:
        t0 = time.perf_counter()
        p = subprocess.run([sys.executable, *cmd], cwd=ROOT, env=env,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        took = time.perf_counter() - t0
        ok = p.returncode == 0
        results.append((label, ok, took))
        print(f"[{'  ok  ' if ok else ' FAIL '}] {label:<26} {took:6.1f}s", flush=True)
        if args.verbose or not ok:
            tail = (p.stdout + p.stderr).strip().splitlines()[-25:]
            print("\n".join("        " + line for line in tail))

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} suites passed"
          f" in {sum(r[2] for r in results):.0f}s")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
