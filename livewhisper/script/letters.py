"""Letter-by-letter romanization: the last resort, so native script never leaks.

The dictionary spells ~87% of words and the character model most of the rest,
but some words defeat both - the model's Sinhala spelled කරන්ට with a loop its
own guard rejected - and until now such a word was pasted in native script,
the one thing this app exists to prevent. This spells any letter it is given.
It is not pretty ("karant" rather than a native speaker's "karanta"), but it is
readable and the user can correct it, and a correction is learned like any
other.

Most Indic scripts in Unicode were laid out from the same national standard
(ISCII), so the same letter sits at the same offset in each block: क at U+0915,
ক at U+0995, க at U+0B95. One Devanagari table therefore covers Hindi, Marathi,
Bengali, Punjabi, Gujarati, Oriya, Tamil, Telugu, Kannada and Malayalam.
Sinhala and the Arabic script used for Urdu and Sindhi were not laid out that
way and get their own tables.
"""

from __future__ import annotations

import re
import unicodedata

# Blocks laid out parallel to Devanagari (U+0900).
_PARALLEL = [(0x0980, 0x09FF), (0x0A00, 0x0A7F), (0x0A80, 0x0AFF), (0x0B00, 0x0B7F),
             (0x0B80, 0x0BFF), (0x0C00, 0x0C7F), (0x0C80, 0x0CFF), (0x0D00, 0x0D7F)]

_DEVA_CONS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "ng", "च": "ch", "छ": "chh",
    "ज": "j", "झ": "jh", "ञ": "ny", "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh",
    "ण": "n", "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n", "ऩ": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r",
    "ऱ": "r", "ल": "l", "ळ": "l", "ऴ": "zh", "व": "v", "श": "sh", "ष": "sh",
    "स": "s", "ह": "h", "क़": "q", "ख़": "kh", "ग़": "gh", "ज़": "z", "ड़": "r",
    "ढ़": "rh", "फ़": "f", "य़": "y",
}
_DEVA_VOWELS = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ऋ": "ri",
    "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऍ": "e", "ऑ": "o", "ऎ": "e", "ऒ": "o",
}
_DEVA_SIGNS = {
    "ा": "a", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "ृ": "ri", "े": "e",
    "ै": "ai", "ो": "o", "ौ": "au", "ॅ": "e", "ॉ": "o", "ॆ": "e", "ॊ": "o",
    "ौ": "au",
}
_DEVA_MARKS = {"ं": "n", "ँ": "n", "ः": "h", "्": "", "़": "", "ऽ": ""}

_SINHALA_CONS = {
    "ක": "k", "ඛ": "kh", "ග": "g", "ඝ": "gh", "ඞ": "ng", "ඟ": "ng", "ච": "ch",
    "ඡ": "chh", "ජ": "j", "ඣ": "jh", "ඤ": "ny", "ඥ": "gn", "ඦ": "nj", "ට": "t",
    "ඨ": "th", "ඩ": "d", "ඪ": "dh", "ණ": "n", "ඬ": "nd", "ත": "th", "ථ": "th",
    "ද": "d", "ධ": "dh", "න": "n", "ඳ": "nd", "ප": "p", "ඵ": "ph", "බ": "b",
    "භ": "bh", "ම": "m", "ඹ": "mb", "ය": "y", "ර": "r", "ල": "l", "ව": "w",
    "ශ": "sh", "ෂ": "sh", "ස": "s", "හ": "h", "ළ": "l", "ෆ": "f",
}
_SINHALA_VOWELS = {
    "අ": "a", "ආ": "aa", "ඇ": "ae", "ඈ": "aae", "ඉ": "i", "ඊ": "ii", "උ": "u",
    "ඌ": "uu", "ඍ": "ru", "එ": "e", "ඒ": "ee", "ඓ": "ai", "ඔ": "o", "ඕ": "oo",
    "ඖ": "au",
}
_SINHALA_SIGNS = {
    "ා": "a", "ැ": "ae", "ෑ": "aae", "ි": "i", "ී": "ii", "ු": "u", "ූ": "uu",
    "ෘ": "ru", "ෙ": "e", "ේ": "ee", "ෛ": "ai", "ො": "o", "ෝ": "oo", "ෞ": "au",
}
_SINHALA_MARKS = {"ං": "ng", "ඃ": "h", "්": ""}

