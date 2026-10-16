"""Numbered CC-CEDICT pinyin to diacritics."""

import pytest

from core.lang.pinyin import convert_syllable, to_diacritics


@pytest.mark.parametrize(
    "numbered, expected, tone",
    [
        ("ni3", "nǐ", 3),
        ("hao3", "hǎo", 3),
        ("ma1", "mā", 1),
        ("ma2", "má", 2),
        ("ma4", "mà", 4),
        ("ma5", "ma", 5),  # neutral: no mark, but the tone is still reported
        # 'a' and 'e' win outright, wherever they sit in the cluster.
        ("xiao3", "xiǎo", 3),
        ("jie3", "jiě", 3),
        # "ou" puts the mark on the o, not the last vowel.
        ("zhou1", "zhōu", 1),
        # Otherwise the last vowel takes it.
        ("gui4", "guì", 4),
        ("liu2", "liú", 2),
        # ü is written "u:" by CC-CEDICT and "v" by everyone else.
        ("nu:3", "nǚ", 3),
        ("lu:4", "lǜ", 4),
        ("nv3", "nǚ", 3),
        # Capitals keep their case.
        ("Bei3", "Běi", 3),
    ],
)
def test_syllables_take_the_mark_on_the_right_vowel(numbered, expected, tone):
    result = convert_syllable(numbered)
    assert result.text == expected
    assert result.tone == tone


def test_tokens_that_are_not_syllables_pass_through_untouched():
    # Middots, latin abbreviations and punctuation appear inside CC-CEDICT pinyin fields. They
    # must survive so the caller can style them neutrally rather than drop them.
    for token in ("·", "CD", "-"):
        result = convert_syllable(token)
        assert result.text == token
        assert result.tone == 0


def test_a_whole_string_keeps_its_syllable_boundaries():
    result = to_diacritics("ni3 hao3")
    assert result.text == "nǐ hǎo"
    assert [s.tone for s in result.syllables] == [3, 3]


def test_an_empty_string_is_not_an_error():
    result = to_diacritics("")
    assert result.text == ""
    assert result.syllables == ()
