"""Finishing the text: what you would have typed, not what you said.

A speech model returns a sentence. A person typing produces a *message*: line
breaks where the thought turned, a list that looks like a list, the correction
they made out loud already applied, brackets closed, and no "um". Every
commercial dictation app does this step and calls it AI formatting. Almost none
of it needs a model.

Four passes, in this order, because each assumes the previous has run:

    spoken marks   "comma", "new paragraph", "bullet point"  ->  ,  \\n\\n  -
    said again     "meet Monday, I mean Tuesday"             ->  "meet Tuesday"
    entities       "sarthak at gmail dot com"                ->  sarthak@gmail.com
    tidy           spacing, capitals after a full stop, lone "i"

Deliberately deterministic. A language model could do this - the app can
already call one - but it would cost about a second per dictation, it would
sometimes rewrite words that were actually said, and it could not run on the
machines this app promises to run on. Rules are instant, inspectable, and when
one is wrong you can see which.

Two dangers shape most of the code here, and tests/test_format.py is mostly
about them:

  Command words are ordinary words too. "The period of the wave", "a dash of
  salt", "two commas". Every single-word command is guarded by its neighbours.

  Romanized Indic text must survive untouched. It reaches this module already
  romanized, in Latin script, so every English rule can see it. "kal milte
  hain" must not collect capitals it never had, and reduplication ("dheere
  dheere") is grammar rather than a stutter - the same trap cleanup.py had to
  avoid.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

# --------------------------------------------------------------------- style


@dataclass(frozen=True)
class Style:
    """What the field in front of us wants.

    A chat box and a terminal disagree about nearly everything, and guessing
    wrong is worse than doing nothing: a trailing full stop in Slack reads as
    annoyance, and a capital letter in a shell is a broken command.
    """

    name: str = "prose"
    marks: bool = True             # spoken punctuation and line breaks
    auto_edit: bool = True         # apply corrections made out loud
    entities: bool = True          # emails, domains, percentages, money
    capitals: bool = True          # sentence case
    final_stop: bool = True        # finish a sentence that has no ending
    flag_dash: bool = False        # "dash m" -> "-m", the way a flag is typed
    identifiers: bool = False      # "camel case user name" -> userName


PROSE = Style("prose")
CHAT = Style("chat", final_stop=False)
CODE = Style("code", capitals=False, final_stop=False, entities=False,
             auto_edit=False, flag_dash=True, identifiers=True)
VERBATIM = Style("verbatim", marks=False, auto_edit=False, entities=False,
                 capitals=False, final_stop=False)

STYLES = {s.name: s for s in (PROSE, CHAT, CODE, VERBATIM)}

# Matched against the process name, lowercased. Browsers are deliberately
# absent: the same chrome.exe is Gmail and Slack, and prose is the safer guess.
APP_STYLE = {
    "code.exe": CODE, "cursor.exe": CODE, "devenv.exe": CODE,
    "idea64.exe": CODE, "pycharm64.exe": CODE, "sublime_text.exe": CODE,
    "windowsterminal.exe": CODE, "cmd.exe": CODE, "powershell.exe": CODE,
    "pwsh.exe": CODE, "wt.exe": CODE, "alacritty.exe": CODE,
    "slack.exe": CHAT, "discord.exe": CHAT, "teams.exe": CHAT,
    "ms-teams.exe": CHAT, "telegram.exe": CHAT, "whatsapp.exe": CHAT,
    "signal.exe": CHAT,
}


def style_for(app: str = "", override: str | None = None,
              cfg: dict | None = None) -> Style:
    """The style for this app: an explicit setting first, then the app table.

    `cfg` can only turn passes OFF, never on. The shipped config lists every
    pass as true, and honouring that as an instruction would quietly cancel
    every style: a `final_stop: true` there put a full stop back on the end of
    Slack messages, which is exactly what the chat style exists to prevent. So
    false disables a pass everywhere, and true leaves the choice to the style.
    """
    base = STYLES.get(override or "", None) or APP_STYLE.get((app or "").lower(), PROSE)
    off = {k: False for k, v in (cfg or {}).items()
           if k != "name" and k in Style.__dataclass_fields__ and v is False}
    return replace(base, **off) if off else base


# -------------------------------------------------------------- spoken marks

# Internal only: they become a plain " the moment the writer sees them. A
# spoken "quote" toggles, but "open quote"/"unquote" must not - dictating only
# the closing one would otherwise open a quotation.
_QUOTE_OPEN = ""
_QUOTE_CLOSE = ""
_FLAG_DASH = ""

_MARKS: dict = {
    ("new", "paragraph"): "\n\n",
    ("next", "paragraph"): "\n\n",
    ("new", "line"): "\n",
    ("next", "line"): "\n",
    ("full", "stop"): ".",
    ("question", "mark"): "?",
    ("exclamation", "mark"): "!",
    ("exclamation", "point"): "!",
    ("semi", "colon"): ";",
    ("open", "bracket"): "(",
    ("open", "parenthesis"): "(",
    ("open", "paren"): "(",
    ("close", "bracket"): ")",
    ("close", "parenthesis"): ")",
    ("close", "paren"): ")",
    ("open", "quote"): _QUOTE_OPEN,
    ("close", "quote"): _QUOTE_CLOSE,
    ("em", "dash"): "—",
    ("dot", "dot", "dot"): "…",
    ("smiley", "face"): ":)",
    ("comma",): ",",
    ("period",): ".",
    ("colon",): ":",
    ("semicolon",): ";",
    ("unquote",): _QUOTE_CLOSE,
    ("quote",): '"',
    ("hyphen",): "-",
    ("dash",): "-",
    ("ellipsis",): "…",
    ("ampersand",): "&",
    ("asterisk",): "*",
}

# Single words above that are also ordinary English nouns, so they convert only
# when nothing around them suggests a noun phrase.
_AMBIGUOUS = {"period", "colon", "dash", "hyphen", "comma", "semicolon",
              "ellipsis", "asterisk", "unquote", "quote"}

# "the comma", "a dash", "his period", "two colons": a determiner or a number
# in front means the speaker is talking *about* the mark.
_DETERMINERS = {"the", "a", "an", "this", "that", "these", "those", "my",
                "your", "his", "her", "its", "their", "our", "each", "every",
                "any", "no", "one", "two", "three", "first", "second", "third",
                "last", "next", "same", "other", "another", "grace", "trial",
                "long", "short", "full", "rest", "time", "menstrual"}

# "period of", "dash to", "colon in": a preposition behind means the same.
_PREPOSITIONS = {"of", "for", "in", "on", "to", "with", "from", "between",
                 "after", "before", "during", "since", "until", "about",
                 "into", "over", "under", "and", "or", "was", "is", "are"}

_BULLET = {("bullet", "point"), ("next", "bullet"), ("new", "bullet"),
           ("next", "item"), ("new", "item")}
_NUMBERED = {("numbered", "list"), ("number", "list"), ("ordered", "list")}
_BULLETED = {("bulleted", "list"), ("bullet", "list"), ("bullet", "points")}

_LONGEST = max(len(k) for k in
               list(_MARKS) + list(_BULLET) + list(_NUMBERED) + list(_BULLETED))

# Punctuation that hugs the word before it; everything else takes a space.
_HUGS_LEFT = {",", ".", "?", "!", ";", ":", ")", "]", "}", "…", "%"}
_HUGS_RIGHT = {"(", "[", "{"}


def _bare(token: str) -> str:
    """The token's letters, lowercased: "comma," -> "comma"."""
    return re.sub(r"[^\w']", "", token).lower()


