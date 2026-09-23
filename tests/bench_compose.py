#!/usr/bin/env python
"""Which model writes text for Ctrl+Alt+W, and does it write it well?

"Reply saying I can't make Thursday" has to produce a finished message in about
the time it takes to reach for the mouse. Each candidate writes the same
replies; the output is printed for reading and checked for the failures that
make a reply unusable: a preamble ("Here's a draft"), quotes round it, a missing
key fact, the wrong language, or a sign-off with a placeholder name.

Replies to an email are also checked for being an email: a greeting with the
sender's first name, and a sign-off with the user's name. They used to stop at
one line ("Sure, I'll be there."), because the prompt left the sign-off out
without the user's name and nothing gave it the name. A chat reply must have
neither.

    python tests/bench_compose.py --models qwen3:1.7b,qwen2.5:3b          # Ollama
    python tests/bench_compose.py --models builtin,groq --prompt old,new \\
        --llm-dir %LOCALAPPDATA%/LiveWhisper/llm
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

from livewhisper.actions import (COMPOSE_SYSTEM, FIX_SYSTEM, _unwrap, looks_like_email,  # noqa: E402
                                 sender_first_name, shape_email)
from livewhisper.console import setup as _console  # noqa: E402

_console()
OUT = Path(__file__).resolve().parent / "results"
SIGNER = "Sarthak"

# The prompt before emails were written as emails, for a before/after.
OLD_COMPOSE = """You write text for the user to send, as the user.

The screen shows what the user is looking at - usually a message someone else
sent them. The user tells you what to write back. You are the user replying:
never write as the other person, never address the user by name.

