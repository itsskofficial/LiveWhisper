#!/usr/bin/env python
"""Does Ctrl+Alt+F fix the mistakes, and leave the rest alone?

The built-in model handed back "i has went through the screens yesterday and
they looks good. me and dev will fixed the last two" unchanged, and the app
said it already looked correct. Each case is a message with real mistakes that
must be gone afterwards, or a message with none - lowercase chat, Hinglish,
learned spellings like "muze" - that must come back exactly as it was.

TUNE is what prompts were written against; HELD_OUT was written at the same
time and not looked at until the prompt was settled.

    python tests/bench_fix.py --models builtin --prompt old,new \\
        --llm-dir %LOCALAPPDATA%/LiveWhisper/llm
    python tests/bench_fix.py --models groq --prompt old,new
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper.actions import FIX_SYSTEM, _unwrap  # noqa: E402
from livewhisper.console import setup as _console  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_compose import provider  # noqa: E402

_console()
OUT = Path(__file__).resolve().parent / "results"

# The prompt before this bench, for a before/after.
OLD_FIX = """You correct grammar, spelling and punctuation.

Rules:
- Output ONLY the corrected text. Nothing else.
- Change as little as possible. Do not rewrite, restructure, or improve style.
- Preserve the writer's voice exactly, including deliberate informality,
  lowercase, slang, and romanised Hindi or Marathi spellings. Those are not
  errors.
- If the text is already correct, output it unchanged."""

# (text, mistakes that must be gone, words that must survive); no mistakes
# listed means the text must come back exactly as it was.
TUNE = [
    ("hi ananya, i has went through the screens yesterday and they looks good. me and dev will "
     "fixed the last two before friday", ["i has", "they looks", "will fixed"], ["ananya", "friday"]),
    ("i has went to the office yesterday and meet with priya about the the release",
     ["i has", "the the", "and meet"], ["priya"]),
    ("their going to send the invoice tomorrow, can you checked it once",
     ["their going", "can you checked"], ["invoice"]),
    ("she dont know where the keys is", ["she dont", "keys is"], ["keys"]),
    ("kal main office gaya tha aur priya se mila", [], []),
    ("lol ok see you at 5", [], []),
]
HELD_OUT = [
    ("we was planning to meets the client on monday but he cancel it",
     ["we was", "to meets", "he cancel it"], ["client", "monday"]),
    ("can you sends me the file what you was talking about", ["you sends", "you was"], ["file"]),
    ("i have attach the report and the numbers looks fine to me",
     ["have attach", "numbers looks"], ["report"]),
    ("my manager dont like when we pushes on friday", ["manager dont", "we pushes"], ["friday"]),
    ("the builds is failing since morning because of the the new config",
     ["builds is", "the the"], ["config"]),
    ("yaar kal ka plan cancel ho gaya, sorry", [], []),
    ("thanks, see you tmrw", [], []),
    ("muze nahi pata tha ki meeting cancel hai", [], []),
]


def judge(text: str, out: str, gone: list, keep: list) -> list:
    low = out.lower()
    if not gone:
        return [] if out.strip() == text.strip() else ["changed a message with no mistakes"]
    # Whole words: "have attach" is not left over in "have attached".
    problems = [f"still has {g!r}" for g in gone if re.search(rf"\b{re.escape(g)}\b", low)]
    problems += [f"lost {k!r}" for k in keep if k not in low]
    if out.strip() == text.strip():
        problems.insert(0, "returned unchanged")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="builtin")
    ap.add_argument("--prompt", default="old,new")
    ap.add_argument("--llm-dir")
    args = ap.parse_args()

    summary = {}
    for model in args.models.split(","):
        p = provider(model, args.llm_dir)
        p.chat("Reply with ok.", "ok", temperature=0)
        for which in args.prompt.split(","):
            system = OLD_FIX if which == "old" else FIX_SYSTEM
            for name, cases in (("tune", TUNE), ("held_out", HELD_OUT)):
                ok = 0
                print(f"\n=== {model} / {which} prompt / {name} ===")
                for text, gone, keep in cases:
                    out = _unwrap(p.chat(system, text, temperature=0.0), text)
                    problems = judge(text, out, gone, keep)
                    ok += not problems
                    print(f"  [{'ok' if not problems else 'XX'}] {out[:110]}")
                    for pr in problems:
                        print(f"        -> {pr}")
                summary[f"{model} / {which} / {name}"] = f"{ok}/{len(cases)}"
        if model == "builtin":
            from livewhisper import llm
            llm.server("writer").stop()

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "fix_prompt.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print("\n" + json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
