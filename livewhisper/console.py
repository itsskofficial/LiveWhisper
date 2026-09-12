"""Make stdout safe for the scripts that print Devanagari, Tamil and friends.

A default Windows console is cp1252, which has no code point for क. Printing one
raises UnicodeEncodeError and kills the script mid-run - so every test and check
tool in this repo died on the first line that named a word, on the exact console
the README tells contributors to use.

    python -m tools.check_data
    UnicodeEncodeError: 'charmap' codec can't encode characters in position 9-12

The tests were passing; only the reporting was broken, which is the worst
possible failure mode: it looks like the code is wrong when it isn't.

Call `setup()` at the top of anything that prints native script.
"""

from __future__ import annotations

import sys


def setup() -> None:
    """Switch stdout/stderr to UTF-8, replacing anything the console can't draw.

    `errors="replace"` rather than `"strict"`: a console that genuinely cannot
    render a glyph should show a box, not abort the run.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue          # redirected to something that isn't a TextIO
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass              # already detached, or a stream that refuses


def ascii_only() -> bool:
    """True if the console still can't represent native script after setup().

    Lets a caller fall back to code points (`U+0915`) instead of printing a row
    of boxes.
    """
    enc = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        "क".encode(enc)
    except (UnicodeEncodeError, LookupError):
        return True
    return False