class _Writer:
    """Collects words and marks, then spaces them the way a typist would.

    An explicit item list rather than string concatenation, because spacing
    depends on both neighbours: a closing bracket takes no space before it, and
    none after it either when a comma follows.
    """

    def __init__(self) -> None:
        self.items: list = []      # (kind, text): word | left | right | break
        self._quote_open = False

    def word(self, text: str) -> None:
        if text:
            self.items.append(("word", text))

    def mark(self, mark: str) -> None:
        if mark in ("\n", "\n\n"):
            self.items.append(("break", mark))
        elif mark == _QUOTE_OPEN:
            self._quote_open = True
            self.items.append(("right", '"'))
        elif mark == _QUOTE_CLOSE:
            self._quote_open = False
            self.items.append(("left", '"'))
        elif mark == '"':          # a spoken "quote": whichever end is next
            self._quote_open = not self._quote_open
            self.items.append(("right" if self._quote_open else "left", '"'))
        elif mark == _FLAG_DASH:   # "dash m" in an editor -> "-m"
            self.items.append(("right", "-"))
        elif mark == "-":          # well-known, 3-4: no space on either side
            self.items.append(("tight", mark))
        elif mark in _HUGS_RIGHT:
            self.items.append(("right", mark))
        elif mark in _HUGS_LEFT:
            self.items.append(("left", mark))
        else:
            self.items.append(("word", mark))

    def bullet(self, marker: str) -> None:
        self.items.append(("break", "\n"))
        self.items.append(("word", marker))

    def render(self) -> str:
        out: list = []
        space_pending = False
        for kind, text in self.items:
            if kind == "break":
                while out and out[-1].isspace():
                    out.pop()
                out.append(text)
                space_pending = False
                continue
            if kind == "left":                 # hugs what came before
                while out and out[-1] == " ":
                    out.pop()
                out.append(text)
                space_pending = True
                continue
            if kind == "tight":                # hugs both neighbours
                while out and out[-1] == " ":
                    out.pop()
                out.append(text)
                space_pending = False
                continue
            if kind == "right":                # hugs what comes after
                if space_pending:
                    out.append(" ")
                out.append(text)
                space_pending = False
                continue
            if space_pending:
                out.append(" ")
            out.append(text)
            space_pending = True
        return "".join(out)


