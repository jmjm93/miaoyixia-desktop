"""The pinned-region watcher, and the change gate underneath it.

The gate's contract is unusual and worth pinning down precisely, because getting it wrong is what
the measurements caught: it can prove a region UNCHANGED, and it cannot prove one CHANGED. Four
candidate gates were scored on how far they move under a background-only change versus a
text-only change and all four overlapped -- the background move was larger every time. So these
tests assert the one direction that holds, and the app settles the other by comparing text.
"""

import os

import numpy as np
import pytest
from PIL import Image, ImageDraw

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.region_area import RegionArea
from app import watcher as watcher_mod  # noqa: E402
from app.capture import ink_mask, mask_distance  # noqa: E402
from app.watcher import IDENTICAL, SETTLE_TICKS, SETTLING_DISTANCE, Watcher  # noqa: E402


@pytest.fixture(scope="session")
def qt():
    return QApplication.instance() or QApplication([])


def _text_image(fg, bg, offset=0):
    """A crude line of 'text': high-contrast bars on a flat ground."""
    img = Image.new("RGB", (400, 80), bg)
    draw = ImageDraw.Draw(img)
    for i in range(8):
        x = 20 + i * 45 + offset
        draw.rectangle([x, 20, x + 22, 60], fill=fg)
    return img


# --- the mask ---------------------------------------------------------------------------


def test_the_mask_is_polarity_agnostic():
    """The bug this replaced: an earlier gate thresholded on brightness.

    That only looked correct because the first material tested was white-on-dark game dialogue.
    Black text on a white manhua bubble is the opposite polarity and would have been masked
    inside-out. Contrast is the property text has either way round.
    """
    light_on_dark = ink_mask(_text_image((255, 255, 255), (20, 20, 24)))
    dark_on_light = ink_mask(_text_image((16, 16, 16), (250, 250, 250)))

    assert light_on_dark.sum() > 0
    assert dark_on_light.sum() > 0
    # Same glyph geometry, so the same edges, whichever way the contrast runs.
    assert mask_distance(light_on_dark, dark_on_light) < 0.02


def test_a_flat_region_has_no_ink():
    assert ink_mask(Image.new("RGB", (200, 60), (128, 128, 130))).sum() == 0


def test_distance_is_zero_for_an_identical_region():
    img = _text_image((255, 255, 255), (20, 20, 24))
    assert mask_distance(ink_mask(img), ink_mask(img.copy())) == 0.0


def test_distance_is_one_when_shapes_disagree():
    """A resized region must never compare as 'unchanged' by accident."""
    a = ink_mask(Image.new("RGB", (100, 40), "black"))
    b = ink_mask(Image.new("RGB", (120, 40), "black"))
    assert mask_distance(a, b) == 1.0
    assert mask_distance(a, None) == 1.0


# --- the watcher ------------------------------------------------------------------------


@pytest.fixture
def fake_screen(monkeypatch):
    """Replace the screen with something the test controls."""
    state = {"image": _text_image((255, 255, 255), (20, 20, 24))}
    monkeypatch.setattr(watcher_mod, "grab_region", lambda _rect: state["image"])
    # These tests tick synchronously, so no wall-clock time passes between ticks and the rate
    # limiter would block every read. Neutralised here so each test exercises the logic it names;
    # the one test that is actually about rate limiting sets it back explicitly.
    monkeypatch.setattr(watcher_mod, "MIN_OCR_GAP_MS", 0)
    return state


def _run(watcher, ticks):
    for _ in range(ticks):
        watcher._tick()


def test_a_static_region_reports_once_and_then_stays_quiet(qt, fake_screen):
    """The common case while someone is reading: nothing moves, nothing is re-read."""
    watcher = Watcher()
    caught = []
    watcher.caught.connect(caught.append)
    watcher.start(RegionArea(0, 0, 400, 80))

    _run(watcher, SETTLE_TICKS + 1)
    assert len(caught) == 1, "a settled region should be read exactly once"

    _run(watcher, 20)
    assert len(caught) == 1, "an unchanged region must not be re-read forever"


