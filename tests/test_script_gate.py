"""The gate that stops a watched region overwriting a good reading with non-Chinese.

The numbers here are measured, not chosen: core/lang/script.py records the distribution over the
benchmark fixtures, and these assert the two sides of the gap it found.
"""

from pathlib import Path

from core.config import DEFAULTS, WatchConfig, load
from core.lang.script import han_count, han_fraction, is_han

#: Real lines that must survive the gate. The last two are the hard cases and the reason the
#: threshold is not simply "mostly Han": both came off a hand-lettered panel that the recogniser
#: reported at min score 0.31, with OCR noise mixed into real text.
POSITIVES = [
    "倖存的居民皆已收容完畢",
    "研究生命起源",
    "中国菜",
    "的",
    '美工"们"版证人工代证表:',
    '美工"行T"代证(工T章]',
]

#: What a watched region says when there is nothing Chinese in it.
#:
#: The first three are not invented -- they are what the recogniser actually returned for the
#: three images in bench/negatives/, kept verbatim so this stays grounded in measured output
#: without the tests having to load the models. Run bench/gate.py to re-measure from the images.
NEGATIVES = [
    # manga-style-bw-no-text: no text at all, so the whole-crop fallback guessed a letter.
    "A",
    # noisy-image-no-text: nothing legible, which the empty check already stops.
    "",
    # random-UI-shot-with-some-nonhanzi-text: English and Japanese, at min score 0.995 -- higher
    # than nine of the fourteen real Chinese fixtures. The reason the gate cannot be confidence.
    "ThewomanwholosteverythingbecauseofColdplay'sk!sscamisstillunemployedにないtokuninai",
    "What are you doing here at this hour?",
    "File  Edit  View  Help",
    "12:45  85%  1080p",
    "   ",
    "!!!",
]


def _watch():
    return load(Path("no-such-config.json")).watch


def test_han_is_recognised_by_range_not_by_looking_chinese():
    assert is_han("中") and is_han("龍")
    # Kana and CJK punctuation are shared with Japanese, and full-width quotes with OCR noise.
    # Counting them as evidence of Chinese counts the one thing that is not evidence.
    for char in "。、「」ひらがなカタカナ":
        assert not is_han(char), char
    for char in "abcABC123!?":
        assert not is_han(char), char


def test_whitespace_does_not_dilute_the_measurement():
    """The recogniser's spaces are a layout artefact -- ppocr.tidy strips them for that reason."""
    assert han_fraction("中 国 菜") == 1.0
    assert han_count("中 国 菜") == 3


def test_an_empty_line_is_not_a_division_by_zero():
    assert han_fraction("") == 0.0
    assert han_fraction("   ") == 0.0


def test_every_real_line_survives_the_shipped_threshold():
    watch = _watch()
    for line in POSITIVES:
        assert watch.accepts(line), f"{line} ({han_fraction(line):.3f}) was rejected"


def test_nothing_without_chinese_in_it_gets_through():
    watch = _watch()
    for line in NEGATIVES:
        assert not watch.accepts(line), f"{line!r} ({han_fraction(line):.3f}) was accepted"


def test_the_threshold_sits_in_the_gap_rather_than_against_one_edge():
    """A threshold with no margin is a threshold that the next fixture moves.

    Asserted as a property of the shipped number so that lowering it towards the noise, or
    raising it towards the real lines, fails here rather than in use.
    """
    shipped = DEFAULTS["watch"]["min_han_fraction"]
    worst_real = min(han_fraction(line) for line in POSITIVES)
    best_noise = max(han_fraction(line) for line in NEGATIVES)

    assert best_noise < shipped < worst_real
    # Measured over bench/, the two sets are 0.714 and 0.000 with nothing in between, and the
    # shipped number sits within 0.02 of the middle of that. These bounds are deliberately looser
    # than the gap so that a new fixture narrowing it is what fails, not arithmetic.
    assert shipped - best_noise > 0.2, "too close to the noise"
    assert worst_real - shipped > 0.15, "too close to the real lines"


def test_a_stray_hanzi_in_a_line_of_english_is_not_a_chinese_line():
    """The case a bare "any Han at all" test gets wrong.

    OCR of a Latin interface does occasionally emit one Han glyph, and a count-based gate would
    let the whole line through on the strength of it.
    """
    line = "Press 口 to continue playing the game"
    assert han_count(line) == 1
    assert not _watch().accepts(line)


def test_kana_is_not_counted_as_chinese():
    """One of the negatives is a Japanese UI, and にない is not a reason to refresh.

    A looser "is it CJK" range check would have counted it. The three kana are only 4% of that
    line so it would have been rejected anyway, but on a shorter line it would not have been.
    """
    assert han_fraction("にないtokuninai") == 0.0
    assert not _watch().accepts("にない")


def test_the_gate_can_be_turned_off_entirely():
    """Zero restores the previous behaviour, for anyone reading a script this misjudges."""
    off = WatchConfig(min_han_fraction=0.0)
    for line in NEGATIVES + POSITIVES:
        assert off.accepts(line)


def test_the_threshold_is_configurable(tmp_path):
    import json

    path = tmp_path / "config.json"
    path.write_text(json.dumps({"watch": {"min_han_fraction": 0.9}}), encoding="utf-8")

    watch = load(path).watch
    assert watch.min_han_fraction == 0.9
    assert watch.accepts("倖存的居民皆已收容完畢")
    assert not watch.accepts('美工"们"版证人工代证表:')
    # Changing one section must not disturb the other.
    assert load(path).anki.deck == DEFAULTS["anki"]["deck"]