def _is_command(key: tuple, tokens: list, i: int, span: int) -> bool:
    """Was this said as a command, or is it a word in the sentence?

    Multi-word commands ("new paragraph", "question mark") stand on their own -
    nobody says them by accident. The single words need their neighbours read.
    """
    if len(key) > 1:
        return True
    word = key[0]
    if word not in _AMBIGUOUS:
        return True
    raw = _bare(tokens[i])
    if raw != word:                                   # "commas", "periods"
        return False
    before = _bare(tokens[i - 1]) if i else ""
    after = _bare(tokens[i + span]) if i + span < len(tokens) else ""
    if before in _DETERMINERS:
        return False
    if after in _PREPOSITIONS:
        return False
    return True


def spoken_marks(text: str, flag_dash: bool = False) -> str:
    """Turn spoken punctuation and list commands into real punctuation.

    Whisper writes commands down as words - it has no way to know a comma was
    meant rather than said. Dragon and Apple dictation users say them out of
    habit, and "new paragraph" is how anyone dictating more than a sentence
    breaks it up.

    Line breaks already in the text are kept. They are not decoration: the
    transcriber puts a blank line in where the speaker paused long enough to
    have started a new paragraph, and an earlier version of this function -
    which tokenised with a plain split() - silently flattened all of them.
    """
    if not text.strip():
        return text
    numbering = 0                  # 0 = bullets, >0 = the next number to write
    out: list = []
    for chunk in re.split(r"(\n+)", text):
        if not chunk or chunk.startswith("\n"):
            out.append(chunk)
            continue
        rendered, numbering = _marks_in_line(chunk, numbering, flag_dash)
        out.append(rendered)
    return "".join(out)


def _marks_in_line(text: str, numbering: int, flag_dash: bool) -> tuple:
    """One line's worth, carrying the list numbering in and back out."""
    tokens = text.split()
    out = _Writer()
    i = 0
    while i < len(tokens):
        for span in range(min(_LONGEST, len(tokens) - i), 0, -1):
            key = tuple(_bare(t) for t in tokens[i:i + span])
            if not all(key):
                continue
            if key in _NUMBERED or key in _BULLETED:
                numbering = 1 if key in _NUMBERED else 0
                break
            if key in _BULLET:
                out.bullet(f"{numbering}." if numbering else "-")
                if numbering:
                    numbering += 1
                break
            if key in _MARKS and _is_command(key, tokens, i, span):
                mark = _MARKS[key]
                if flag_dash and key in (("dash",), ("hyphen",)):
                    mark = _FLAG_DASH
                out.mark(mark)
                break
        else:
            out.word(tokens[i])
            i += 1
            continue
        i += span
    return out.render(), numbering


# ----------------------------------------------------------------- auto-edit

