"""Turns a dictionary entry into Anki field values.

A port of the extension's lib/anki-fields.js, and faithful to its central idea: nothing here
knows any particular field, note type or deck name. The caller supplies a mapping of
{field name -> token id}, and each token is a small pure function of a Card. That is what lets
the same code serve whatever collection it finds -- the shipped defaults merely pre-fill the
mapping, they are not assumed anywhere.

Token ids are the extension's, character for character, so a config can be copied between the
two without translation.

Two of the extension's tokens are absent, because nothing on this side can fill them: `source`
and `sourceUrl` describe the web page a word was hovered on, and a screen region has no URL. A
config naming either still loads -- an unrecognised token renders an empty field rather than
losing the note, which is the same thing that happens to settings written by a newer version.
"""

from collections.abc import Callable
from dataclasses import dataclass

from core.reading import Card

#: Anki card templates conventionally style .tone1-.tone5; anything else has no rule.
NEUTRAL_TONE_CLASS = "tone5"


def escape_html(text: str) -> str:
    """Anki fields are HTML, so anything derived from dictionary text has to be escaped."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def tone_class(tone: int) -> str:
    return f"tone{tone}" if 1 <= tone <= 5 else NEUTRAL_TONE_CLASS


def coloured_hanzi(card: Card, extras: dict) -> str:
    """One tone-coloured span per character.

    Tones are per *syllable* while the colouring is per *character*. They line up 1:1 for
    ordinary Chinese, but not for headwords holding digits or Latin (卡拉OK, AA制). Emitting
    plain text beats emitting confidently wrong colours, so a mismatch falls back.
    """
    chars = list(card.headword)
    if not card.syllables or len(chars) != len(card.syllables):
        return escape_html(card.headword)
    return "".join(
        f'<span class="{tone_class(syllable.tone)}">{escape_html(char)}</span>'
        for char, syllable in zip(chars, card.syllables)
    )


def coloured_pinyin(card: Card, extras: dict) -> str:
    """One tone-coloured span per syllable, with the toneless reading left in a comment."""
    if not card.syllables:
        return escape_html(card.pinyin)
    spans = " ".join(
        f'<span class="{tone_class(s.tone)}">{escape_html(s.text)}</span>' for s in card.syllables
    )
    # Matches the convention Chinese Support 3 writes, so notes look native alongside existing
    # ones.
    toneless = " ".join(part.rstrip("12345") for part in card.pinyin_numbered.split())
    return f"{spans} <!-- {escape_html(toneless)} -->" if toneless else spans


def sentence_with_word_bold(card: Card, extras: dict) -> str:
    """The line the word was read in, with that word emboldened.

    Matched on `as_read` rather than `headword`: the export can rewrite the headword to the other
    script, and 個 is not findable in a line that says 个.
    """
    sentence = escape_html(card.sentence)
    found = card.as_read or card.headword
    if not card.sentence or not found:
        return sentence
    word = escape_html(found)
    return sentence.replace(word, f"<b>{word}</b>", 1)


def japanese_furigana(card: Card, extras: dict) -> str:
    from core.anki.japanese import furigana
    return furigana(card.headword, card.reading)


@dataclass(frozen=True)
class Token:
    id: str
    label: str
    render: Callable[[Card, dict], str]


#: Every value a field can be bound to. `extras` carries anything that is not a property of the
#: card itself -- at present only a stored media filename.
TOKENS: tuple[Token, ...] = (
    Token("none", "(empty)", lambda c, x: ""),
    Token("headword", "Word", lambda c, x: escape_html(c.headword)),
    Token("reading", "Kana reading", lambda c, x: escape_html(c.reading)),
    Token("furigana", "Word with furigana", japanese_furigana),
    Token("simplified", "Simplified", lambda c, x: escape_html(c.simplified)),
    Token("traditional", "Traditional", lambda c, x: escape_html(c.traditional)),
    Token("colourHanzi", "Word, tone-coloured", coloured_hanzi),
    Token("pinyin", "Pinyin", lambda c, x: escape_html(c.pinyin)),
    Token("colourPinyin", "Pinyin, tone-coloured", coloured_pinyin),
    Token("pinyinNumbered", "Pinyin, numbered", lambda c, x: escape_html(c.pinyin_numbered)),
    Token("senses", "Definitions", lambda c, x: "<br>".join(escape_html(s) for s in c.senses)),
    Token(
        "sensesNumbered",
        "Definitions, numbered",
        lambda c, x: "<br>".join(f"{i}. {escape_html(s)}" for i, s in enumerate(c.senses, 1)),
    ),
    Token("firstSense", "First definition", lambda c, x: escape_html(c.senses[0]) if c.senses else ""),
    Token("sentence", "Line it was read in", lambda c, x: escape_html(c.sentence)),
    Token("sentenceBold", "Line, word emboldened", sentence_with_word_bold),
    # Only reference media after the exporter has stored it successfully.
    Token("audio", "Audio", lambda c, x: f"[sound:{x['audioFilename']}]" if x.get("audioFilename") else ""),
)

_BY_ID = {token.id: token for token in TOKENS}


def token_exists(token_id: str) -> bool:
    return token_id in _BY_ID


def build_fields(mapping: dict[str, str], card: Card, extras: dict | None = None) -> dict[str, str]:
    """Render a whole note.

    An unknown token id -- a config written by a newer version, or one naming a token only the
    extension has -- yields an empty field rather than raising and losing the whole note.
    """
    extras = extras or {}
    fields = {}
    for field, token_id in mapping.items():
        token = _BY_ID.get(token_id)
        fields[field] = token.render(card, extras) if token else ""
    return fields


def primary_field(mapping: dict[str, str]) -> str:
    """Which mapped field goes on the front of an auto-created note type.

    Prefers whichever field holds the word itself; falls back to the first field.
    """
    for wanted in ("headword", "colourHanzi", "simplified", "traditional"):
        for field, token_id in mapping.items():
            if token_id == wanted:
                return field
    return next(iter(mapping), "")
