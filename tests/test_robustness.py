#!/usr/bin/env python
"""Robustness: does anything in the chain crash, hang, or corrupt on ugly input?

A dictation app eats whatever the speech engine emits and whatever happens to be
in the focused field, and neither is under our control. Whisper produces empty
strings on silence, repeated tokens on music, and stray CJK on noise. The field
may hold a URL, a code block, an emoji wall, or 50 KB of someone else's text.

None of that may crash the app, and - more subtly - none of it may poison the
learned profile, because a corrupt profile degrades every future dictation
silently. This suite pushes the nasty cases through the real pipeline and
asserts on both.

    python tests/test_robustness.py
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper.console import setup as _console  # noqa: E402
from livewhisper.context import ScreenContext  # noqa: E402
from livewhisper.pipeline import Pipeline  # noqa: E402
from livewhisper.profile import ProfileStore  # noqa: E402
from livewhisper.script.conventions import Conventions, tokenize  # noqa: E402
from livewhisper.script.languages import CODES, WORD, has_indic  # noqa: E402
from livewhisper.script.romanize import Romanizer  # noqa: E402

_console()

failures: list = []
checks = 0


def ctx(field: str, app: str = "chrome.exe") -> ScreenContext:
    """A screen reading with `field` under the cursor."""
    return ScreenContext(app=app, title="t", text=field, focused_text=field,
                         method="uia")


def check(name: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    print(f"[{'  ok  ' if ok else ' FAIL '}] {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        failures.append(f"{name} — {detail}")


def survives(name: str, fn, *a, **kw):
    """Call fn and fail the check instead of the suite if it raises."""
    global checks
    try:
                                                 # noqa: E116
        out = fn(*a, **kw)
    except Exception as exc:                      # noqa: BLE001 - that's the point
        checks += 1
        failures.append(f"{name} — {type(exc).__name__}: {exc}")
        print(f"[ FAIL ] {name}  raised {type(exc).__name__}: {exc}")
        return None
    checks += 1
    print(f"[  ok  ] {name}")
    return out


# Inputs chosen because each one has a plausible real source, noted alongside.
NASTY = [
    ("empty", ""),
    ("whitespace only", "   \t \n  "),
    ("single space-less newline wall", "\n" * 200),
    ("one native char", "क"),
    ("lone combining mark", "्"),      # virama with no base letter
    ("lone joiner", "‍"),         # ZWJ
    ("marks only", "्‍ां"),
    ("emoji wall", "🙏🙏🙏 कैसे हो 🎉🎉"),
    ("url with native text", "देखो https://example.com/a?b=1&c=२ पर"),
    ("code block", "def f(x):\n    return x  # क्या\n"),
    ("markdown", "**कल** _office_ `जाऊंगा` [link](http://x.io)"),
    ("mixed four scripts", "क्या हो আমি நான் අංශු hello"),
    ("native digits", "मेरे पास २५ रुपये हैं"),
    ("arabic-script rtl", "میں اسکول"),
    ("repeated token (whisper on music)", "la " * 300),
    ("no spaces at all", "क्याकररहेहोआजकलतुम"),
    ("html entities", "&amp; क्या &lt;tag&gt; हो"),
    ("control chars", "क्या\x00हो\x07 ठीक\x1b[31m है"),
    ("nbsp and zero width space",
     "क्या हो​ठीक"),
    ("surrogate-ish astral", "𝕜𝕒𝕝 मैं 𝟙𝟚 जाऊंगा"),
    ("very long single word", "क" * 600),
    ("50k of text", ("कल मैं office जाऊंगा और " * 2000)),
    ("only punctuation", "!!! ... ?!?! -- ,,,"),
    ("tabs inside", "क्या\tहो\tठीक"),
]


def main() -> int:
    print("=== 1. romanizer eats anything, in every language ===")
    # 24 inputs x 12 languages = 288 calls through lexicon, model and conventions.
    worst = (0.0, "")
    for code in CODES:
        r = Romanizer(code)
        for label, text in NASTY:
            t0 = time.perf_counter()
            try:
                out = r.text(text)
            except Exception as exc:              # noqa: BLE001
                failures.append(f"{code}/{label} — {type(exc).__name__}: {exc}")
                print(f"[ FAIL ] {code} {label}  {type(exc).__name__}: {exc}")
                continue
            dt = time.perf_counter() - t0
            if dt > worst[0]:
                worst = (dt, f"{code}/{label}")
            if not isinstance(out, str):
                failures.append(f"{code}/{label} returned {type(out)}")
    print(f"[  ok  ] 12 languages x {len(NASTY)} nasty inputs, no crash")
    check("slowest single input under 5s", worst[0] < 5.0,
          f"{worst[1]} took {worst[0]:.2f}s")

    print("\n=== 2. output invariants ===")
    r = Romanizer("hi")
    check("empty in, empty out", r.text("") == "")
    check("pure English is untouched",
          r.text("let's ship it on Friday, ok?") == "let's ship it on Friday, ok?")
    check("URL survives romanization",
          "https://example.com/a?b=1" in r.text("देखो https://example.com/a?b=1 पर"),
          r.text("देखो https://example.com/a?b=1 पर"))
    check("code identifiers survive",
          "return x" in r.text("def f(x):\n    return x  # क्या"))
    out = r.text("🙏🙏🙏 कैसे हो 🎉🎉")
    check("emoji survive", "🙏" in out and "🎉" in out, out)
    check("newlines preserved", r.text("क्या\nहो").count("\n") == 1)
    check("no control chars introduced",
          not any(c in r.text("क्या हो") for c in "\x00\x07\x1b"))
    check("lone combining mark does not vanish into an exception",
          isinstance(r.text("्"), str))
    out = r.text("क्या हो আমি নই")
    check("only the selected language is converted, others left alone",
          "আমি" in out, out)

    print("\n=== 3. tokenizer invariants ===")
    check("tokenizer never splits a native word",
          tokenize("അധ്യാപക") ==
          ["അധ്യാപക"])
    check("tokenizer drops digits", tokenize("abc 123 def") == ["abc", "def"])
    check("tokenizer keeps apostrophes", tokenize("don't stop") == ["don't", "stop"])
    check("tokenizer on empty", tokenize("") == [])
    check("mark alone yields no token", tokenize("्") == [])
    check("WORD matches nothing in pure punctuation", WORD.findall("!!! ...") == [])

    print("\n=== 4. conventions cannot be poisoned by garbage ===")
    c = Conventions()
    for bad in ("", "   ", "\x00", "क" * 600, "🙏", "a" * 400):
        survives(f"learn({bad[:12]!r}) does not raise", c.learn, "क", "ka", bad)
    check("no rule learned from a single garbage correction",
          all(len(k) <= 3 for k in c.rules), str(c.rules)[:120])
    c2 = Conventions()
    c2.learn("मुझे", "mujhe", "muze")
    c2.learn("झूठ", "jhooth", "zooth")
    check("legitimate rule still promoted after two words", c2.rules.get("jh") == "z",
          str(c2.rules))
    survives("apply() on a 600-char word", c2.apply, "k" * 600)

    print("\n=== 5. habits survive hostile field contents ===")
    with tempfile.TemporaryDirectory() as td:
        store = ProfileStore(Path(td) / "p.json")
        for label, text in NASTY:
            survives(f"observe_text({label})", store.observe_text, "x.exe", text)
        survives("save after garbage", store.save)
        store2 = ProfileStore(Path(td) / "p.json")
        survives("reload after garbage", store2.load)
        h = store2.get("x.exe").habits
        check("habit rates stay in [0,1]",
              all(0.0 <= v <= 1.0 for v in h.to_dict().get("habits", {}).values()),
              str(h.to_dict().get("habits")))

    print("\n=== 6. full pipeline, including the learning path ===")
    with tempfile.TemporaryDirectory() as td:
        store = ProfileStore(Path(td) / "p.json")
        cfg = {"language": "hi", "script": {"mode": "auto"}}
        pipe = Pipeline(cfg, store)
        for label, text in NASTY:
            d = survives(f"process({label})", pipe.process, text,
                         ctx(""))
            if d is not None and not isinstance(d.text, str):
                failures.append(f"process({label}) gave {type(d.text)}")

        # The reverse path is the dangerous one: it compares what we pasted with
        # whatever is in the field, and a mismatch there is what corrupted a real
        # profile once already.
        pipe.process("कल मैं office जाऊंगा",
                     ctx(""))
        for label, text in NASTY:
            survives(f"learn_from_screen({label})", pipe.learn_from_screen,
                     ctx(text))
        glob = store.get(ProfileStore.GLOBAL).conventions
        check("garbage fields taught no spelling rules", not glob.rules,
              str(glob.rules)[:160])
        check("garbage fields taught no overrides",
              len(glob.overrides) == 0, str(list(glob.overrides.items())[:3]))

    print("\n=== 7. language resolution never throws ===")
    with tempfile.TemporaryDirectory() as td:
        pipe = Pipeline({"language": "hi"}, ProfileStore(Path(td) / "p.json"))
        for heard in (None, "", "hi", "xx", "zz-ZZ", "HINDI", "en", 0, [], {}):
            survives(f"resolve_language(heard={heard!r})",
                     pipe.resolve_language, "क्या हो",
                     heard)
        check("unknown language code falls back, not crashes",
              isinstance(Romanizer("xx").text("क्या"), str))

    print("\n=== 8. has_indic agrees with reality ===")
    check("plain English is not Indic", not has_indic("hello world"))
    check("emoji alone is not Indic", not has_indic("🙏🎉"))
    check("a joiner alone is not Indic", not has_indic("‍"))
    check("one Devanagari letter is Indic", has_indic("क"))
    check("Sinhala is Indic", has_indic("අංශ"))

    print(f"\n{checks} checks")
    if failures:
        print(f"\n{len(failures)} FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nrobust against every input thrown at it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