_SCRATCH = re.compile(
    r"\b(?:scratch|strike|delete|ignore|forget)\s+(?:that|this)\b[\s,.:;-]*",
    re.IGNORECASE)

# The Hinglish ones are how the same correction is actually said: "Monday
# matlab Tuesday", "5 nahi nahi 6". Both words are everyday discourse fillers
# too ("matlab kya hai"), which is safe only because of _same_kind below - the
# words on either side have to be the same sort of thing before anything moves.
_MEANT = re.compile(
    r"[\s,;.]*\b(?:i\s+mean(?:t)?|sorry|no\s+wait|wait\s+no|rather|correction"
    r"|matlab|nahi\s+nahi|nahin\s+nahin)\b"
    r"[\s,:-]+(?P<fix>[^.!?,\n]{1,40})", re.IGNORECASE)

_WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday", "friday",
             "saturday", "sunday"}
_MONTHS = {"january", "february", "march", "april", "may", "june", "july",
           "august", "september", "october", "november", "december"}
# The same idea in romanized Hindi: relative days and weekday names, in the
# spellings people actually type.
_DIN = {"aaj", "aj", "kal", "parso", "parson", "narso", "narson"}
_VAAR = {"somvar", "somwar", "mangalvar", "mangalwar", "budhvar", "budhwar",
         "guruvar", "guruwar", "brihaspativar", "shukravar", "shukrawar",
         "shanivar", "shaniwar", "ravivar", "raviwar", "itvaar", "itwar"}
_TIME = re.compile(r"^\d{1,2}(?::\d{2})?(?:am|pm)?$", re.IGNORECASE)


def _same_kind(old: str, new: str) -> bool:
    """Can `new` replace `old`, or is the speaker simply carrying on talking?

    This is the whole safety property of the pass. "Monday" -> "Tuesday" is a
    correction. "Monday" -> "obviously" is a sentence continuing, and "I mean,
    it's fine" is a discourse marker that must survive untouched. So
    replacement is restricted to a closed set of kinds where a correction is
    the only sensible reading.
    """
    old, new = old.strip().lower(), new.strip().lower()
    if not old or not new or old == new:
        return False
    for group in (_WEEKDAYS, _MONTHS, _DIN, _VAAR, _WEEKDAYS | _VAAR):
        if old in group and new in group:
            return True
    if old.replace(",", "").isdigit() and new.replace(",", "").isdigit():
        return True
    if _TIME.match(old.replace(" ", "")) and _TIME.match(new.replace(" ", "")):
        return True
    return False


def _drop_scratched(text: str) -> str:
    """Remove "scratch that" and the sentence it cancels.

    The cancelled sentence is the one that just ended, so the cut has to reach
    back past that sentence's own full stop to the end of the one before it.
    Stopping at the nearest full stop - the first version - deleted the marker
    and kept the sentence the speaker had just thrown away.
    """
    while True:
        m = _SCRATCH.search(text)
        if not m:
            return text
        before = text[:m.start()].rstrip()
        # "Actually, scratch that" and "no wait, scratch that" are the same
        # marker with a lead-in; the lead-in is not a sentence to keep.
        lead = re.search(r"(?:\b(?:actually|no|wait|oh|ok|okay|sorry|so)\b[\s,]*)+$",
                         before, re.IGNORECASE)
        if lead:
            before = before[:lead.start()].rstrip()
        body = before[:-1] if before[-1:] in ".!?" else before
        cut = max(body.rfind("."), body.rfind("!"), body.rfind("?"),
                  body.rfind("\n"))
        text = (text[:cut + 1] + " " + text[m.end():]).strip()
        text = re.sub(r"[ \t]{2,}", " ", text)


def _apply_meant(text: str) -> str:
    """Replace the word a "I mean ..." was correcting, when it is safe to."""
    m = _MEANT.search(text)
    if not m:
        return text
    replacement = m.group("fix").strip()
    before = text[:m.start()]
    words = before.split()
    if not words or not replacement:
        return text
    target = words[-1].strip(".,;:")
    if not _same_kind(target, replacement.split()[0].strip(".,;:")):
        return text
    keep = before[:before.rfind(words[-1])]
    return keep + replacement + text[m.end():]


