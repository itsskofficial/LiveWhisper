#!/usr/bin/env python
"""Readiness check: exercise every feature and report what actually works.

Goes further than the unit tests - it drives the real components against the
real data and models, so the output is a truthful statement of what a demo
could show today.

    python verify.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

OK, BAD, WARN = "  ok  ", " FAIL ", " warn "
results: list = []


def report(name, state, detail=""):
    results.append((name, state))
    print(f"[{state}] {name}" + (f"  -  {detail}" if detail else ""))


def section(t):
    print(f"\n=== {t} ===")


def main() -> int:
    section("1. dictation core")
    try:
        from livewhisper.script.romanize import Romanizer
        t0 = time.time()
        r = Romanizer("hi")
        cases = [
            ("कल मैं office जाऊंगा", "kal main office jaunga"),
            ("मुझे नहीं पता क्यों वो नहीं आया", None),
            ("I will be there at five", "I will be there at five"),
        ]
        ok = True
        for src, want in cases:
            got = r.text(src)
            if want and got != want:
                ok = False
                report("romanization", BAD, f"{src} -> {got} (wanted {want})")
        if ok:
            report("romanization", OK, f"loaded and correct in {time.time()-t0:.1f}s")
    except Exception as e:
        report("romanization", BAD, str(e))

    try:
        from livewhisper.script.lexicon import get_lexicon
        lex = get_lexicon("hi")
        report("hindi lexicon", OK if len(lex) > 25000 else BAD, f"{len(lex):,} words")
        mr = get_lexicon("mr")
        report("marathi lexicon", OK if len(mr) > 25000 else BAD, f"{len(mr):,} words")
    except Exception as e:
        report("lexicons", BAD, str(e))

    try:
        from livewhisper.script.oov import get_model
        m = get_model()
        avail = m.load()
        got = m.spell(["लेंगी", "समझो"]) if avail else {}
        report("oov character model", OK if avail else WARN,
               f"available={avail} sample={got}")
    except Exception as e:
        report("oov character model", BAD, str(e))

    section("2. learning")
    try:
        from livewhisper.script.conventions import Conventions, validate_rule
        c = Conventions()
        c.learn("मुझे", "mujhe", "muze")
        first = dict(c.rules)
        c.learn("समझो", "samjho", "samzo")
        report("one correction does not generalise", OK if not first else BAD)
        report("two corrections promote a rule",
               OK if c.rules.get("jh") == "z" else BAD, str(c.rules))
        safe, _ = validate_rule("u", "oo")
        report("unsafe vowel rule refused", OK if not safe else BAD, "u -> oo")
        safe, _ = validate_rule("jh", "z")
        report("safe consonant rule allowed", OK if safe else BAD, "jh -> z")
    except Exception as e:
        report("learning", BAD, str(e))

    try:
        from livewhisper.onboarding import Onboarding
        o = Onboarding("hi")
        report("onboarding prompts", OK if len(o.prompts()) == 5 else BAD,
               f"{len(o.prompts())} sentences")
    except Exception as e:
        report("onboarding", BAD, str(e))

    section("3. screen reading")
    try:
        from livewhisper.context import capture, foreground_app
        app, title = foreground_app()
        report("foreground app detection", OK if app else WARN, f"{app} / {title[:40]}")
        t0 = time.time()
        ctx = capture()
        report("ui automation read", OK if ctx.method == "uia" else WARN,
               f"{ctx.method}, {len(ctx.text)} chars in {time.time()-t0:.1f}s")
    except Exception as e:
        report("screen reading", BAD, str(e))

    try:
        import rapidocr_onnxruntime  # noqa
        report("ocr fallback installed", OK, "for Chrome/Electron apps")
    except ImportError:
        report("ocr fallback installed", WARN, "pip install rapidocr_onnxruntime")

    section("4. writing assistant")
    try:
        from livewhisper import providers
        p = providers.build({"provider": "ollama", "model": "qwen2.5:7b"})
        report("provider available", OK, f"{p.name} / {getattr(p,'model','')}")
        from livewhisper.actions import Actions, looks_like_command
        a = Actions({"models": {"provider": "ollama", "model": "qwen2.5:7b"}})
        report("command intent detection",
               OK if looks_like_command("write a reply") and
               not looks_like_command("kal main office jaunga") else BAD)
        t0 = time.time()
        fixed = a.fix("i has went to the market yesterday")
        report("grammar fix", OK if fixed and "went" in fixed else BAD,
               f"{time.time()-t0:.1f}s -> {fixed}")
    except Exception as e:
        report("writing assistant", WARN, str(e)[:90])

    section("5. notes")
    try:
        import tempfile
        from livewhisper.notes import NoteBook
        nb = NoteBook(directory=Path(tempfile.mkdtemp()))
        nb.start("check")
        n = nb.append("hello there")
        report("notes write to disk", OK if n.path.exists() else BAD, n.path.name)
        nb.stop()
    except Exception as e:
        report("notes", BAD, str(e))

    section("6. transcription engine")
    try:
        from livewhisper import config as cfgio
        cfg = cfgio.load(ROOT / "config.yaml")
        from livewhisper.transcribe import build_backend
        b = build_backend(cfg["transcription"].get("backend", "auto"),
                          cfg["transcription"])
        report("backend constructs", OK, b.name)
        import numpy as np
        t0 = time.time()
        b.transcribe(np.zeros(16000, dtype=np.float32))
        report("transcribe runs", OK, f"silent 1s clip in {time.time()-t0:.1f}s")
    except Exception as e:
        report("transcription", WARN, str(e)[:90])

    section("7. app wiring")
    try:
        from livewhisper import config as cfgio
        cfg = cfgio.load(ROOT / "config.yaml")
        hk = cfg.get("hotkeys", {})
        need = ["record", "write", "fix", "notes", "devanagari", "cancel"]
        missing = [k for k in need if k not in hk]
        report("all hotkeys configured", OK if not missing else BAD,
               ", ".join(f"{k}={hk.get(k)}" for k in need))
        from livewhisper.main import App  # noqa
        from livewhisper.wizard import Wizard  # noqa
        from livewhisper.gui import SECTIONS
        report("app + gui import", OK, f"panels: {', '.join(SECTIONS)}")
    except Exception as e:
        report("app wiring", BAD, str(e))

    section("8. installed copy")
    inst = Path("E:/Apps/LiveWhisper")
    if inst.exists():
        report("install present", OK, str(inst))
        prof = inst / "profiles.json"
        if prof.exists():
            try:
                d = json.loads(prof.read_text(encoding="utf-8"))
                g = (d.get("_global") or {}).get("conventions", {})
                report("install profile", WARN,
                       f"exists - rules={g.get('rules')} "
                       f"(wizard will NOT auto-run; delete to demo it)")
            except Exception:
                report("install profile", WARN, "exists but unreadable")
        else:
            report("install profile", OK, "absent - wizard runs on first launch")
    else:
        report("install present", BAD, "E:/Apps/LiveWhisper missing")

    print()
    bad = [n for n, s in results if s == BAD]
    warn = [n for n, s in results if s == WARN]
    print(f"{len(results)} checks: {len(results)-len(bad)-len(warn)} ok, "
          f"{len(warn)} warn, {len(bad)} failed")
    if bad:
        print("FAILED: " + ", ".join(bad))
        return 1
    if warn:
        print("warnings: " + ", ".join(warn))
    return 0


if __name__ == "__main__":
    sys.exit(main())
