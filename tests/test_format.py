#!/usr/bin/env python
"""Formatting a transcript into finished text.

Most of this file is about the two ways the feature can do harm: converting a
word the speaker meant literally, and touching romanized Indic text.

    python tests/test_format.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper.console import setup as _console  # noqa: E402
from livewhisper.format import (CHAT, CODE, PROSE, VERBATIM, auto_edit,  # noqa: E402
                                entities, finish, spoken_marks, style_for)

_console()
fails = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    fails += not ok
    print(f"[{'  ok  ' if ok else ' FAIL '}] {name}" + (f"  {detail}" if detail else ""))


def same(name: str, got: str, want: str) -> None:
    check(name, got == want, "" if got == want else f"got {got!r} want {want!r}")


def main() -> int:
    print("=== spoken punctuation ===")
    same("comma and question mark",
         finish("hey Sarthak comma how are you question mark"),
         "Hey Sarthak, how are you?")
    same("full stop starts the next sentence",
         finish("that works full stop send it tomorrow"),
         "That works. Send it tomorrow.")
    same("new paragraph",
         finish("the meeting is at five new paragraph bring the deck"),
         "The meeting is at five\n\nBring the deck.")
    same("new line", finish("line one new line line two"), "Line one\nLine two.")
    same("Whisper's own commas around a spoken one do not double it",
         finish("Hi Rahul, comma, thanks for the update, full stop, new paragraph, "
                "let's talk on Monday."),
         "Hi Rahul, thanks for the update.\n\nLet's talk on Monday.")
    same("an abbreviation keeps its dot before a spoken comma",
         finish("use e.g. comma like this"), "Use e.g., like this.")
    same("brackets close up against their contents",
         finish("open bracket this is aside close bracket done"),
         "(this is aside) done.")
    same("quoted speech", finish("he said quote it works unquote yesterday"),
         'He said "it works" yesterday.')
    same("a closing quote alone does not open a quotation",
         finish("he said it works unquote"), 'He said it works"')
    same("ellipsis", finish("well dot dot dot maybe not"), "Well… maybe not.")
    same("hyphen joins the words either side",
         finish("it is a well hyphen known problem"),
         "It is a well-known problem.")

    print("\n=== lists ===")
    same("bullets", finish("bullet point ship it bullet point measure it"),
         "- Ship it\n- Measure it")
    same("numbered list keeps counting",
         finish("numbered list next item write it next item test it"),
         "1. Write it\n2. Test it")
    same("a list item is not given a full stop",
         finish("bullet point one thing"), "- One thing")

    print("\n=== words that are also commands ===")
    for text in ("I think the period of the wave is short",
                 "add a dash of salt to it",
                 "there are two commas missing here",
                 "the quote of the day was good",
                 "this period was hard for everyone"):
        out = finish(text)
        check(f"left alone: {text!r}", out.rstrip(".") == text[0].upper() + text[1:],
              f"got {out!r}")
    same("but a real command still converts at the end",
         finish("send it today period"), "Send it today.")

    print("\n=== corrections said out loud ===")
    same("weekday corrected", finish("let us meet Monday I mean Tuesday"),
         "Let us meet Tuesday.")
    same("number corrected", finish("it costs 40 sorry 45"), "It costs 45.")
    same("time corrected", finish("call at 3pm I mean 4pm"), "Call at 4pm.")
    same("scratch that drops the cancelled sentence",
         finish("that plan is fine. scratch that. let us do it next week"),
         "Let us do it next week.")
    same("a lead-in before scratch that does not save the cancelled sentence",
         finish("The deadline is fine. Actually scratch that. We need one more week."),
         "We need one more week.")
    # The discourse marker, which is the reason the pass is restricted to a
    # closed set of kinds. Removing "I mean" here would change the sentence.
    for text in ("I mean it is fine either way",
                 "sorry I am late for the call",
                 "we met Monday I mean we talked about the deadline"):
        out = auto_edit(text)
        check(f"untouched: {text!r}", out == text, f"got {out!r}")

    print("\n=== emails, domains, numbers ===")
    same("email", entities("write to sarthak at gmail dot com today"),
         "write to sarthak@gmail.com today")
    same("domain", entities("go to livewhisper dot ai"), "go to livewhisper.ai")
    same("percent", entities("we grew 25 percent"), "we grew 25%")
    same("rupees", entities("it cost 500 rupees"), "it cost ₹500")
    same("dollars", entities("it cost 20 dollars"), "it cost $20")
    same("no digit, no change", entities("a few percent either way"),
         "a few percent either way")

    print("\n=== romanized Indic text ===")
    same("Hinglish keeps its words", finish("kal milte hain phir baat karte hain"),
         "Kal milte hain phir baat karte hain.")
    check("reduplication survives",
          finish("dheere dheere kaam ho jayega").startswith("Dheere dheere"),
          finish("dheere dheere kaam ho jayega"))
    # Native script has no case, so the capitalisation pass must be a no-op.
    native = "आज शाम को मिलते हैं"
    check("Devanagari passes through unchanged",
          finish(native).rstrip(".") == native, repr(finish(native)))
    same("a Hinglish command still works",
         finish("theek hai comma kal baat karte hain"),
         "Theek hai, kal baat karte hain.")
    same("a Hinglish correction: matlab",
         finish("Monday matlab Tuesday ko milte hain"),
         "Tuesday ko milte hain.")
    same("a Hinglish correction: nahi nahi",
         finish("main 5 nahi nahi 6 baje aaunga"),
         "Main 6 baje aaunga.")
    # "matlab" is also the most common filler in Hinglish. Nothing may move
    # unless the words either side of it are the same kind of thing.
    same("a Hinglish correction between days",
         finish("kal matlab parso tak ho jayega"), "Parso tak ho jayega.")
    same("an English day corrected to a Hindi one",
         finish("Monday matlab mangalvar ko milte hain"), "Mangalvar ko milte hain.")
    for text in ("matlab kya hai ye",
                 "wo aaya matlab kaam ho gaya",
                 "kal aana matlab zaroor aana",
                 "nahi nahi aisa mat karo"):
        out = auto_edit(text)
        check(f"Hinglish left alone: {text!r}", out == text, f"got {out!r}")

    print("\n=== styles ===")
    same("chat gets no trailing full stop", finish("lets ship it today", CHAT),
         "Lets ship it today")
    same("prose does", finish("lets ship it today", PROSE),
         "Lets ship it today.")
    same("code keeps its case and spells a flag",
         finish("git commit dash m fix comma then push", CODE),
         "git commit -m fix, then push")
    same("verbatim changes nothing", finish("hello  comma world", VERBATIM),
         "hello  comma world")
    check("slack is chat", style_for("slack.exe").name == "chat")
    check("the terminal is code", style_for("WindowsTerminal.exe").name == "code")
    check("an unknown app is prose", style_for("outlook.exe").name == "prose")
    check("an explicit override wins over the app",
          style_for("slack.exe", override="verbatim").name == "verbatim")
    check("a single pass can be switched off",
          style_for("", cfg={"auto_edit": False}).auto_edit is False)
    same("with auto-edit off the correction stays spoken",
         finish("let us meet Monday I mean Tuesday",
                style_for("", cfg={"auto_edit": False})),
         "Let us meet Monday I mean Tuesday.")

    print("\n=== voice shortcuts ===")
    saved = {"my address": "221B Baker Street, London NW1",
             "sign off": "Thanks,\nSarthak"}
    same("a cue on its own expands, exactly as saved",
         finish("My address.", PROSE, shortcuts=saved), "221B Baker Street, London NW1")
    same("line breaks in an expansion survive",
         finish("sign off", CHAT, shortcuts=saved), "Thanks,\nSarthak")
    same("a cue inside a sentence is just words",
         finish("I changed my address", PROSE, shortcuts=saved), "I changed my address.")
    same("no shortcuts configured changes nothing",
         finish("my address", PROSE, shortcuts=None), "My address")

    print("\n=== identifiers in code ===")
    same("camel case stops at an operator",
         finish("camel case user name equals five", CODE), "userName equals five")
    same("snake case stops at a spoken comma",
         finish("define snake case max retry count comma then", CODE),
         "define max_retry_count, then")
    same("pascal case", finish("new pascal case http client", CODE), "new HttpClient")
    same("constant case", finish("constant case max retries", CODE), "MAX_RETRIES")
    same("kebab case", finish("kebab case main nav bar", CODE), "main-nav-bar")
    same("talking about a convention is not using it",
         finish("the camel case convention is nice", CODE),
         "the camel case convention is nice")
    same("prose never builds identifiers",
         finish("we discussed the camel case convention", PROSE),
         "We discussed the camel case convention.")

    print("\n=== tidying ===")
    same("space before a comma", finish("hello , world and more"),
         "Hello, world and more.")
    same("lone i is capitalised", finish("i said i would and i did"),
         "I said I would and I did.")
    check("i inside a word is left alone", "indic" in finish("this is indic text"),
          finish("this is indic text"))
    same("a short answer gets no full stop", finish("yes"), "Yes")
    same("already punctuated is left alone", finish("Is that done?"),
         "Is that done?")
    same("empty stays empty", finish("   "), "   ")

    print("\n=== properties ===")
    samples = [
        "hey Sarthak comma how are you question mark",
        "bullet point ship it bullet point measure it",
        "let us meet Monday I mean Tuesday",
        "write to sarthak at gmail dot com comma please",
        "kal milte hain",
        "the period of the wave is short",
    ]
    stable = [s for s in samples if finish(finish(s)) != finish(s)]
    check("formatting twice changes nothing the second time", not stable,
          f"unstable: {stable}")

    long_text = " ".join(samples * 12)               # ~700 words
    t0 = time.perf_counter()
    for _ in range(20):
        finish(long_text)
    ms = (time.perf_counter() - t0) / 20 * 1000
    check("a long dictation formats in well under a millisecond per 100 words",
          ms < 25, f"{ms:.2f} ms for {len(long_text.split())} words")

    # Whatever happens, the words the user actually said must still be there.
    kept = finish("we shipped the build and it works")
    check("no words are lost from ordinary speech",
          all(w in kept.lower() for w in
              ("shipped", "build", "works")), kept)

    print(f"\n{'all passed' if not fails else f'{fails} FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
