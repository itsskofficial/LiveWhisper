"""Dakshina romanization lexicons: native word -> attested Latin spellings.

One lexicon per language, 30,000 words each, twelve languages. Loaded lazily
so a Hindi user never pays for the Tamil table.

Data from Google's Dakshina dataset (CC BY-SA 4.0). See data/LICENSE-DATA.md.

Measured coverage on real Whisper output: 92.3% of Devanagari tokens (exp2).
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

DATA = Path(__file__).resolve().parent.parent.parent / "data"

# Dakshina's lexicon is a 30k sample, so some extremely common forms are simply
# absent - जाऊंगा and खाऊंगा are missing while करूंगा and आऊंगा are present. The
# character model then over-generates on them (जाऊंगा -> "jaaungaanga").
#
# A curated table of high-frequency words costs nothing, never degenerates, and
# removes both observed failure modes: the very short words the model loops on,
# and the common inflections the sample happened to miss.
COMMON_WORDS = {
  "hi": {
    # future tense - the gap that showed up in testing
    "जाऊंगा": "jaunga", "जाऊंगी": "jaungi", "जाऊँगा": "jaunga",
    "खाऊंगा": "khaunga", "आऊंगा": "aaunga", "करूंगा": "karunga",
    "करूंगी": "karungi", "दूंगा": "dunga", "लूंगा": "lunga",
    "होऊंगा": "hounga", "देखूंगा": "dekhunga", "बताऊंगा": "bataunga",
    # frequent verbs
    "करना": "karna", "होना": "hona", "जाना": "jana", "आना": "aana",
    "देना": "dena", "लेना": "lena", "कहना": "kehna", "देखना": "dekhna",
    "मिलना": "milna", "रहना": "rehna", "बोलना": "bolna", "सुनना": "sunna",
    "समझना": "samajhna", "लगना": "lagna", "चलना": "chalna",
    "करता": "karta", "करती": "karti", "करते": "karte", "किया": "kiya",
    "गया": "gaya", "गयी": "gayi", "गए": "gaye", "हुआ": "hua", "हुई": "hui",
    "रहा": "raha", "रही": "rahi", "रहे": "rahe", "लगता": "lagta",
    "चाहिए": "chahiye", "सकता": "sakta", "सकते": "sakte", "सकती": "sakti",
    # question and discourse words
    "क्यों": "kyun", "क्यूं": "kyun", "कैसे": "kaise", "कब": "kab",
    "कहाँ": "kahan", "कितना": "kitna", "कौनसा": "kaunsa", "मतलब": "matlab",
    "लेकिन": "lekin", "अगर": "agar", "इसलिए": "isliye", "फिर": "phir",
    "अभी": "abhi", "बहुत": "bahut", "थोड़ा": "thoda", "सिर्फ": "sirf",
    "यार": "yaar", "भाई": "bhai", "अच्छा": "accha", "ठीक": "theek",
    "नहीं": "nahi", "हाँ": "haan", "क्या": "kya",
    # pronouns and particles - short, and the model loops on these
    "आ": "aa", "न": "na", "ना": "na", "ने": "ne", "को": "ko", "का": "ka",
    "की": "ki", "के": "ke", "से": "se", "में": "mein", "पर": "par",
    "है": "hai", "हैं": "hain", "था": "tha", "थी": "thi", "थे": "the",
    "हो": "ho", "ही": "hi", "भी": "bhi", "तो": "to", "जो": "jo", "वो": "vo",
    "ये": "ye", "यह": "yeh", "वह": "vah", "और": "aur", "या": "ya",
    "कि": "ki", "अब": "ab", "जब": "jab", "तब": "tab",
    "मैं": "main", "तू": "tu", "तुम": "tum", "आप": "aap", "हम": "hum",
    "मुझे": "mujhe", "तुझे": "tujhe", "उसे": "use", "इसे": "ise",
    "मेरा": "mera", "तेरा": "tera", "अपना": "apna", "उनका": "unka",
    "एक": "ek", "दो": "do", "कुछ": "kuch", "सब": "sab", "कोई": "koi",
    "कौन": "kaun", "कहाँ": "kahan",
  },
  # Other languages rely on the lexicon alone until a native speaker
  # contributes a list. See CONTRIBUTING.md - this is a good first issue.
}

# Kept for backwards compatibility with earlier imports.
SHORT_WORDS = {
    "आ": "aa", "न": "na", "ना": "na", "ने": "ne", "को": "ko", "का": "ka",
    "की": "ki", "के": "ke", "से": "se", "में": "mein", "पर": "par",
    "है": "hai", "हैं": "hain", "था": "tha", "थी": "thi", "थे": "the",
    "हो": "ho", "ही": "hi", "भी": "bhi", "तो": "to", "जो": "jo", "वो": "vo",
    "ये": "ye", "यह": "yeh", "वह": "vah", "और": "aur", "या": "ya",
    "कि": "ki", "अब": "ab", "कब": "kab", "जब": "jab", "तब": "tab",
    "मैं": "main", "तू": "tu", "तुम": "tum", "आप": "aap", "हम": "hum",
    "एक": "ek", "दो": "do", "क्या": "kya", "कौन": "kaun", "कहाँ": "kahan",
}


class Lexicon:
    """Word-level lookup with the user's per-word overrides layered on top."""

    def __init__(self, lang: str = "hi"):
        self.lang = lang
        self._entries: dict[str, list[str]] = {}
        self._counts: dict[str, int] = {}      # attestations, a commonness proxy
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        path = DATA / f"{self.lang}.lexicon.tsv"
        if not path.exists():
            log.warning("lexicon missing: %s - falling back to model only", path)
            self._loaded = True
            return
        n = 0
        with open(path, encoding="utf-8") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 2:
                    continue
                # each field after the word is "spelling:attestations"
                forms, total = [], 0
                for field in parts[1:]:
                    if not field:
                        continue
                    spelling, _, count = field.rpartition(":")
                    if not spelling:            # no colon - treat as bare form
                        spelling, count = field, "1"
                    forms.append(spelling)
                    total += int(count) if count.isdigit() else 1
                if forms:
                    self._entries[parts[0]] = forms
                    self._counts[parts[0]] = total
                    n += 1
        self._loaded = True
        log.info("loaded %s lexicon: %d words", self.lang, n)

    def lookup(self, word: str) -> str | None:
        """Most-attested spelling, or None if unknown."""
        curated = COMMON_WORDS.get(self.lang)
        if curated and word in curated:
            return curated[word]
        self.load()
        forms = self._entries.get(word)
        return forms[0] if forms else None

    def attestations(self, word: str) -> int:
        """How many people wrote this word at all - a rough frequency signal."""
        self.load()
        return self._counts.get(word, 0)

    def contested(self, limit: int = 40) -> list:
        """Common words people spell in more than one way.

        These are the only words worth asking about during setup: a word with
        one accepted spelling teaches us nothing, and an obscure word the user
        does not recognise makes the question unanswerable.
        """
        self.load()
        scored = [(self._counts.get(w, 0), w) for w, forms in self._entries.items()
                  if len(forms) > 1 and 2 <= len(w) <= 8]
        scored.sort(reverse=True)
        return [w for _n, w in scored[:limit]]

    def variants(self, word: str) -> list[str]:
        """All attested spellings - the surface the user's preference selects from."""
        self.load()
        return list(self._entries.get(word, []))

    def __len__(self) -> int:
        self.load()
        return len(self._entries)


@lru_cache(maxsize=16)
def get_lexicon(lang: str = "hi") -> Lexicon:
    lex = Lexicon(lang)
    lex.load()
    return lex
