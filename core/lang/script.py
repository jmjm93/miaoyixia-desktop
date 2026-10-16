"""How much of a recognised line is actually Chinese.

The watcher needs this. It re-reads a pinned region whenever the pixels settle, and the only
thing standing between that and the transcript is an exact string comparison -- which answers
"is this different?" and not "is this Chinese?". So an English subtitle, a clock, or a panel the
whole-crop fallback guessed at all count as new text and all overwrite the reading.

The obvious gate, recognition confidence, is the wrong one and the fixtures say so. Real Chinese
scores 0.870 to 1.000 across all fourteen of them, but a genuine hand-lettered panel came back at
min score 0.31 -- score measures how sure the model is about glyphs it has already committed to,
not whether they were Chinese. Gating on it would discard exactly the hard, real material this
app exists for.

What separates the two cleanly is how much of the line is Han at all:

    14 benchmark fixtures      0.714 - 1.000
    a noisy real panel         0.538
    English, UI text, a clock  0.000

Nothing measured lands between 0.0 and 0.5, which is the whole reason a threshold can work here.
"""

#: Han ideographs, by codepoint rather than unicodedata.name: this runs on every watch tick, and
#: a range check is a comparison where a name lookup is a table search per character.
#:
#: CJK Unified Ideographs and its extensions, plus the compatibility block. Deliberately excludes
#: kana, Latin, digits and CJK *punctuation* -- 。, 、 and full-width quotes are the characters a
#: line of Chinese shares with a line of Japanese or with OCR noise, so counting them as evidence
#: of Chinese is counting the one thing that is not evidence.
_HAN_RANGES = (
    (0x3400, 0x4DBF),    # Extension A
    (0x4E00, 0x9FFF),    # CJK Unified Ideographs
    (0xF900, 0xFAFF),    # Compatibility Ideographs
    (0x20000, 0x2A6DF),  # Extension B
    (0x2A700, 0x2EBEF),  # Extensions C-F
)


def is_han(char: str) -> bool:
    code = ord(char)
    return any(low <= code <= high for low, high in _HAN_RANGES)


def han_count(text: str) -> int:
    return sum(1 for char in text if is_han(char))


def han_fraction(text: str) -> float:
    """Proportion of the line's non-space characters that are Han. 0.0 for an empty line.

    Whitespace is excluded rather than counted as non-Han because it is a layout artefact of the
    recogniser, not something it read -- see ppocr.tidy, which strips it for the same reason.
    """
    solid = [char for char in text if not char.isspace()]
    if not solid:
        return 0.0
    return sum(1 for char in solid if is_han(char)) / len(solid)


def is_kana(char: str) -> bool:
    code = ord(char)
    return (0x3041 <= code <= 0x3096 or 0x309D <= code <= 0x309F
            or 0x30A1 <= code <= 0x30FA or 0x30FC <= code <= 0x30FF
            or 0x31F0 <= code <= 0x31FF or 0xFF66 <= code <= 0xFF9D)


def language_fraction(text: str, language: str = "zh") -> float:
    if language == "zh":
        return han_fraction(text)
    if language != "ja":
        raise ValueError("language must be zh or ja")
    solid = [char for char in text if not char.isspace()]
    return sum(is_han(char) or is_kana(char) for char in solid) / len(solid) if solid else 0.0