Rules:
- Output ONLY the finished text, ready to paste. No preamble ("Here's a
  draft"), no quotes around it, no explanation, no subject line.
- Match the register of the conversation on screen: a chat gets a chat reply,
  an email gets an email reply.
- Keep it as short as the situation allows.
- Never use placeholders like [Your Name] or [Date]. If you do not know the
  user's name, leave the sign-off out.
- If the instruction is in Hindi or Hinglish, write the reply in Hinglish,
  in Latin letters.
{style}"""

EMAIL = """From: Priya Raghavan
Subject: Design review on Thursday

Hi Sarthak, can we do the design review this Thursday at 3pm? I'd like to go
through the new onboarding flow before the release. Let me know. Thanks, Priya"""

MAIL_ANANYA = """Design review on Friday
Ananya Rao <ananya@example.com> to me
Hi,

Could you join the design review on Friday at 5 pm? We'll go through the new
onboarding screens and decide what ships next week.

Let me know if the time works.

Thanks,
Ananya"""

SLACK = """#release  Marcus: is the installer fix merged yet? QA wants to start at 5"""

# (kind, instruction, screen, checks); "email" is the sender's first name when
# the reply must be a whole email, "chat" when it must not be one.
TASKS = [
    ("compose", "reply saying I can't make Thursday but Friday morning works",
     EMAIL, {"has": ["friday"], "not": ["here's", "here is", "[your name]", "subject:"], "email": "priya"}),
    ("compose", "tell him yes it's merged and the build is running now",
     SLACK, {"has": ["merged"], "not": ["here's", "[", "dear"], "chat": True}),
    ("compose", "reply that I'll send the deck tonight and thank her",
     EMAIL, {"has": ["tonight"], "not": ["here's", "[your name]"], "email": "priya"}),
    ("compose", "bol do ki main kal subah call karunga",
     SLACK, {"has": ["kal", "call"], "not": ["here's", "[", "tomorrow morning"], "chat": True}),
    ("compose", "write a short note to the team that the office is closed on Monday",
     "", {"has": ["monday", "closed"], "not": ["here's", "[your name]", "subject:"]}),
    ("compose", "Reply saying that I'll be there and I'll bring the onboarding screens with me.",
     MAIL_ANANYA, {"has": ["onboarding"], "not": ["here's", "[your name]"], "email": "ananya"}),
    ("fix", "i has went to the office yesterday and meet with priya about the the release",
     "", {"has": ["went", "met", "priya"], "not": ["here's", "corrected", "the the"]}),
    ("fix", "kal main office gaya tha aur priya se mila, release ki baat hui",
     "", {"has": ["kal", "office", "priya"], "not": ["here's", "yesterday i"]}),
]


def provider(name: str, llm_dir: str | None):
    if name == "builtin":
        if llm_dir:
            from livewhisper import paths
            paths.LLM = Path(llm_dir)
        from livewhisper.providers import Builtin
        return Builtin()
    if name.startswith("groq"):
        from livewhisper.providers import GROQ_WRITER, OpenAICompatible
        model = name.split(":", 1)[1] if ":" in name else GROQ_WRITER
        return OpenAICompatible("groq", "https://api.groq.com/openai/v1/chat/completions",
                                "GROQ_API_KEY", model)
    from livewhisper.providers import Ollama
    return Ollama(name)


def structure(out: str, check: dict) -> list:
    lines = [ln.strip() for ln in out.strip().splitlines() if ln.strip()]
    if not lines:
        return ["empty"]
    problems = []
    if check.get("email"):
        first = lines[0].lower()
        if not re.match(rf"(hi|hello|hey|dear)\b.*\b{check['email']}\b", first):
            problems.append(f"no greeting to {check['email'].title()}")
        if SIGNER.lower() not in lines[-1].lower():
            problems.append("no sign-off with the user's name")
    if check.get("chat"):
        if re.match(r"(hi|hello|dear)\b", lines[0].lower()) or SIGNER.lower() in lines[-1].lower():
            problems.append("a chat reply written as an email")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="qwen3:1.7b,qwen3:4b,qwen2.5:3b,qwen2.5:7b")
    ap.add_argument("--prompt", default="new", help="old, new, or old,new for a before/after")
    ap.add_argument("--llm-dir", help="folder with the app's GGUF models, e.g. an installed copy's "
                    "%%LOCALAPPDATA%%/LiveWhisper/llm, for --models builtin")
    args = ap.parse_args()

    summary = {}
    for model in [m for m in args.models.split(",") if m]:
        p = provider(model, args.llm_dir)
        for which in [w for w in args.prompt.split(",") if w]:
            label = f"{model} / {which} prompt"
            p.chat("Reply with ok.", "ok", temperature=0)            # load it
            times, bad, shape = [], 0, 0
            print(f"\n=== {label} ===")
            for kind, instruction, screen, check in TASKS:
                if kind == "compose":
                    user = (f"What is on screen right now:\n-----\n{screen}\n-----\n\n"
                            if screen else "") + f"Instruction: {instruction}"
                    if which == "old":
                        system = OLD_COMPOSE.format(style="")
                    else:
                        system = COMPOSE_SYSTEM.format(
                            style="", name=f"- The user's name is {SIGNER}; sign emails with it.")
                else:
                    user, system = instruction, FIX_SYSTEM
                t0 = time.perf_counter()
                out = p.chat(system, user, temperature=0.3 if kind == "compose" else 0)
                if kind == "compose" and which == "new" and looks_like_email(screen):
                    # What Actions.compose does after the model: the reply to an
                    # email gets a greeting and the user's sign-off.
                    out = shape_email(_unwrap(out, instruction), sender_first_name(screen), SIGNER)
                ms = (time.perf_counter() - t0) * 1000
                times.append(ms)
                low = out.lower()
                problems = [f"missing {w!r}" for w in check["has"] if w not in low]
                problems += [f"contains {w!r}" for w in check["not"] if w in low]
                form = structure(out, check) if kind == "compose" else []
                bad += bool(problems or form)
                shape += bool(form)
                print(f"  [{'ok' if not (problems or form) else 'XX'}] {ms:6.0f} ms  {instruction[:44]!r}")
                print("        " + re.sub(r"\s+", " ", out)[:200])
                for pr in problems + form:
                    print(f"        -> {pr}")
            summary[label] = {"usable": len(TASKS) - bad, "of": len(TASKS), "wrong_shape": shape,
                              "ms_p50": round(statistics.median(times)), "ms_max": round(max(times))}
            print(f"  {label}: {len(TASKS) - bad}/{len(TASKS)} usable, {shape} the wrong shape, "
                  f"median {statistics.median(times):.0f} ms")
        if model == "builtin":
            from livewhisper import llm
            llm.server("writer").stop()

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "compose_models.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print("\n" + json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
