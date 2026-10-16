"""A recognised line, turned into tokens and looked up."""

import pytest

from core.reading import build_card, read_line, render_sense
from core.lang.dict_store import Entry


@pytest.fixture(scope="session")
def _warm():
    read_line("好")  # pay the dictionary load once


def opened(token):
    """The card the window would actually show for a token."""
    return token.candidates[token.default].cards[0]


def test_the_panel_opens_on_the_word_segmentation_chose(_warm):
    # The bug inherited from the extension, whose EntryView hardcodes "longest match wins by
    # default". At position 0 the candidates are 研究生, 研究, 研 -- longest first -- but the DP
    # split the line as 研究 | 生命 | 起源, so opening on 研究生 would show "graduate student"
    # under a token that reads 研究.
    tokens = read_line("研究生命起源")
    assert [t.text for t in tokens] == ["研究", "生命", "起源"]

    first = tokens[0]
    assert [c.headword for c in first.candidates] == ["研究生", "研究", "研"]
    assert first.default == 1
    assert opened(first).headword == "研究"

    # Every other length is still one click away; only which tab is showing changed.
    assert len(first.candidates) == 3


def test_a_token_with_one_candidate_opens_on_it(_warm):
    (token,) = read_line("的")
    assert token.default == 0
    assert opened(token).headword == "的"


def test_unknown_characters_survive_as_tokens_with_no_candidates(_warm):
    tokens = read_line("好！")
    assert [t.text for t in tokens] == ["好", "！"]
    assert tokens[1].candidates == ()
    # default stays in range even when there is nothing to index into.
    assert tokens[1].default == 0


def test_a_traditional_line_reads_with_pinyin_and_senses(_warm):
    tokens = read_line("倖存的居民皆已收容完畢")
    assert [t.text for t in tokens] == ["倖存", "的", "居民", "皆", "已", "收容", "完畢"]

    card = opened(tokens[0])
    assert card.headword == "倖存"
    assert card.pinyin == "xìng cún"
    assert card.pinyin_numbered == "xing4 cun2"
    assert card.senses  # "to survive (a disaster)"


def test_the_whole_line_travels_as_the_sentence(_warm):
    line = "居民皆已"
    for token in read_line(line):
        for candidate in token.candidates:
            for card in candidate.cards:
                assert card.sentence == line


def test_both_scripts_are_carried_and_variants_flagged(_warm):
    (token,) = read_line("国")
    card = opened(token)
    assert card.simplified == "国"
    assert card.traditional == "國"
    assert card.has_variants

    (same,) = read_line("好")
    assert opened(same).has_variants is False


def test_senses_split_on_slashes():
    entry = Entry("好", "", "hao3", "good/well/proper")
    assert build_card("好", entry).senses == ("good", "well", "proper")


def test_bracketed_cross_references_get_diacritics_too():
    # CC-CEDICT writes cross-references as 打伞[da3 san3]; raw tone digits in the middle of a
    # definition read badly.
    assert render_sense("to hold an umbrella 打伞[da3 san3]") == "to hold an umbrella 打伞[dǎ sǎn]"


def test_brackets_that_are_not_pinyin_are_left_alone():
    assert render_sense("abbr. for 中国[Zhong1 guo2]") == "abbr. for 中国[Zhōng guó]"
    assert render_sense("see also [note 1]") == "see also [note 1]"
