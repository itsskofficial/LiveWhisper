#!/usr/bin/env python
"""Can a very small model format dictation better than rules, and safely?

Every candidate - the rules in livewhisper/format.py, and small local models
through Ollama - formats the same hand-written cases in tests/data/format_eval.json
and is scored on four things:

  exact      output identical to what a careful typist would have pasted
  similar    character-level similarity to that text, punctuation included
  word errs  words wrong or missing against the expected text
  invented   words in the output that were never spoken - the failure that
             matters most. A model that translates Hinglish, answers a question
             it was asked to punctuate, or follows an instruction inside the
             dictation, shows up here and nowhere else.

Latency is wall time per case with the model loaded, median and p95.

    python tests/bench_format_llm.py --models qwen2.5:0.5b,gemma3:1b
    python tests/bench_format_llm.py --models qwen2.5:1.5b --cpu
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper import format as fmt  # noqa: E402
from livewhisper.console import setup as _console  # noqa: E402

_console()
HERE = Path(__file__).resolve().parent
CASES = HERE / "data" / "format_eval.json"
OUT = HERE / "results"
WORD = re.compile(r"\w+", re.UNICODE)


def words(text: str) -> list:
    return [w.lower() for w in WORD.findall(text or "")]


def edit(a: list, b: list) -> int:
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1,
                         prev[j - 1] + (a[i - 1] != b[j - 1]))
        prev = cur
    return prev[-1]


def score(case: dict, out: str) -> dict:
    expect = case["expect"]
    spoken = set(words(case["input"])) | set(words(expect))
    got = words(out)
    return {
        "exact": out.strip() == expect.strip(),
        "similar": difflib.SequenceMatcher(a=expect, b=out.strip()).ratio(),
        "word_errs": edit(words(expect), got),
        "invented": [w for w in got if w not in spoken],
    }


def run(name: str, fn, cases: list, repeat_warm: bool = True) -> dict:
    if repeat_warm:
        fn(cases[0])                                   # load / warm
    rows, times = [], []
    for c in cases:
        t0 = time.perf_counter()
        try:
            out = fn(c)
        except Exception as e:                         # a failure is a result
            out = f"<error: {e}>"
        times.append((time.perf_counter() - t0) * 1000)
        rows.append({"id": c["id"], "cat": c["cat"], "out": out, **score(c, out)})
    n = len(rows)
    summary = {
        "system": name, "n": n,
        "exact": sum(r["exact"] for r in rows) / n,
        "similar": statistics.mean(r["similar"] for r in rows),
        "word_errs": sum(r["word_errs"] for r in rows),
        "invented_cases": sum(bool(r["invented"]) for r in rows),
        "ms_p50": statistics.median(times),
        "ms_p95": sorted(times)[int(0.95 * (n - 1))],
    }
    print(f"  {name:<28} exact {summary['exact']:>4.0%}  similar {summary['similar']:.3f}"
          f"  word errs {summary['word_errs']:>3}  invented in {summary['invented_cases']:>2}"
          f"  {summary['ms_p50']:>6.0f} ms p50  {summary['ms_p95']:>6.0f} ms p95",
          flush=True)
    return {"summary": summary, "rows": rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="")
    ap.add_argument("--cpu", action="store_true", help="run Ollama models on the CPU")
    ap.add_argument("--label", default="")
    ap.add_argument("--pace", type=float, default=0.0,
                    help="seconds between requests, for rate-limited cloud models")
    ap.add_argument("--modes", default="project,guard")
    ap.add_argument("--show", action="store_true", help="print every wrong output")
    ap.add_argument("--raw", action="store_true",
                    help="also score each model with no rules and no check")
    args = ap.parse_args()

    cases = json.loads(CASES.read_text(encoding="utf-8"))
    print(f"{len(cases)} cases\n")
    # The pipeline removes fillers before formatting, so the rules get the
    # same head start the model path does.
    from livewhisper.cleanup import remove_fillers
    results = {"rules": run("rules", lambda c: fmt.finish(remove_fillers(c["input"]),
                                                          fmt.STYLES[c["style"]]),
                            cases)}

    from livewhisper.llm_format import LLMFormatter, OllamaBackend

    for model in [m for m in args.models.split(",") if m]:
        if model.startswith("groq:"):
            from livewhisper.llm_format import GroqBackend
            backend = GroqBackend(model.split(":", 1)[1], timeout=10)
        else:
            backend = OllamaBackend(model, cpu=args.cpu)
        if args.raw:
            raw = LLMFormatter(backend, guard=False, rules_first=False)
            results[f"{model} raw"] = run(f"{model} raw",
                                          lambda c: raw.format(c["input"], c["style"]), cases)
        for mode in args.modes.split(","):
            formatter = LLMFormatter(backend, mode=mode)
            fell_back: list = []

            def one(c, formatter=formatter, fell_back=fell_back):
                if args.pace:
                    import time as _t
                    _t.sleep(args.pace)
                out = formatter.format(c["input"], c["style"])
                if formatter.last_reason not in ("ok", "rules only for this style"):
                    fell_back.append((c["id"], formatter.last_reason))
                return out
            formatter.format(cases[0]["input"], cases[0]["style"])   # load the model
            name = f"{model} {mode}"
            res = run(name, one, cases, repeat_warm=False)
            res["summary"]["fell_back"] = len(fell_back)
            res["fell_back"] = fell_back
            print(f"  {'':<28} used the rules instead in {len(fell_back)} cases")
            results[name] = res

    if args.show:
        for name, res in results.items():
            print(f"\n--- {name}: misses")
            for r in res["rows"]:
                if not r["exact"]:
                    case = next(c for c in cases if c["id"] == r["id"])
                    mark = f"  INVENTED {r['invented']}" if r["invented"] else ""
                    print(f"  [{r['id']}] want {case['expect']!r}\n"
                          f"  {' ' * len(r['id'])}   got  {r['out']!r}{mark}")

    OUT.mkdir(parents=True, exist_ok=True)
    label = args.label or ("cpu" if args.cpu else "gpu")
    (OUT / f"format_llm_{label}.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