def auto_edit(text: str) -> str:
    """Apply corrections the speaker made out loud.

    Two shapes, both conservative:

        "...that's fine. Scratch that. Let's meet Tuesday."
            -> the cancelled sentence goes, with the marker.

        "Let's meet Monday, I mean Tuesday."
            -> "Let's meet Tuesday." Only when the new word is the same kind of
               thing as the old one.
    """
    text = _drop_scratched(text)
    for _ in range(2):             # at most two corrections in one dictation
        fixed = _apply_meant(text)
        if fixed == text:
            break
        text = fixed
    return text


# ------------------------------------------------------------------ entities

_TLDS = "com|org|net|io|ai|co|edu|gov|dev|app|in|uk|me"

_EMAIL = re.compile(rf"\b([\w.\-]+)\s+at\s+([\w\-]+)\s+dot\s+({_TLDS})\b",
                    re.IGNORECASE)
_DOMAIN = re.compile(rf"\b([\w\-]{{2,}})\s+dot\s+({_TLDS})\b", re.IGNORECASE)
_PERCENT = re.compile(r"\b(\d+(?:\.\d+)?)\s+percent\b", re.IGNORECASE)
_MONEY = re.compile(r"\b(\d[\d,]*(?:\.\d+)?)\s+(rupees?|dollars?|euros?|pounds?)\b",
                    re.IGNORECASE)
_SYMBOL = {"rupee": "₹", "dollar": "$", "euro": "€", "pound": "£"}


def entities(text: str) -> str:
    """Write addresses, domains, percentages and money the way they are typed.

    Everything here needs a hard anchor - the literal word "dot", or a digit
    already in the text - so ordinary prose cannot trigger it. Whisper writes
    numbers as digits on its own, which is what makes the digit anchor work.
    """
    text = _EMAIL.sub(lambda m: f"{m.group(1)}@{m.group(2)}.{m.group(3).lower()}", text)
    text = _DOMAIN.sub(lambda m: f"{m.group(1)}.{m.group(2).lower()}", text)
    text = _PERCENT.sub(lambda m: f"{m.group(1)}%", text)
    text = _MONEY.sub(
        lambda m: _SYMBOL[m.group(2).lower().rstrip("s")] + m.group(1), text)
    return text


# ---------------------------------------------------------------------- tidy

_SPACE_BEFORE_MARK = re.compile(r"[ \t]+([,.;:!?%)\]}…])")
_AFTER_OPENER = re.compile(r"([(\[{])[ \t]+")
_SENTENCE_START = re.compile(r"(^|[.!?]\s+|\n\s*(?:[-*]\s+|\d+\.\s+)?)([a-z])")
_LONE_I = re.compile(r"\bi\b(?=[ \t]|['’][a-z]|$)")


