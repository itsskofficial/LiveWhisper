#!/usr/bin/env python
"""Does polish help, and is what it pastes safe?

Runs each case of tests/data/polish_eval.json the way a dictation goes: fillers
removed and rules applied, then the polisher. Reports, per model:

    distance     word edits from the reference polished text, before polish
                 (rules only) and after - lower is better
    accepted     share of cases where the guardrails let the model's text through
    violations   cases whose pasted text lost a must-keep word or contains a
                 must-not one (an answer, an executed instruction). Must be 0.
    skipped      cases polish correctly declined (Hinglish, too short)

    python tests/bench_polish.py --models groq:openai/gpt-oss-20b,builtin --pace 2.2 \
        --llm-dir %LOCALAPPDATA%/LiveWhisper/llm
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from livewhisper import format as fmt  # noqa: E402
from livewhisper import polish  # noqa: E402
from livewhisper.cleanup import remove_fillers  # noqa: E402
from livewhisper.console import setup as _console  # noqa: E402

_console()
CASES = ROOT / "tests" / "data" / "polish_eval.json"
OUT = ROOT / "tests" / "results"


def words(text: str) -> list:
    return re.findall(r"[a-z0-9']+", text.lower())


def distance(a: list, b: list) -> int:
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
        prev = cur
    return prev[-1]


def backend_for(name: str):
    if name.startswith("groq:"):
        from livewhisper.llm_format import GroqBackend
        return GroqBackend(name.split(":", 1)[1], timeout=15)
    if name == "builtin":
        return polish.LocalWriter(timeout=30)
    raise SystemExit(f"unknown model {name}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="groq:openai/gpt-oss-20b")
    ap.add_argument("--pace", type=float, default=0.0)
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--cases", default=str(CASES),
                    help="tests/data/polish_holdout.json was written after the guardrails "
                    "were tuned on polish_eval.json and is the fair score")
    ap.add_argument("--llm-dir", help="folder holding the GGUF models, e.g. an installed "
                    "copy's %%LOCALAPPDATA%%/LiveWhisper/llm, to avoid downloading them again")
    args = ap.parse_args()
    if args.llm_dir:
        from livewhisper import paths
        paths.LLM = Path(args.llm_dir)
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    n_skip = sum(c["kind"] == "skip" for c in cases)
    results = {}
    for name in [m for m in args.models.split(",") if m]:
        backend = backend_for(name)
        if hasattr(backend, "warm"):
            backend.warm()  # a model load is not polish latency
        p = polish.Polisher(backend, vocabulary="LiveWhisper, Dakshina, Kubernetes")
        rows, before_d, after_d, accepted, applicable, violations, skipped = [], 0, 0, 0, 0, [], 0
        times = []
        for c in cases:
            said = fmt.finish(remove_fillers(c["input"]), fmt.STYLES["prose"])
            why_not = polish.applies(said, language="en", romanized=False, respelled=False,
                                     style="prose", composed=False)
            if why_not:
                out, reason = said, f"skipped: {why_not}"
                skipped += c["kind"] == "skip"
            else:
                applicable += 1
                if args.pace:
                    time.sleep(args.pace)
                t0 = time.perf_counter()
                out = p.polish(said)
                times.append(time.perf_counter() - t0)
                reason = p.last_reason
                accepted += reason == "ok"
            exp = words(c["expect"])
            before_d += distance(words(said), exp)
            after_d += distance(words(out), exp)
            bad = [k for k in c["keep"] if k.lower() not in out.lower()] + \
                  [n for n in c["not"] if n.lower() in out.lower()]
            if bad:
                violations.append((c["id"], bad))
            rows.append({"id": c["id"], "said": said, "out": out, "reason": reason, "bad": bad})
            if args.show and out != said:
                print(f"  [{c['id']}] {reason}\n     {said}\n  -> {out}")
        times.sort()
        summary = {"cases": len(cases), "applicable": applicable, "accepted": accepted,
                   "distance_before": before_d, "distance_after": after_d,
                   "violations": len(violations), "hinglish_skipped": skipped,
                   "p50_s": round(times[len(times) // 2], 2) if times else None}
        results[name] = {"summary": summary, "violations": violations, "rows": rows}
        print(f"{name:32s} accepted {accepted}/{applicable}  distance {before_d} -> {after_d}"
              f"  violations {len(violations)}  hinglish skipped {skipped}/{n_skip}"
              f"  p50 {summary['p50_s']} s", flush=True)
        for v in violations:
            print(f"   VIOLATION {v}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{Path(args.cases).stem}.json").write_text(json.dumps(results, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
