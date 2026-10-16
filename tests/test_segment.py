"""Where the word boundaries go.

Ported from the extension's test/segment.test.mjs, which is worth keeping intact: several of
these cases are regressions from real bugs rather than invented examples, and the comments say
which. Two halves, as there -- a made-up dictionary pins the algorithm without depending on what
CC-CEDICT happens to contain, then the real shards run the sentence that prompted it.
"""

import pytest

from core.lang.dict_store import dictionary
from core.lang.segment import segment


def split(text: str, words: list[str]) -> list[str]:
    """Segment `text` knowing only `words`, and return the pieces as strings."""
    chars = list(text)
    known = set(words)
    lengths_at = [
        [
            length
            for length in range(1, len(chars) - start + 1)
            if "".join(chars[start : start + length]) in known
        ]
        for start in range(len(chars))
    ]
    return ["".join(chars[s.start : s.start + s.length]) for s in segment(len(chars), lengths_at)]


def test_a_line_of_two_words_is_split_between_them():
    # The reported bug: a lookup answered for 开始 and ignored everything after it, because it
    # only ever matched from position 0.
    assert split("开始阅读", ["开始", "阅读", "开", "始", "阅", "读"]) == ["开始", "阅读"]


def test_a_greedy_first_choice_does_not_strand_the_rest_of_the_line():
    # The case maximum matching gets wrong. 研究生 is a real word ("graduate student"), so greedy
    # takes it and leaves 命 stranded; the whole-line cost says otherwise.
    words = ["研究", "研究生", "生命", "起源", "生", "命"]
    result = split("研究生命起源", words)
    assert result == ["研究", "生命", "起源"]
    assert result != ["研究生", "命", "起源"], "this is the greedy answer"


def test_the_tie_is_broken_against_leaving_single_characters_alone():
    # Both readings above are three tokens, so counting alone cannot separate them. What decides
    # it is that the greedy one orphans a character -- which is the SINGLE penalty's whole job.
    words = ["研究", "研究生", "生命", "起源", "生", "命"]
    assert split("研究生命起源", words) == ["研究", "生命", "起源"]


def test_unknown_characters_become_their_own_token():
    # Punctuation, latin, and whatever OCR invents. They must not drag a neighbour into a worse
    # split, and they must not make the line unsegmentable.
    assert split("开始!阅读", ["开始", "阅读"]) == ["开始", "!", "阅读"]
    assert split("???", []) == ["?", "?", "?"]


def test_a_longer_word_wins_a_tie_against_several_shorter_ones():
    assert split("中国菜", ["中国菜", "中国", "菜", "中"]) == ["中国菜"]


def test_an_empty_line_segments_to_nothing_rather_than_throwing():
    assert split("", ["开始"]) == []
    assert segment(0, []) == []


def test_tokens_are_contiguous_and_cover_the_whole_line():
    # Whatever it decides, it may not drop or duplicate a character -- the tokens are what the
    # window renders as the recognised line, and a gap there would misreport what was read.
    text = "我喜欢吃中国菜开始阅读"
    pieces = split(text, ["我", "喜欢", "吃", "中国菜", "中国", "开始", "阅读", "菜"])
    assert "".join(pieces) == text


# --- against the real dictionary ---------------------------------------------------------


@pytest.fixture(scope="session")
def cedict():
    return dictionary()


def reading_for(cedict, line: str):
    """The app's own segmentation path: match everywhere, then split."""
    matches = cedict.matches_by_position(line)
    spans = segment(len(line), [[m.length for m in at] for at in matches])
    return [(line[s.start : s.start + s.length], matches[s.start]) for s in spans]


def test_the_real_dictionary_splits_the_sentence_that_started_this(cedict):
    tokens = reading_for(cedict, "开始阅读")
    assert [text for text, _ in tokens] == ["开始", "阅读"]

    # Both words are looked up, not just the first -- which is the whole point.
    for text, candidates in tokens:
        assert candidates, f"{text} has no candidates"
        assert candidates[0].headword == text
        assert candidates[0].entries


def test_each_token_carries_the_other_lengths_at_its_position(cedict):
    # 中国菜 also matches 中国 and 中 at the same position. Keeping them is what lets the window
    # offer candidate tabs rather than making the user re-snip.
    text, candidates = reading_for(cedict, "中国菜")[0]
    headwords = [c.headword for c in candidates]

    assert text == "中国菜"
    assert "中国" in headwords, f"expected a shorter candidate, got {headwords}"
    # Longest first, the same order the popup's tabs use.
    assert headwords == sorted(headwords, key=len, reverse=True)