def tidy(text: str, capitals: bool = True) -> str:
    """Spacing and capitals - the mechanical part.

    Capitalisation only reaches Latin letters, so Devanagari and every other
    Indic script passes through untouched; those scripts have no case.
    """
    text = _SPACE_BEFORE_MARK.sub(r"\1", text)
    text = _AFTER_OPENER.sub(r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    if capitals:
        text = _SENTENCE_START.sub(lambda m: m.group(1) + m.group(2).upper(), text)
        text = _LONE_I.sub("I", text)
    # A list item is a fragment, typed without a full stop. The speech model
    # hears each spoken item end and adds one: "- Fix the login bug."
    text = _LIST_ITEM_STOP.sub(r"\1", text)
    # The line that introduces a list ends in a colon, not a full stop.
    text = _LIST_LEAD_STOP.sub(r"\1:\n", text)
    return text.strip()


_LIST_ITEM_STOP = re.compile(r"(?m)^((?:[-*]|\d+\.)\s[^\n.!?]*[^\s.!?])\.[ \t]*$")
_LIST_LEAD_STOP = re.compile(r"(?m)^([^\n]*[^\s.:!?])\.[ \t]*\n(?=(?:[-*]|\d+\.)\s)")


_ALREADY_ENDED = re.compile(r"[.!?…:,)\"'\]]$")


def final_stop(text: str) -> str:
    """Close a sentence that ran out without one - if it is a sentence.

    Not for a one- or two-word answer ("yes", "tomorrow"), not for a list item,
    and not when it already ends in punctuation.
    """
    stripped = text.rstrip()
    if not stripped or _ALREADY_ENDED.search(stripped):
        return text
    last_line = stripped.rsplit("\n", 1)[-1].strip()
    if re.match(r"^(?:[-*]|\d+\.)\s", last_line):
        return text
    if len(stripped.split()) < 3:
        return text
    return stripped + "."


# -------------------------------------------------------------------- driver


# --------------------------------------------------------------- shortcuts


def shortcut(text: str, shortcuts: dict | None) -> str | None:
    """The expansion when the whole dictation is a shortcut's cue, else None.

    "my address" -> the full address, typed out. Only a dictation that is
    nothing but the cue expands: matching cues inside sentences would turn
    "I changed my address" into a street name, and the cost of saying the cue
    on its own is one press of the hotkey.
    """
    if not shortcuts or not text:
        return None
    said = " ".join(_bare(t) for t in text.split() if _bare(t))
    for cue, expansion in shortcuts.items():
        if said and said == " ".join(_bare(t) for t in str(cue).split() if _bare(t)):
            return str(expansion)
    return None


# ---------------------------------------------------------------- case words

_CASES = {("camel", "case"): "camel", ("snake", "case"): "snake",
          ("pascal", "case"): "pascal", ("kebab", "case"): "kebab",
          ("constant", "case"): "constant"}
_CASE_WORDS = 4          # "camel case user account id" - identifiers are short
# Words that end an identifier: what comes next in a line of code is an
# operator or a keyword, not more of the name.
_CASE_STOP = {"equals", "equal", "plus", "minus", "times", "is", "to", "in",
              "of", "and", "or", "not", "then", "with", "from", "for", "as",
              "at", "on", "if", "else", "return", "into", "by"}


def _identifier(words: list, how: str) -> str:
    low = [w for w in (re.sub(r"[^\w]", "", w).lower() for w in words) if w]
    if not low:
        return ""
    if how == "camel":
        return low[0] + "".join(w.capitalize() for w in low[1:])
    if how == "pascal":
        return "".join(w.capitalize() for w in low)
    if how == "kebab":
        return "-".join(low)
    if how == "constant":
        return "_".join(low).upper()
    return "_".join(low)


def case_words(text: str) -> str:
    """"camel case user name" -> userName, the way an identifier is typed.

    The identifier runs until punctuation, a line break, or four words -
    identifiers are short, and without a limit "snake case user id equals
    five" would swallow the whole line. Say "comma" to end one early.
    """
    lines = text.split("\n")
    for n, line in enumerate(lines):
        words = line.split(" ")
        out: list = []
        i = 0
        while i < len(words):
            key = (_bare(words[i]), _bare(words[i + 1]) if i + 1 < len(words) else "")
            before = _bare(words[i - 1]) if i else ""
            if key in _CASES and i + 2 < len(words) and before not in _DETERMINERS:
                taken: list = []
                j = i + 2
                while j < len(words) and len(taken) < _CASE_WORDS:
                    if taken and _bare(words[j]) in _CASE_STOP:
                        break
                    taken.append(words[j])
                    j += 1
                    if re.search(r"[,.;:!?]$", taken[-1]):
                        break
                tail = re.search(r"[,.;:!?]+$", taken[-1])
                out.append(_identifier(taken, _CASES[key]) + (tail.group(0) if tail else ""))
                i = j
                continue
            out.append(words[i])
            i += 1
        lines[n] = " ".join(out)
    return "\n".join(lines)


def finish(text: str, style: Style = PROSE, shortcuts: dict | None = None) -> str:
    """Run the passes this style asks for. The one entry point."""
    if not text or not text.strip() or style is VERBATIM or style.name == "verbatim":
        return text
    expansion = shortcut(text, shortcuts)
    if expansion is not None:
        return expansion                   # typed exactly as the user saved it
    if style.marks:
        text = spoken_marks(text, flag_dash=style.flag_dash)
    if style.identifiers:
        text = case_words(text)
    if style.auto_edit:
        text = auto_edit(text)
    if style.entities:
        text = entities(text)
    text = tidy(text, capitals=style.capitals)
    if style.final_stop:
        text = final_stop(text)
    return text
