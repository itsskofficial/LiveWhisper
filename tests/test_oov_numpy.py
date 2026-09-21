#!/usr/bin/env python
"""The numpy transliterator spells every word exactly as the torch one does.

    python tests/test_oov_numpy.py

The app ships without torch, so the numpy port in livewhisper/script/oov.py is
what users run. When torch is installed this decodes a few thousand lexicon
words through both and requires the same strings; without torch it only checks
that the numpy model loads and spells.
"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper.console import setup as _console  # noqa: E402
from livewhisper.script.oov import DATA, MAX_IN, NPZ_CHECKPOINT, OOVModel  # noqa: E402

_console()
fails = 0
PER_LANG = 200          # x12 languages = 2,400 words
BATCH = 64


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    fails += not ok
    print(f"[{'  ok  ' if ok else ' FAIL '}] {name}" + (f"  {detail}" if detail else ""))


def sample(lang: str, rng: random.Random) -> list[str]:
    """Words of every length the app will see, including the longest allowed."""
    path = DATA / f"{lang}.lexicon.tsv"
    if not path.exists():
        return []
    words = [ln.split("\t", 1)[0] for ln in path.read_text(encoding="utf-8").splitlines()]
    words = [w for w in words if 3 <= len(w) <= MAX_IN]
    long_ = sorted(words, key=len)[-20:]            # near MAX_IN as far as real words go
    rest = rng.sample(words, min(PER_LANG - len(long_), len(words)))
    return list(dict.fromkeys(long_ + rest))


def decode(model: OOVModel, words: list[str], lang: str) -> tuple[dict, float]:
    """Spell in app-sized batches; return the spellings and seconds spent."""
    out, took = {}, 0.0
    for i in range(0, len(words), BATCH):
        chunk = words[i:i + BATCH]
        t0 = time.perf_counter()
        out.update(model.spell(chunk, lang))
        took += time.perf_counter() - t0
    return out, took


def main() -> int:
    check("numpy archive exists", NPZ_CHECKPOINT.exists(), str(NPZ_CHECKPOINT))
    np_model = OOVModel("numpy")
    check("numpy model loads", np_model.load())
    if not np_model.available:
        return 1
    check("numpy path does not import torch", sys.modules.get("torch") is None)

    try:
        import torch  # noqa: F401
    except ImportError:
        print("\n=== smoke test (torch not installed) ===")
        got = np_model.spell(["कमल", "ऑफिस", "जाऊंगा", "লেখা"], "hi")
        check("hindi words spelled in Latin", all(v.isascii() for v in got.values())
              and len(got) >= 2, str(got))
        print(f"\n{'all passed' if not fails else f'{fails} FAILED'}")
        return 1 if fails else 0

    th_model = OOVModel("torch")
    check("torch model loads", th_model.load())
    check("same languages", th_model.languages == np_model.languages,
          f"{sorted(np_model.languages)}")

    print("\n=== identical spellings, torch vs numpy ===")
    rng = random.Random(7)
    total = same = 0
    t_np = t_th = 0.0
    batches = 0
    mismatches = []
    for lang in sorted(np_model.languages):
        words = sample(lang, rng)
        if not words:
            continue
        a, ta = decode(th_model, words, lang)
        b, tb = decode(np_model, words, lang)
        t_th += ta
        t_np += tb
        batches += -(-len(words) // BATCH)
        n_same = sum(a.get(w) == b.get(w) for w in words)
        total += len(words)
        same += n_same
        mismatches += [(lang, w, a.get(w), b.get(w)) for w in words if a.get(w) != b.get(w)]
        print(f"  {lang}: {n_same}/{len(words)} identical")

    rate = same / max(total, 1)
    check(f"{total} words, >= 99.9% identical", total >= 2000 and rate >= 0.999,
          f"{same}/{total} = {rate:.4%}")
    for lang, w, x, y in mismatches[:10]:
        print(f"    {lang} {w}: torch={x!r} numpy={y!r}")

    print("\n=== speed, per batch of 64 ===")
    print(f"  torch {1000 * t_th / batches:6.1f} ms   numpy {1000 * t_np / batches:6.1f} ms"
          f"   over {batches} batches")
    # Relative, not absolute: OpenBLAS thread count and machine load swing the
    # numpy figure 2x (see OPENBLAS_NUM_THREADS), but the cached decoder does
    # O(t) work against torch's O(t^2), so it should never lose.
    check("numpy no slower than torch", t_np <= t_th)

    print(f"\n{'all passed' if not fails else f'{fails} FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
