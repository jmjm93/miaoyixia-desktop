"""CC-CEDICT pinyin ("ni3 hao3", "lu:4") to diacritics ("nǐ hǎo", "lǜ").

A direct port of the extension's src/lib/pinyin.js. The tone number is kept alongside the marked
text rather than discarded: it drives tone colouring in the UI, and exported Anki cards want the
numbers.
"""

import re
from dataclasses import dataclass

TONE_MARKS = {
    "a": "āáǎàa",
    "e": "ēéěèe",
    "i": "īíǐìi",
    "o": "ōóǒòo",
    "u": "ūúǔùu",
    "ü": "ǖǘǚǜü",
}

_TONED = re.compile(r"^(.*?)([1-5])$")
_VOWELS = re.compile(r"[aeiouüAEIOUÜ]+")


@dataclass(frozen=True)
class Syllable:
    text: str
    tone: int  # 1-4 marked, 5 neutral, 0 for anything that is not a syllable


def tone_target(vowels: str) -> int:
    """Which vowel in a cluster carries the mark.

    Standard rule: 'a' or 'e' wins outright; in "ou" the 'o' takes it; otherwise the last vowel.
    """
    a = vowels.find("a")
    if a != -1:
        return a
    e = vowels.find("e")
    if e != -1:
        return e
    ou = vowels.find("ou")
    if ou != -1:
        return ou
    return len(vowels) - 1


def convert_syllable(syllable: str) -> Syllable:
    """One numbered syllable to diacritics."""
    # "u:" and "v" are both used for ü.
    normalised = syllable.replace("u:", "ü").replace("v", "ü").replace("V", "Ü")

    match = _TONED.match(normalised)
    if not match:
        # Middots, Latin abbreviations, punctuation: pass through so the caller can style them
        # neutrally rather than dropping them.
        return Syllable(normalised, 0)

    body, digit = match.group(1), int(match.group(2))
    if digit == 5:
        return Syllable(body, digit)

    vowels = _VOWELS.search(body)
    if not vowels:
        return Syllable(body, digit)

    offset = vowels.start() + tone_target(vowels.group(0).lower())
    vowel = body[offset]
    marks = TONE_MARKS.get(vowel.lower())
    if not marks:
        return Syllable(body, digit)

    marked = marks[digit - 1]
    cased = marked.upper() if vowel.isupper() else marked
    return Syllable(body[:offset] + cased + body[offset + 1 :], digit)


@dataclass(frozen=True)
class Pinyin:
    text: str
    syllables: tuple[Syllable, ...]


def to_diacritics(pinyin: str) -> Pinyin:
    """A whole numbered pinyin string."""
    syllables = tuple(convert_syllable(token) for token in pinyin.split() if token)
    return Pinyin(text=" ".join(s.text for s in syllables), syllables=syllables)