def test_new_text_is_reported(qt, fake_screen):
    watcher = Watcher()
    caught = []
    watcher.caught.connect(caught.append)
    watcher.start(RegionArea(0, 0, 400, 80))
    _run(watcher, SETTLE_TICKS + 1)
    assert len(caught) == 1

    fake_screen["image"] = _text_image((255, 255, 255), (20, 20, 24), offset=7)
    _run(watcher, SETTLE_TICKS + 1)
    assert len(caught) == 2, "moved lettering should be read again"


def test_a_region_that_never_settles_is_never_read(qt, fake_screen):
    """Dialogue typed out character by character must be read once, complete -- not per frame."""
    watcher = Watcher()
    caught = []
    watcher.caught.connect(caught.append)
    watcher.start(RegionArea(0, 0, 400, 80))

    for i in range(12):
        fake_screen["image"] = _text_image((255, 255, 255), (20, 20, 24), offset=i * 3)
        watcher._tick()

    assert caught == [], "a region still in motion must not be handed on"


def test_the_rate_limit_bounds_the_animated_case(qt, fake_screen, monkeypatch):
    """Over a constantly-changing region, OCR must not run on every single tick."""
    watcher = Watcher()
    caught = []
    watcher.caught.connect(caught.append)
    watcher.start(RegionArea(0, 0, 400, 80))

    monkeypatch.setattr(watcher_mod, "MIN_OCR_GAP_MS", 10_000)
    for i in range(6):
        # Settle on a different image each round, so novelty is never the limiting factor.
        fake_screen["image"] = _text_image((255, 255, 255), (20, 20, 24), offset=i * 9)
        _run(watcher, SETTLE_TICKS + 1)

    assert len(caught) <= 1, f"rate limit ignored: {len(caught)} reads"


def test_stopping_clears_state(qt, fake_screen):
    watcher = Watcher()
    caught = []
    watcher.caught.connect(caught.append)
    watcher.start(RegionArea(0, 0, 400, 80))
    _run(watcher, SETTLE_TICKS + 1)
    assert watcher.watching

    watcher.stop()
    assert not watcher.watching
    _run(watcher, 5)
    assert len(caught) == 1, "a stopped watcher must not keep reading"


def test_the_skip_test_is_exact_not_tolerant():
    """One changed pixel must NOT count as identical, and that asymmetry is deliberate.

    The measurements found a text-only change moving the mask by as little as 0.0030 -- below
    SETTLING_DISTANCE. So any tolerant comparison used to skip work would sometimes discard real
    new text. Exact equality never can: a changed glyph always changes the mask somewhere.
    """
    img = _text_image((255, 255, 255), (20, 20, 24))
    nudged = np.asarray(img).copy()
    nudged[0, 0] = (255, 255, 255)  # one stray bright pixel in the corner
    distance = mask_distance(ink_mask(img), ink_mask(Image.fromarray(nudged)))

    assert distance > IDENTICAL, "a changed pixel must not be treated as identical"
    # ...while still counting as "not moving", for the settling test. Two jobs, two thresholds.
    assert distance <= SETTLING_DISTANCE


def test_ambient_screen_jitter_still_counts_as_settled():
    """Why SETTLING_DISTANCE is 0.02 and not a hair above zero.

    Traced against a live screen region, ambient jitter -- blinking cursor, antialiasing,
    compositor dithering -- measured 0.006 to 0.014 on EVERY tick and never fell below 0.0015.
    With the old hair-above-zero threshold the region never settled, so it was read exactly once
    and then never again: the reported symptom was "just a single frame capture".
    """
    rng = np.random.default_rng(7)
    img = _text_image((255, 255, 255), (20, 20, 24))
    noisy = np.asarray(img).astype(np.int16)
    speckle = rng.random(noisy.shape[:2]) < 0.004
    noisy[speckle] = 255
    distance = mask_distance(ink_mask(img), ink_mask(Image.fromarray(np.clip(noisy, 0, 255).astype(np.uint8))))

    assert 0 < distance <= SETTLING_DISTANCE, f"jitter of {distance:.4f} would stall settling"
