"""Persian text normalisation for lexicon keys.

Two keys per term, per the Lucene/Elasticsearch `persian` analyzer plus the
correction it needs for short entity names:

  fold()   - token key:  ZWNJ -> space, then character folding
  squash() - entity key: ZWNJ and ALL whitespace removed

`سی تی اسکن`, `سی‌تی‌اسکن` and `سیتیاسکن` must all reach one lexicon entry, which
`fold()` alone does not achieve. Match on squash() first, fall back to fold().

Direction: we fold TOWARD the Persian forms (U+06CC yeh, U+06A9 keheh) rather than
Lucene's Persian->Arabic direction, so debug output stays readable to Persian
speaking staff. The direction is arbitrary; applying it identically to both sides
is what matters.

Measured need: the live service catalogue holds `سي تي اسکن` (Arabic yeh, 206
services) and `سی تی اسکن` (Persian yeh, 1 service) as two different groups for
what is one concept.
"""

import re
import unicodedata

ZWNJ = "‌"

_FOLD = {
    # yeh: Arabic yeh, alef maksura, yeh barree  ->  Farsi yeh
    "ي": "ی", "ى": "ی", "ے": "ی",
    # kaf -> keheh
    "ك": "ک",
    # heh variants and teh marbuta -> heh
    "ۀ": "ه", "ہ": "ه", "ۂ": "ه", "ة": "ه",
    # alef variants -> alef
    "أ": "ا", "إ": "ا", "آ": "ا",
    # waw with hamza
    "ؤ": "و",
    # punctuation
    "،": ",", "؛": ";", "؟": "?", "٫": ".", "٬": ",",
}

# tatweel, harakat, ZWJ, BOM, hamza above/below - dropped outright
_DROP = set("ـ‍﻿") | {chr(c) for c in range(0x064B, 0x0653)} | {"ٔ", "ٕ"}

_DIGITS = {}
for i in range(10):
    _DIGITS[chr(0x06F0 + i)] = str(i)   # Persian
    _DIGITS[chr(0x0660 + i)] = str(i)   # Arabic-Indic

_WS = re.compile(r"\s+")


def fold(text) -> str:
    """Token key: canonical, digit-folded, character-folded, ZWNJ as space."""
    if text is None:
        return ""
    s = unicodedata.normalize("NFC", str(text))
    out = []
    for ch in s:
        if ch in _DROP:
            continue
        if ch == ZWNJ:
            out.append(" ")
            continue
        out.append(_DIGITS.get(ch, _FOLD.get(ch, ch)))
    return _WS.sub(" ", "".join(out)).strip().casefold()


def squash(text) -> str:
    """Entity key: as fold(), with every space removed as well."""
    return _WS.sub("", fold(text))