# Arabic script as used for Urdu and Sindhi. Short vowels are not written, so
# this spells consonants and long vowels only: readable, never elegant.
_ARABIC = {
    "ا": "a", "آ": "aa", "أ": "a", "ب": "b", "پ": "p", "ت": "t", "ٹ": "t",
    "ث": "s", "ج": "j", "چ": "ch", "ح": "h", "خ": "kh", "د": "d", "ڈ": "d",
    "ذ": "z", "ر": "r", "ڑ": "r", "ز": "z", "ژ": "zh", "س": "s", "ش": "sh",
    "ص": "s", "ض": "z", "ط": "t", "ظ": "z", "ع": "", "غ": "gh", "ف": "f",
    "ق": "q", "ک": "k", "ك": "k", "گ": "g", "ل": "l", "م": "m", "ن": "n",
    "ں": "n", "و": "o", "ؤ": "o", "ہ": "h", "ه": "h", "ۃ": "h", "ھ": "h",
    "ء": "", "ی": "i", "ي": "i", "ئ": "i", "ے": "e", "ۓ": "e",
    # Sindhi's extra letters
    "ٻ": "b", "ڀ": "bh", "ٺ": "th", "ٽ": "t", "ٿ": "th", "ڄ": "j", "ڃ": "ny",
    "ڇ": "chh", "ڊ": "d", "ڌ": "dh", "ڍ": "dh", "ڏ": "d", "ڙ": "r", "ڦ": "ph",
    "ڪ": "k", "ڳ": "g", "ڱ": "ng", "ڻ": "n", "ڙ": "r",
    "َ": "a", "ِ": "i", "ُ": "u", "ّ": "", "ْ": "", "ٰ": "a", "ٔ": "",
}


# A nukta turns a letter into the sound borrowed from Persian or English. NFC
# does not recombine these (they are composition exclusions), so they are read
# as pairs.
_NUKTA = {"फ": "f", "ज": "z", "क": "q", "ख": "kh", "ग": "gh", "ड": "r", "ढ": "rh"}

# Malayalam's chillus - consonants that end a word with no vowel - sit outside
# the parallel layout.
_CHILLU = {"ൺ": "n", "ൻ": "n", "ർ": "r", "ൽ": "l",
           "ൾ": "l", "ൿ": "k", "ൔ": "m"}


def _to_devanagari(ch: str) -> str:
    if ch in _CHILLU:
        return ch
    cp = ord(ch)
    for lo, hi in _PARALLEL:
        if lo <= cp <= hi:
            mapped = chr(cp - lo + 0x0900)
            # The parallel layout has holes (Tamil has no aspirates); anything
            # that lands outside a letter is dropped rather than guessed.
            return mapped if unicodedata.category(mapped) != "Cn" else ""
    return ch


def _brahmic(word: str, cons: dict, vowels: dict, signs: dict, marks: dict) -> str:
    out = []
    pending = False                     # a consonant still owes its inherent "a"
    chars = list(word)
    for i, ch in enumerate(chars):
        if ch in _CHILLU:
            if pending:
                out.append("a")
                pending = False
            out.append(_CHILLU[ch])
            continue
        if ch in _NUKTA and i + 1 < len(chars) and chars[i + 1] == "़":
            if pending:
                out.append("a")
            out.append(_NUKTA[ch])
            pending = True
            continue
        if ch in cons:
            if pending:
                out.append("a")
            out.append(cons[ch])
            pending = True
        elif ch in signs:
            out.append(signs[ch])
            pending = False
        elif ch in marks:
            if marks[ch] == "" and pending and ch in ("्", "්"):
                pending = False           # virama: no vowel after this consonant
            else:
                if pending:
                    out.append("a")
                    pending = False
                out.append(marks[ch])
        elif ch in vowels:
            if pending:
                out.append("a")
                pending = False
            out.append(vowels[ch])
        elif unicodedata.category(ch) in ("Mn", "Cf"):
            continue                      # nukta, ZWJ/ZWNJ: nothing to say
        else:
            if pending:
                out.append("a")
                pending = False
            out.append(ch if ch.isascii() else "")
    # A word-final consonant is said without its vowel in these languages
    # ("kar", not "kara"), so the owed "a" is dropped at the end.
    return "".join(out)


def spell(word: str) -> str:
    """Romanize any word, one letter at a time. Always returns Latin text."""
    if not word:
        return word
    if any(0x0D80 <= ord(c) <= 0x0DFF for c in word):
        return _brahmic(word, _SINHALA_CONS, _SINHALA_VOWELS, _SINHALA_SIGNS,
                        _SINHALA_MARKS)
    if any(0x0600 <= ord(c) <= 0x06FF or 0x0750 <= ord(c) <= 0x077F for c in word):
        return "".join(_ARABIC.get(c, c if c.isascii() else "") for c in word)
    deva = unicodedata.normalize("NFC", "".join(_to_devanagari(c) for c in word))
    return _brahmic(deva, _DEVA_CONS, _DEVA_VOWELS, _DEVA_SIGNS, _DEVA_MARKS)


_NATIVE = re.compile(r"[؀-ۿݐ-ݿऀ-෿‌‍]+")


def spell_text(text: str) -> str:
    """Replace every native-script run in `text` with its letter spelling."""
    return _NATIVE.sub(lambda m: spell(m.group(0)), text)
