"""Undo Whisper writing the right sounds in a sibling script.

large-v3, told the audio is Malayalam, correctly hears Malayalam - and writes it
in Telugu script:

    said      ഈ നഗരം രാജ്യത്തെ മറ്റ് നഗരങ്ങളിൽ ...
    written   ఇనగరం రాజుతే మట్టు నగరంగ్ళలునీన ...

Measured on 40 FLEURS recordings, 98% of its Malayalam output came out in the
wrong script. The sounds are largely right; the alphabet is wrong, so every
character counts as an error and the romanizer reaches for the wrong lexicon.

Unicode laid out the Brahmic scripts of India in parallel blocks, inherited from
ISCII, so the same letter sits at the same offset in each: TELUGU LETTER KA is
U+0C15 and MALAYALAM LETTER KA is U+0D15. Moving a character between blocks is
therefore a table-free transliteration - but only where both blocks actually
define that letter with the same role. Tamil, for one, has no aspirated
consonants. Every mapped character is checked by Unicode name, and anything
without a true twin is left exactly as it was.
"""

from __future__ import annotations

import unicodedata

# Start of each language's 128-codepoint block. Sinhala and the Arabic-script
# languages are not ISCII-aligned and are deliberately absent.
BLOCK = {
    "hi": 0x0900, "mr": 0x0900,
    "bn": 0x0980, "pa": 0x0A00, "gu": 0x0A80,
    "ta": 0x0B80, "te": 0x0C00, "kn": 0x0C80, "ml": 0x0D00,
}


def _role(ch: str) -> str | None:
    """'LETTER KA' from 'TELUGU LETTER KA' - what a character is, minus script."""
    name = unicodedata.name(ch, "")
    parts = name.split(" ", 1)
    return parts[1] if len(parts) == 2 else None


def remap(text: str, source: str, target: str) -> str:
    """Move characters of `source`'s script into `target`'s, where twins exist."""
    if source not in BLOCK or target not in BLOCK or BLOCK[source] == BLOCK[target]:
        return text
    src, dst = BLOCK[source], BLOCK[target]
    out = []
    for ch in text:
        cp = ord(ch)
        if src <= cp < src + 0x80:
            twin = chr(cp - src + dst)
            role = _role(ch)
            if role and role == _role(twin):
                out.append(twin)
                continue
        out.append(ch)
    return "".join(out)


def untwinned(text: str, source: str, target: str) -> set:
    """Characters of `source` script in text that have no twin in `target`."""
    if source not in BLOCK or target not in BLOCK:
        return set()
    src = BLOCK[source]
    return {ch for ch in text
            if src <= ord(ch) < src + 0x80 and remap(ch, source, target) == ch}
