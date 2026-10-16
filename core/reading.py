"""A recognised line, turned into something the window can render.

Ports the extension's card.js (row -> card) and the `handleRead` half of its service worker
(line -> tokens -> candidates). The shape is deliberately a superset of what a flashcard needs --
both scripts, both pinyin forms, the sentence the word was read in -- so the Anki exporter is a
new consumer of existing data rather than a change to this path.
"""

import re
from dataclasses import dataclass, field, replace

from .lang.dict_store import Entry, Match, dictionary
from .lang.pinyin import Syllable, to_diacritics
from .lang.segment import segment

# Longer CC-CEDICT glosses cross-reference other words with their pinyin in brackets, e.g.
# 打伞[da3 san3]. Left alone that puts raw tone digits in the middle of a definition.
_BRACKETED = re.compile(r"\[([^\]]+)\]")
_PINYIN_TOKEN = re.compile(r"^[a-zA-ZüÜ:]+[1-5]?$")


def _looks_like_pinyin(text: str) -> bool:
    tokens = text.split()
    return (
        bool(tokens)
        and any(t[-1:].isdigit() and t[-1] in "12345" for t in tokens)
        and all(_PINYIN_TOKEN.match(t) for t in tokens)
    )


def render_sense(sense: str) -> str:
    """Give bracketed pinyin cross-references the same diacritics as a headword's."""
    return _BRACKETED.sub(
        lambda m: f"[{to_diacritics(m.group(1)).text}]" if _looks_like_pinyin(m.group(1)) else m.group(0),
        sense,
    )


@dataclass(frozen=True)
class Card:
    headword: str  # the form actually read off the image
    simplified: str
    traditional: str
    has_variants: bool
    pinyin: str
    pinyin_numbered: str
    syllables: tuple[Syllable, ...]
    senses: tuple[str, ...]
    sentence: str = ""
    #: The form as it came off the image, kept even when `headword` has been rewritten to the
    #: other script for export. Only the line's own wording can be found in the line itself, so
    #: this is what the example-sentence field emboldens on.
    as_read: str = ""
    language: str = "zh"
    reading: str = ""  # kana for Japanese; Chinese continues to use pinyin

    @property
    def pronunciation(self) -> str:
        return self.reading if self.language == "ja" else self.pinyin


def apply_script(card: Card, preference: str) -> Card:
    """The same card with its headword forced to one script, for export.

    Someone who studies simplified but reads Taiwanese material -- or the reverse -- otherwise
    ends up with a deck in two scripts depending on where each word was read. `as_read` is left
    alone, so the example sentence still bolds the form the screen actually showed.

    `preference` is 'as-read', 'simplified' or 'traditional'.
    """
    wanted = {"simplified": card.simplified, "traditional": card.traditional}.get(preference, "")
    # Tone colouring pairs each character with a syllable, and the two scripts are a per-character
    # mapping, so the pairing survives. A form that is missing or a different length would not,
    # and is left as it was rather than mangled.
    if not wanted or wanted == card.headword or len(wanted) != len(card.headword):
        return card
    return replace(card, headword=wanted)


def build_card(headword: str, entry: Entry, sentence: str = "", user_language: str = "en") -> Card:
    pinyin = to_diacritics(entry.pinyin)
    senses = [s for s in entry.gloss.split("/") if s]
    if user_language == "es":
        from .lang.spanish import gloss
        senses = gloss(entry) or senses
    return Card(
        headword=headword,
        as_read=headword,
        simplified=entry.simplified,
        traditional=entry.traditional,
        has_variants=entry.traditional != entry.simplified,
        pinyin=pinyin.text,
        pinyin_numbered=entry.pinyin,
        syllables=pinyin.syllables,
        # CC-CEDICT packs senses into one field separated by slashes.
        senses=tuple(render_sense(s) for s in senses),
        sentence=sentence,
    )


@dataclass(frozen=True)
class Candidate:
    headword: str
    length: int
    cards: tuple[Card, ...]


@dataclass(frozen=True)
class Token:
    text: str
    start: int
    length: int
    candidates: tuple[Candidate, ...] = field(default=())
    #: Which candidate the window should open on. See `_default_candidate`.
    default: int = 0


def _candidates(matches: list[Match], sentence: str, user_language="en") -> tuple[Candidate, ...]:
    return tuple(
        Candidate(
            headword=match.headword,
            length=match.length,
            cards=tuple(build_card(match.headword, entry, sentence, user_language) for entry in match.entries),
        )
        for match in matches
    )


def _default_candidate(candidates: tuple[Candidate, ...], length: int) -> int:
    """Which candidate tab to open on: the one segmentation actually chose.

    The extension opens on candidate 0 with the comment "longest match wins by default", which is
    right for *hovering* -- the cursor names a character and the longest word containing it is the
    best guess. It is wrong after a snip, because segmentation has already weighed the whole line
    and picked a length.

    Concretely, on 研究生命起源 the DP correctly splits 研究 | 生命 | 起源, but the candidates at
    position 0 are [研究生, 研究, 研], longest first -- so the panel would open on 研究生,
    "graduate student", for a token whose text reads 研究. The tabs still offer every length; only
    which one is showing changes.
    """
    for index, candidate in enumerate(candidates):
        if candidate.length == length:
            return index
    return 0


def read_line(line: str, language: str = "zh", user_language: str = "en") -> list[Token]:
    """Split a line into words and look each one up.

    Unlike a hover there is no cursor saying where a word begins, so the line is segmented first
    -- see lang/segment.py for why that is a shortest-path problem rather than greedy matching.

    Each token carries *every* match at its starting position, not just the one segmentation
    chose. That is what makes a wrong split recoverable: the window offers those as candidate
    tabs, so picking a different length is a click rather than a re-snip. It costs nothing extra,
    since the matches were already computed in order to segment.

    The whole line travels as the sentence on every card, so a note made from one word still
    records the context it was read in.
    """
    if language == "ja":
        from .lang.japanese import reader
        return reader().read(line, user_language)
    if language != "zh":
        raise ValueError("language must be zh or ja")
    chars = list(line)
    if not chars:
        return []

    cedict = dictionary()
    matches_at = cedict.matches_by_position(line)
    spans = segment(len(chars), [[m.length for m in at] for at in matches_at])

    tokens = []
    for span in spans:
        candidates = _candidates(matches_at[span.start], line, user_language)
        tokens.append(
            Token(
                text="".join(chars[span.start : span.start + span.length]),
                start=span.start,
                length=span.length,
                candidates=candidates,
                default=_default_candidate(candidates, span.length),
            )
        )
    return tokens
