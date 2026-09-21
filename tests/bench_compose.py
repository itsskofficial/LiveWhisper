#!/usr/bin/env python
"""Which local model should write text for Ctrl+Alt+W?

"Reply saying I can't make Thursday" has to produce a finished message in about
the time it takes to reach for the mouse, from a model small enough to share an
8 GB card with the speech models. Each candidate writes the same replies; the
output is printed for reading and checked for the failures that make a reply
unusable: a preamble ("Here's a draft"), quotes round it, a missing key fact,
the wrong language, or a sign-off with a placeholder name.

    python tests/bench_compose.py --models qwen3:1.7b,qwen3:4b,qwen2.5:3b
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper.actions import COMPOSE_SYSTEM, FIX_SYSTEM  # noqa: E402
from livewhisper.console import setup as _console  # noqa: E402
from livewhisper.providers import Ollama  # noqa: E402

_console()
OUT = Path(__file__).resolve().parent / "results"

EMAIL = """From: Priya Raghavan
Subject: Design review on Thursday

Hi Sarthak, can we do the design review this Thursday at 3pm? I'd like to go
through the new onboarding flow before the release. Let me know. Thanks, Priya"""

SLACK = """#release  Marcus: is the installer fix merged yet? QA wants to start at 5"""

TASKS = [
    ("compose", "reply saying I can't make Thursday but Friday morning works",
     EMAIL, {"has": ["friday"], "not": ["here's", "here is", "[your name]", "subject:"]}),
    ("compose", "tell him yes it's merged and the build is running now",
     SLACK, {"has": ["merged"], "not": ["here's", "[", "dear"]}),
    ("compose", "reply that I'll send the deck tonight and thank her",
     EMAIL, {"has": ["tonight"], "not": ["here's", "[your name]"]}),
    ("compose", "bol do ki main kal subah call karunga",
     SLACK, {"has": ["kal", "call"], "not": ["here's", "[", "tomorrow morning"]}),
    ("compose", "write a short note to the team that the office is closed on Monday",
     "", {"has": ["monday", "closed"], "not": ["here's", "[your name]", "subject:"]}),
    ("fix", "i has went to the office yesterday and meet with priya about the the release",
     "", {"has": ["went", "met", "priya"], "not": ["here's", "corrected", "the the"]}),
    ("fix", "kal main office gaya tha aur priya se mila, release ki baat hui",
     "", {"has": ["kal", "office", "priya"], "not": ["here's", "yesterday i"]}),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="qwen3:1.7b,qwen3:4b,qwen2.5:3b,qwen2.5:7b")
    args = ap.parse_args()

    summary = {}
    for model in [m for m in args.models.split(",") if m]:
        p = Ollama(model)
        p.chat("Reply with ok.", "ok", temperature=0)            # load it
        times, bad = [], 0
        print(f"\n=== {model} ===")
        for kind, instruction, screen, check in TASKS:
            if kind == "compose":
                user = (f"What is on screen right now:\n-----\n{screen}\n-----\n\n"
                        if screen else "") + f"Instruction: {instruction}"
                system = COMPOSE_SYSTEM.format(style="")
            else:
                user, system = instruction, FIX_SYSTEM
            t0 = time.perf_counter()
            out = p.chat(system, user, temperature=0.3 if kind == "compose" else 0)
            ms = (time.perf_counter() - t0) * 1000
            times.append(ms)
            low = out.lower()
            problems = [f"missing {w!r}" for w in check["has"] if w not in low]
            problems += [f"contains {w!r}" for w in check["not"] if w in low]
            bad += bool(problems)
            print(f"  [{'ok' if not problems else 'XX'}] {ms:6.0f} ms  {instruction[:44]!r}")
            print("        " + re.sub(r"\s+", " ", out)[:160])
            for pr in problems:
                print(f"        -> {pr}")
        summary[model] = {"usable": len(TASKS) - bad, "of": len(TASKS),
                          "ms_p50": statistics.median(times), "ms_max": max(times)}
        print(f"  {model}: {len(TASKS) - bad}/{len(TASKS)} usable, "
              f"median {statistics.median(times):.0f} ms, worst {max(times):.0f} ms")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "compose_models.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print("\n" + json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
