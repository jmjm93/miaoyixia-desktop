"""The snip flow, exercised without a mouse.

These exist because of a real crash: `QRegion.rects()` was removed in Qt6, and the call sat
inside `paintEvent`, so the overlay took the process down the instant it was shown. Nothing in
the unit tests could see it -- it needed a widget to actually paint.

So the rule here is that every test paints or drives a widget for real. `grab()` runs the full
paintEvent synchronously and lets an exception in it surface as a test failure rather than as a
dead process.

Runs on Qt's offscreen platform, so there is no window and no display required.
"""

import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.capture import Frame, Monitor  # noqa: E402
from core import config as anki_config  # noqa: E402
from app.overlay import MIN_SIZE, Selection, SnipOverlay  # noqa: E402
from app.result import ResultWindow  # noqa: E402
from app.worker import Reading  # noqa: E402
from core.ocr.ppocr import PPOCR  # noqa: E402
from core.reading import read_line  # noqa: E402


@pytest.fixture(scope="session")
def qt():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def frame():
    """Two monitors of different heights, so there is a real dead zone to paint.

    Mirrors the development machine: 2560x1440 at the origin, 1920x1080 to its left. The bottom
    360 rows of the left column belong to no display.
    """
    width, height = 4480, 1440
    image = Image.new("RGB", (width, height), (40, 44, 52))
    ImageDraw.Draw(image).rectangle([2100, 300, 2600, 420], fill=(255, 255, 255))
    return Frame(
        bgra=image.convert("RGBA").tobytes("raw", "BGRA"),
        width=width,
        height=height,
        origin=(-1920, 0),
        monitors=(Monitor(0, 0, 2560, 1440), Monitor(-1920, 0, 1920, 1080)),
    )


def _press(widget, x, y, button=Qt.LeftButton):
    point = QPoint(x, y)
    widget.mousePressEvent(
        QMouseEvent(QMouseEvent.MouseButtonPress, point, button, button, Qt.NoModifier)
    )


def _move(widget, x, y):
    point = QPoint(x, y)
    widget.mouseMoveEvent(
        QMouseEvent(QMouseEvent.MouseMove, point, Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    )


def _release(widget, x, y):
    point = QPoint(x, y)
    widget.mouseReleaseEvent(
        QMouseEvent(QMouseEvent.MouseButtonRelease, point, Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
    )


def _settle(qt):
    """Let the overlay's result arrive.

    It is emitted from a zero-delay timer rather than from inside the event handler that ended
    the drag -- see SnipOverlay._finish, where emitting synchronously destroyed the widget
    underneath Qt's own dispatch. The deferral is the fix, so the tests wait for it.
    """
    qt.processEvents()


# --- the overlay ------------------------------------------------------------------------


def test_the_result_does_not_arrive_while_the_overlay_is_still_handling_the_event(qt, frame):
    """The crash this shape of code produced: an access violation in Qt, no Python frame.

    _finish runs part-way through Qt dispatching a mouse release to the overlay. Its receiver
    naturally lets go of the overlay -- App does `self.overlay = None` -- and with no other
    reference Python destroys the C++ widget on the spot, while QApplication::notify is still
    using it. Measured before the fix: destroyed() fired before mouseReleaseEvent returned.

    So the guarantee is about *ordering*, and that is what this asserts: nothing the receiver
    does can run before the event handler has finished with the widget.
    """
    overlay = SnipOverlay(frame)
    order = []
    overlay.chosen.connect(lambda s: order.append("receiver ran"))
    overlay.destroyed.connect(lambda *_: order.append("destroyed"))

    _press(overlay, 2000, 300)
    _move(overlay, 2300, 420)
    _release(overlay, 2300, 420)
    order.append("release returned")

    _settle(qt)
    assert order[0] == "release returned", f"the receiver ran mid-event: {order}"
    assert order[1] == "receiver ran"


def test_overlay_paints_with_a_dead_zone_present(qt, frame):
    """The regression. QRegion.rects() raised here and killed the process."""
    overlay = SnipOverlay(frame)
    assert overlay.grab().size().width() == frame.width


def test_overlay_paints_mid_drag(qt, frame):
    overlay = SnipOverlay(frame)
    _press(overlay, 100, 100)
    _move(overlay, 400, 260)
    # The selection branch of paintEvent draws four shade rectangles and the size readout, none
    # of which the idle branch touches.
    assert not overlay.grab().isNull()


def test_a_drag_reports_virtual_coordinates(qt, frame):
    overlay = SnipOverlay(frame)
    got = []
    overlay.chosen.connect(got.append)

    # Widget-local (2000, 300) on a frame whose origin is (-1920, 0) is virtual (80, 300).
    _press(overlay, 2000, 300)
    _move(overlay, 2300, 420)
    _release(overlay, 2300, 420)
    _settle(qt)

    assert got == [Selection(80, 300, 300, 120)]


def test_a_misclick_cancels_rather_than_snipping_a_sliver(qt, frame):
    overlay = SnipOverlay(frame)
    chosen, cancelled = [], []
    overlay.chosen.connect(chosen.append)
    overlay.cancelled.connect(lambda: cancelled.append(True))

    _press(overlay, 2000, 300)
    _release(overlay, 2000 + MIN_SIZE - 1, 300 + MIN_SIZE - 1)
    _settle(qt)

    assert not chosen
    assert cancelled


def test_a_selection_in_the_dead_zone_is_refused(qt, frame):
    """Below the shorter monitor there are no pixels, only whatever the framebuffer held."""
    overlay = SnipOverlay(frame)
    chosen, cancelled = [], []
    overlay.chosen.connect(chosen.append)
    overlay.cancelled.connect(lambda: cancelled.append(True))

    # Widget x 200 -> virtual -1720, y 1200 -> below the 1080-tall left monitor.
    _press(overlay, 200, 1200)
    _move(overlay, 500, 1350)
    _release(overlay, 500, 1350)
    _settle(qt)

    assert not chosen
    assert cancelled


def test_escape_cancels(qt, frame):
    from PySide6.QtGui import QKeyEvent

    overlay = SnipOverlay(frame)
    cancelled = []
    overlay.cancelled.connect(lambda: cancelled.append(True))
    overlay.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    _settle(qt)
    assert cancelled


def test_exactly_one_signal_however_it_ends(qt, frame):
    """The caller is promised one signal; several paths can reach _finish."""
    overlay = SnipOverlay(frame)
    events = []
    overlay.chosen.connect(lambda s: events.append("chosen"))
    overlay.cancelled.connect(lambda: events.append("cancelled"))

    _press(overlay, 2000, 300)
    _release(overlay, 2300, 420)
    overlay.keyPressEvent_called = True
    from PySide6.QtGui import QKeyEvent

    overlay.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    _settle(qt)

    assert events == ["chosen"]


# --- the result window ------------------------------------------------------------------


@pytest.fixture(scope="session")
def engine():
    return PPOCR()


def _reading(line: str, **kw) -> Reading:
    return Reading(
        line=line,
        tokens=read_line(line),
        orientation=kw.get("orientation", "horizontal"),
        undetected=kw.get("undetected", False),
        scores=kw.get("scores", ()),
        ocr_ms=kw.get("ocr_ms", 12.0),
        total_ms=kw.get("total_ms", 20.0),
    )


def test_a_region_with_no_chinese_reads_empty_and_does_not_throw(qt, engine, frame):
    """The case the user hit. A blank crop is a normal outcome, not a failure."""
    blank = frame.crop((-1900, 20, 300, 120))  # flat background, no text
    reading = engine.read(blank)
    assert reading.text == ""

    window = ResultWindow()
    window.show_capture(blank, (100, 100, 300, 120))
    window.show_reading(_reading(""))
    assert not window.grab().isNull()


def test_the_window_paints_a_real_reading(qt):
    window = ResultWindow()
    window.show_capture(Image.new("RGB", (300, 80), "white"), (10, 10, 300, 80))
    window.show_reading(_reading("倖存的居民皆已收容完畢", scores=(0.98, 0.99)))
    assert not window.grab().isNull()


def test_the_window_opens_on_the_segmented_word_not_the_longest(qt):
    window = ResultWindow()
    window.show_capture(Image.new("RGB", (300, 80), "white"), (10, 10, 300, 80))
    window.show_reading(_reading("研究生命起源"))
    token = window._tokens[0]
    assert token.text == "研究"
    assert token.candidates[token.default].headword == "研究"


def test_switching_words_and_candidates_repaints(qt):
    window = ResultWindow()
    window.show_capture(Image.new("RGB", (300, 80), "white"), (10, 10, 300, 80))
    window.show_reading(_reading("研究生命起源"))

    window.select_token(1)
    assert not window.grab().isNull()

    token = window._tokens[0]
    window.select_token(0)
    window._show_candidates(token, len(token.candidates) - 1)
    assert not window.grab().isNull()


def _chips(window):
    from PySide6.QtWidgets import QPushButton

    items = (window._chips.itemAt(i) for i in range(window._chips.count()))
    return [i.widget() for i in items if isinstance(i.widget(), QPushButton)]


def test_a_long_sentence_does_not_squeeze_its_chips_illegible(qt):
    """The reported symptom: on a long line the chips were too thin to read or to click.

    A row of chips in a window fixed at 460px is a demand a box layout cannot refuse -- it
    divides the shortfall among the children and ignores their minimum widths, because the
    parent has no room to give. Twenty-one chips came out 16px wide against a natural 54px, and
    12 of those pixels are padding and border, so nothing of the character survived.

    Asserted against each chip's own sizeHint rather than a pixel floor, because that is the
    actual claim: a chip is never narrower than the text inside it.
    """
    window = ResultWindow()
    window.show_capture(Image.new("RGB", (300, 80), "white"), (10, 10, 300, 80))
    window.show_reading(
        _reading("倖存的居民皆已收容完畢請所有人員立即前往指定的避難所並保持安靜等待進一步指示")
    )
    window.show()
    qt.processEvents()
    window.grab()

    chips = _chips(window)
    assert len(chips) > 10, "needs enough chips to overflow one row, or it proves nothing"
    thin = [c.text() for c in chips if c.width() < c.sizeHint().width()]
    assert not thin, f"squeezed below their own text: {thin}"

    rows = {c.y() for c in chips}
    assert len(rows) > 1, "they fit their text by wrapping; one row means they cannot have"


def test_a_snipped_paragraph_does_not_push_the_definitions_off_screen(qt):
    """Wrapping without a ceiling trades one bug for a worse one.

    The recogniser joins every text box in the region into a single line, so a box dragged over a
    manhua page -- which is what this is for -- segments into a hundred chips. Left to grow, the
    rows push the card past the height of the display, and _place pins an oversized window to the
    top: capture and line visible, definitions gone off the bottom. The chips scroll instead.
    """
    long_line = "倖存的居民皆已收容完畢請所有人員立即前往指定的避難所並保持安靜等待進一步指示" * 4

    window = ResultWindow()
    window.show_capture(Image.new("RGB", (300, 80), "white"), (10, 10, 300, 80))
    window.show_reading(_reading(long_line))
    window.show()
    qt.processEvents()
    window.adjustSize()
    tall = window.height()

    window.show_reading(_reading("中国菜"))
    qt.processEvents()
    window.adjustSize()
    short = window.height()

    assert len(_chips(window)) == 1
    # A ceiling, and one the short reading is well under -- a strip stuck at its tallest would
    # pass any bound on its own.
    assert tall - short < 200, f"{len(long_line)} characters grew the card by {tall - short}px"
    assert tall > short, "a longer line does take more than one row"


def _anki_window(qt, line="居民"):
    window = ResultWindow()
    window.set_anki_enabled(True, "Mandarin::Chinese Mining")
    window.show_capture(Image.new("RGB", (300, 80), "white"), (10, 10, 300, 80))
    window.show_reading(_reading(line))
    window.show()
    qt.processEvents()
    return window


def test_no_anki_button_exists_until_the_config_enables_one(qt):
    """A button that cannot work is worse than no button, and the default config is off."""
    window = ResultWindow()
    window.show_capture(Image.new("RGB", (300, 80), "white"), (10, 10, 300, 80))
    window.show_reading(_reading("居民"))
    qt.processEvents()

    assert window._anki_buttons == []
    assert not window.grab().isNull()


def test_one_add_button_per_reading_not_per_word(qt):
    """行 is xíng and háng: two notes, two buttons, and the choice is the user's."""
    window = _anki_window(qt, "银行")
    window.select_token(0)
    qt.processEvents()

    cards = window._anki_cards
    assert len(window._anki_buttons) == len(cards) >= 1
    assert not window.grab().isNull()


def test_asking_anki_happens_after_the_definitions_are_on_screen(qt):
    """The round trip is Anki's to be slow at; the window must not wait on it to render."""
    asked = []
    window = ResultWindow()
    window.set_anki_enabled(True, "Deck")
    window.anki_inspect.connect(lambda ticket, cards: asked.append((ticket, cards)))
    window.show_capture(Image.new("RGB", (300, 80), "white"), (10, 10, 300, 80))
    window.show_reading(_reading("居民"))
    qt.processEvents()

    assert asked, "nothing was asked of Anki"
    ticket, cards = asked[-1]
    assert ticket == window._anki_ticket
    assert len(cards) == len(window._anki_buttons)
    # Up, but not yet offering anything. Nothing has been asked of Anki, so "you may add this"
    # is not a claim the window is in a position to make -- and with Anki shut it would be
    # wrong for as long as the connection takes to give up.
    assert all(not button.isEnabled() for button in window._anki_buttons)
    assert all(b.property("state") == "checking" for b in window._anki_buttons)


def test_a_word_already_in_the_collection_opens_it_instead_of_adding_it_twice(qt):
    """Still not addable, but not a dead end either: the click goes to Anki's browser.

    "Already there" is the commonest thing this button has to say, and it is the only control in
    reach -- spending it on a refusal wastes the one gesture available.
    """
    window = _anki_window(qt)
    added, browsed = [], []
    window.anki_add.connect(lambda *a: added.append(a))
    window.anki_browse.connect(lambda *a: browsed.append(a))

    window.apply_anki_states(
        window._anki_ticket,
        {"ready": True, "states": [{"canAdd": False, "duplicate": True, "error": "duplicate"}]},
    )

    button = window._anki_buttons[0]
    assert button.property("state") == "duplicate"
    assert "Mandarin::Chinese Mining" in button.toolTip()

    button.click()
    qt.processEvents()
    assert not added, "a word already in the deck must never be added again"
    assert len(browsed) == 1
    assert browsed[0][2] is window._anki_cards[0]


def test_a_word_the_collection_lacks_becomes_addable_only_once_anki_says_so(qt):
    window = _anki_window(qt)
    assert window._anki_buttons[0].property("state") == "checking"

    window.apply_anki_states(
        window._anki_ticket,
        {"ready": True, "states": [{"canAdd": True, "duplicate": False, "error": ""}]},
    )

    button = window._anki_buttons[0]
    assert button.isEnabled()
    assert button.property("state") == "idle"


def test_a_reply_for_a_word_no_longer_on_screen_is_discarded(qt):
    """The bug this would otherwise be: click through three words faster than Anki answers, and
    the first word's "already in deck" greys out the third word's button.

    Words are clicked through in well under a round trip, so this is the normal case rather than
    a race worth calling unlikely.
    """
    window = _anki_window(qt, "研究生命起源")
    stale = window._anki_ticket

    window.select_token(1)  # a different word, and a new ticket
    qt.processEvents()
    assert window._anki_ticket != stale

    window.apply_anki_states(
        stale, {"ready": True, "states": [{"canAdd": False, "duplicate": True, "error": "dup"}]}
    )
    assert all(b.property("state") == "checking" for b in window._anki_buttons)

    window.anki_added(stale, 0, {"deck": "Deck", "created": []})
    assert all(b.property("state") == "checking" for b in window._anki_buttons)


def test_clicking_add_asks_once_and_says_so_while_it_waits(qt):
    window = _anki_window(qt)
    requests = []
    window.anki_add.connect(lambda t, i, card: requests.append((t, i, card)))

    button = window._anki_buttons[0]
    # Nothing before Anki has answered, however hard it is clicked.
    button.click()
    assert requests == []

    window.apply_anki_states(
        window._anki_ticket,
        {"ready": True, "states": [{"canAdd": True, "duplicate": False, "error": ""}]},
    )
    button.click()
    qt.processEvents()

    assert len(requests) == 1
    assert requests[0][2] is window._anki_cards[0]
    # Disabled while in flight, so an impatient second click cannot make two notes.
    assert not button.isEnabled()
    button.click()
    assert len(requests) == 1


def test_a_word_just_added_can_be_opened_too(qt):
    """The other half of ANKI_ACTIONABLE. Having just made the note is the likeliest moment to
    want to look at it -- to check the fields came out right."""
    window = _anki_window(qt)
    browsed = []
    window.anki_browse.connect(lambda *a: browsed.append(a))
    window.apply_anki_states(
        window._anki_ticket,
        {"ready": True, "states": [{"canAdd": True, "duplicate": False, "error": ""}]},
    )
    window.anki_added(window._anki_ticket, 0, {"deck": "Deck", "created": []})

    button = window._anki_buttons[0]
    assert button.property("state") == "added"
    button.click()
    qt.processEvents()
    assert len(browsed) == 1


def test_a_button_that_cannot_act_swallows_the_click(qt):
    """Every state that is an outcome rather than an offer: nothing may leave the window."""
    window = _anki_window(qt)
    sent = []
    window.anki_add.connect(lambda *a: sent.append("add"))
    window.anki_browse.connect(lambda *a: sent.append("browse"))

    for state in ("checking", "busy", "error"):
        window._set_anki_state(window._anki_buttons[0], state, "x", "")
        window._anki_buttons[0].click()
        # Directly too, since a disabled QPushButton never emits clicked() in the first place.
        window._anki_clicked(0)
        qt.processEvents()

    assert sent == [], f"a {state} button asked Anki for something"


def test_a_failed_add_shows_the_reason_and_a_duplicate_does_not(qt):
    """A duplicate is the expected way to fail -- the word is already studied, not broken."""
    window = _anki_window(qt)
    window.anki_failed(window._anki_ticket, 0, "cannot create note because it is a duplicate", True)
    assert window._anki_buttons[0].property("state") == "duplicate"

    window = _anki_window(qt)
    window.anki_failed(window._anki_ticket, 0, "collection is read-only", False)
    button = window._anki_buttons[0]
    assert button.property("state") == "error"
    assert button.toolTip() == "collection is read-only"


def test_added_note_displays_audio_failure(qt):
    window = _anki_window(qt)
    window.anki_added(window._anki_ticket, 0, {
        "deck": "Deck", "created": [], "audioError": "speech unavailable"
    })
    button = window._anki_buttons[0]
    assert "no audio" in button.text()
    assert "speech unavailable" in button.toolTip()
    assert button.property("state") == "added"


def test_anki_being_shut_does_not_look_like_a_failed_snip(qt):
    """The recognised text is perfectly good; only the export is unavailable.

    Routing this to the status line would read as though the capture had gone wrong, and the
    status line is where "nothing legible" lives.
    """
    window = _anki_window(qt)
    window.anki_unreachable(window._anki_ticket, "Cannot reach Anki at http://127.0.0.1:8765")

    assert all(not button.isEnabled() for button in window._anki_buttons)
    assert window._status.text() == ""
    assert not window.grab().isNull()


def test_a_second_reading_does_not_leave_the_previous_buttons_behind(qt):
    """_clear_layout reaches widgets and nothing else, so the headword row has to be one.

    Added as a layout it would answer None to item.widget(), survive every later render, and
    stack invisible buttons behind the visible one for as long as the window is open.
    """
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QPushButton

    window = _anki_window(qt)
    window.show_reading(_reading("中国菜"))
    # processEvents() alone will not do: Qt holds DeferredDelete back until the event loop that
    # posted it unwinds, so asking for it by name is the only way to see a destruction that has
    # really happened.
    qt.sendPostedEvents(None, QEvent.DeferredDelete)

    live = [b for b in window.findChildren(QPushButton) if b.objectName() == "anki"]
    assert len(live) == len(window._anki_buttons) == 1


def test_engine_results_arrive_on_the_gui_thread(qt):
    """The second crash, and the one worth a permanent guard.

    Qt picks a connection's type from the *receiver's* thread affinity. The App class was a plain
    Python object, so there was no affinity to inspect and PySide6 connected directly -- meaning
    `read_done` ran its handler on the recogniser thread, where it touched widgets and Windows
    answered with an access violation and no Python traceback.

    Nothing about that is visible in the source: the connect() line looks identical either way.
    So this asserts the property directly.
    """
    from PySide6.QtCore import QEventLoop, QObject, QThread, QTimer, Slot

    from app.worker import EngineThread

    main_thread = QThread.currentThread()

    loop = QEventLoop()

    class Receiver(QObject):
        """Stops the loop from inside the slot, deliberately.

        A bare `lambda: loop.quit()` connected to the same signal is not a QObject either, so it
        would be called directly on the worker thread and end the loop before the queued delivery
        to on_reading was ever processed -- failing this test for the very reason it is testing.
        """

        def __init__(self):
            super().__init__()
            self.thread_seen = None
            self.reading = None
            self.error = None

        @Slot(object)
        def on_reading(self, reading):
            self.thread_seen = QThread.currentThread()
            self.reading = reading
            loop.quit()

        @Slot(str)
        def on_failed(self, message):
            self.error = message
            loop.quit()

    engine = EngineThread()
    receiver = Receiver()
    engine.engine.read_done.connect(receiver.on_reading)
    engine.engine.failed.connect(receiver.on_failed)

    QTimer.singleShot(60_000, loop.quit)  # never hang the suite

    engine.read(Image.new("RGB", (120, 48), "white"), None)
    loop.exec()
    engine.stop()

    assert receiver.error is None, receiver.error

    assert receiver.reading is not None, "the engine never answered"
    assert receiver.thread_seen is main_thread, (
        "read_done was delivered on the worker thread; the receiver is not a QObject "
        "with main-thread affinity, so Qt connected it directly"
    )


def _ready_window(qt):
    window = ResultWindow()
    window.show_capture(Image.new("RGB", (300, 80), "white"), (10, 10, 300, 80))
    return window


def test_a_watched_region_accumulates_a_transcript(qt):
    """Subtitles go by. The previous line has to still be readable."""
    window = _ready_window(qt)
    window.show_reading(_reading("虽然偶而也是会失败"), append=False)
    window.show_reading(_reading("倖存的居民皆已收容完畢"), append=True)
    window.show_reading(_reading("中国菜"), append=True)

    assert window._log.toPlainText().splitlines() == [
        "虽然偶而也是会失败",
        "倖存的居民皆已收容完畢",
        "中国菜",
    ]


def test_a_snip_replaces_the_transcript(qt):
    """A fresh snip is a fresh context; the old text is not about it."""
    window = _ready_window(qt)
    window.show_reading(_reading("虽然偶而也是会失败"), append=True)
    window.show_reading(_reading("中国菜"), append=False)
    assert window._log.toPlainText() == "中国菜"


def test_the_same_line_twice_running_is_not_repeated(qt):
    """A region re-pinned mid-stream re-announces whatever is still on screen."""
    window = _ready_window(qt)
    window.show_reading(_reading("中国菜"), append=True)
    window.show_reading(_reading("中国菜"), append=True)
    assert window._log.toPlainText().splitlines() == ["中国菜"]


def test_the_definitions_describe_one_line_not_the_whole_log(qt):
    """The transcript grows; the lookup below it does not become a list of everything seen."""
    window = _ready_window(qt)
    window.show_reading(_reading("虽然偶而也是会失败"), append=True)
    window.show_reading(_reading("中国菜"), append=True)

    assert [t.text for t in window._tokens] == ["中国菜"]


def test_commit_looks_up_the_line_the_cursor_is_on(qt):
    """Clicking into an earlier line and pressing Enter revisits it."""
    from PySide6.QtGui import QTextCursor

    window = _ready_window(qt)
    window.show_reading(_reading("虽然偶而也是会失败"), append=True)
    window.show_reading(_reading("中国菜"), append=True)

    asked = []
    window.edited.connect(asked.append)

    cursor = window._log.textCursor()
    cursor.movePosition(QTextCursor.Start)
    window._log.setTextCursor(cursor)
    window._commit()
    assert asked == ["虽然偶而也是会失败"]

    window._log.moveCursor(QTextCursor.End)
    window._commit()
    assert asked[-1] == "中国菜"


def test_closing_is_distinct_from_hiding(qt):
    """Retry hides without ending a watch; the close button ends it."""
    window = _ready_window(qt)
    closes = []
    window.closed.connect(lambda: closes.append(True))

    window._retry()
    assert closes == [], "retry must not be read as 'done with this region'"

    window.dismiss()
    assert closes == [True]
    assert window.isHidden()


def _placed(window, rect):
    window._place(rect)
    return window.geometry()


def test_placement_does_not_depend_on_where_the_window_already_is(qt):
    """The third crash-class bug, and the one that made it a *stuck* state.

    _place used to read the screen from `screenAt(self.mapToGlobal(...))` -- the window's own
    position, which is an output of _place. That made it self-referential: once the window drifted
    onto the wrong monitor, every later snip was clamped into that monitor's bounds and re-wrote
    the same wrong position, so it never recovered. Measured before the fix: a snip at x=400 on
    the primary display placed the window at x=-473 on the secondary one.

    Placing the same snip twice from different starting positions must give the same answer.
    """
    window = ResultWindow()
    window.show_capture(Image.new("RGB", (300, 80), "white"), (10, 10, 300, 80))
    window.show_reading(_reading("虽然偶而也是会失败"))

    rect = (120, 200, 400, 100)
    first = _placed(window, rect)

    window.move(0, 0)
    assert _placed(window, rect) == first

    window.move(600, 400)
    assert _placed(window, rect) == first


def test_the_window_never_lands_off_screen(qt):
    """Whichever side of the snip it prefers, being wholly visible is not negotiable.

    The visible symptom of getting this wrong is specific and was reported as such: the card is
    ordered capture, line, chips, definitions -- so a window pushed off the top shows definitions
    with no recognised text above them.
    """
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QGuiApplication

    window = ResultWindow()
    window.show_capture(Image.new("RGB", (300, 80), "white"), (10, 10, 300, 80))
    window.show_reading(_reading("虽然偶而也是会失败"))

    for screen in QGuiApplication.screens():
        area = screen.availableGeometry()
        corners = [
            (area.left(), area.top(), 200, 60),
            (area.right() - 200, area.top(), 200, 60),
            (area.left(), area.bottom() - 60, 200, 60),
            (area.right() - 200, area.bottom() - 60, 200, 60),
            (area.center().x(), area.center().y(), 200, 60),
        ]
        for rect in corners:
            geometry = _placed(window, rect)
            centre = QPoint(rect[0] + rect[2] // 2, rect[1] + rect[3] // 2)
            expected = QGuiApplication.screenAt(centre) or QGuiApplication.primaryScreen()
            assert expected.availableGeometry().contains(geometry), (
                f"snip at {rect} put the window at {geometry}, outside {expected.name()}"
            )


def test_enabling_anki_shows_the_button_without_waiting_for_the_next_snip(qt):
    """config.json is watched, so this is reached with a reading already on screen.

    A switch you have just flipped that does nothing until you snip again reads as a switch that
    does nothing -- which is exactly how the feature looked the first time it was turned on.
    """
    window = ResultWindow()
    window.show_capture(Image.new("RGB", (300, 80), "white"), (10, 10, 300, 80))
    window.show_reading(_reading("研究生命起源"))
    qt.processEvents()
    assert window._anki_buttons == []

    window.select_token(1)
    window._show_candidates(window._tokens[1], len(window._tokens[1].candidates) - 1)
    chosen = window._candidate

    window.set_anki_enabled(True, "Mandarin::Chinese Mining")
    qt.processEvents()

    assert window._anki_buttons, "flipping it on left the window unchanged"
    # The tab is the user's choice, not the config's; a reload must not reset it.
    assert window._candidate == chosen
    assert not window.grab().isNull()

    window.set_anki_enabled(False, "")
    qt.processEvents()
    assert window._anki_buttons == []


def test_the_transcript_stops_growing_instead_of_growing_forever(qt):
    """A watched region appends for as long as it is watched.

    Left alone that is an evening of subtitles in one QPlainTextEdit, every line of which
    _fit_log re-lays-out on each new arrival. The ceiling drops the oldest rather than the
    newest: the newest is the one the definitions describe.
    """
    from app.result import TRANSCRIPT_MAX_LINES

    window = ResultWindow()
    window.show_capture(Image.new("RGB", (300, 80), "white"), (10, 10, 300, 80))
    for i in range(TRANSCRIPT_MAX_LINES + 120):
        window.append_line(f"line {i} 居民")

    lines = window._log.toPlainText().splitlines()
    assert len(lines) <= TRANSCRIPT_MAX_LINES
    assert lines[-1] == f"line {TRANSCRIPT_MAX_LINES + 119} 居民", "the newest line was dropped"
    assert "line 0 居民" not in window._log.toPlainText(), "the oldest line survived"


def test_a_health_sample_never_raises_and_says_when_it_cannot_measure():
    """It runs on a timer in a long-lived process. A diagnostic that can fault is a liability."""
    from app import health

    first = health.sample()
    assert first.threads >= 1
    assert first.objects > 0
    assert isinstance(first.line(), str)
    # Growth reads as a signed delta, which is the only form in which one line is informative.
    assert "objects" in health.growth(first, health.sample())


def test_the_windows_counters_are_actually_readable_not_silently_zero(qt):
    """GetCurrentProcess returns (HANDLE)-1, and ctypes defaults a return type to C int.

    Left undeclared the pseudo-handle is truncated on 64-bit, every call that receives it fails,
    and the module reports zeros that look exactly like a perfectly healthy process. That is the
    one failure worth a test, because nothing about it looks wrong.

    GDI is deliberately not asserted: these tests run on Qt's offscreen platform, which paints
    into memory and creates no GDI objects at all, so zero is correct here and only here. Checked
    against a real windowed process it reads in the dozens.
    """
    import sys

    from app import health

    if sys.platform != "win32":
        pytest.skip("win32 counters")

    window = ResultWindow()
    window.show_capture(Image.new("RGB", (300, 80), "white"), (10, 10, 300, 80))
    window.show()
    qt.processEvents()

    got = health.sample()
    assert got.available, "the win32 counters could not be read at all"
    assert got.rss_mb > 0, "a truncated process handle reports zero memory"
    assert got.handles > 0, "a truncated process handle reports zero handles"
    assert got.user > 0
    assert not got.gdi_alarming
    assert "rss" in got.line() and "gdi" in got.line()


def test_anki_replies_arrive_on_the_gui_thread(qt):
    """The same invariant test_engine_results_arrive_on_the_gui_thread guards, for the Anki thread.

    Anki replies land on widgets -- they grey out a button -- so a direct connection would touch
    them from the worker and Windows answers that with an access violation and no traceback.
    Nothing in the connect() line looks different when it is wrong, which is why this asserts the
    property rather than the wiring.
    """
    from PySide6.QtCore import QEventLoop, QObject, QThread, QTimer

    from app.anki import AnkiThread

    gui = QThread.currentThread()
    seen = {}

    class Receiver(QObject):
        """A QObject on the GUI thread holding a plain method, exactly like ResultWindow."""

        def on_inspected(self, ticket, result):
            seen["thread_is_gui"] = QThread.currentThread() is gui
            seen["result"] = result

    config = anki_config.load(Path("no-such-file.json")).anki

    anki = AnkiThread()
    receiver = Receiver()
    anki.anki.inspected.connect(receiver.on_inspected)
    # Answers from memory: the point is which thread the reply lands on, not whether Anki is
    # installed on whatever machine this runs on. The origin has to match the config's, or the
    # client cache decides it has gone stale and builds a real one that really opens a socket --
    # which passes on a developer's machine with Anki running and nowhere else.
    anki.anki._client = _FakeAnkiClient()
    anki.anki._origin = config.origin

    anki.inspect(7, config, [_card()])

    loop = QEventLoop()
    QTimer.singleShot(5000, loop.quit)
    poll = QTimer()
    poll.timeout.connect(lambda: seen and loop.quit())
    poll.start(20)
    loop.exec()
    anki.stop()

    assert seen, "the Anki thread never replied"
    assert seen["thread_is_gui"], "an Anki reply reached a widget on the worker thread"
    assert seen["result"]["ready"] is True


class _FakeAnkiClient:
    """Stands in for AnkiConnect, and asserts nothing was created by a mere inspect."""

    def deck_names(self):
        return ["Mandarin::Chinese Mining"]

    def model_names(self):
        return ["Chinese (Basic)"]

    def model_field_names(self, model):
        return ["Hanzi", "Color", "Pinyin", "English", "Sound"]

    def inspect(self, notes):
        return [{"canAdd": True, "duplicate": False, "error": ""} for _ in notes]


def _card():
    from core.lang.dict_store import Entry
    from core.reading import build_card

    return build_card("居民", Entry("居民", "居民", "ju1 min2", "resident"), "居民")


def test_one_capture_handle_per_thread_however_many_callbacks(qt):
    """The crash. It read as a memory leak and was a thread-state lifetime bug.

    PySide6 runs a slot on a QThread by taking the GIL with PyGILState_Ensure and dropping it on
    the way out, and for a thread Python did not create the last Release destroys the thread
    state. threading.local() lives in the thread state, so a cache kept there is empty again on
    the next callback -- and capture._sct() built a fresh MSS every timer tick, abandoning three
    GDI objects each time. Four ticks a second against Windows' 10,000 ceiling is about fourteen
    minutes of watching, after which Qt cannot create objects and the process dies of an access
    violation with no Python frame.

    Nothing about the thread's identity shows it: threading.get_ident() is stable across the
    teardown, because what persists is the OS thread and not Python's state for it. So the only
    honest assertion is on the count of instances built.
    """
    import mss
    from PySide6.QtCore import QEventLoop, QObject, QThread, QTimer, Signal, Slot

    from app import capture

    built = []
    real = mss.MSS

    def counting(*args, **kwargs):
        built.append(1)
        return real(*args, **kwargs)

    mss.MSS = counting
    try:
        class Ticker(QObject):
            done = Signal()

            @Slot()
            def go(self):
                self.n = 0
                self.timer = QTimer(self)
                self.timer.timeout.connect(self.tick)
                self.timer.start(10)

            def tick(self):
                self.n += 1
                capture._sct()          # one separate slot invocation per tick, as the watcher has
                if self.n >= 8:
                    self.timer.stop()
                    capture.release_capture()
                    self.done.emit()

        thread = QThread()
        ticker = Ticker()
        ticker.moveToThread(thread)
        finished = []
        ticker.done.connect(lambda: finished.append(True))
        thread.started.connect(ticker.go)
        thread.start()

        loop = QEventLoop()
        QTimer.singleShot(10000, loop.quit)
        poll = QTimer()
        poll.timeout.connect(lambda: finished and loop.quit())
        poll.start(20)
        loop.exec()
        thread.quit()
        thread.wait(3000)

        assert finished, "the worker thread never ticked"
        assert len(built) == 1, f"built {len(built)} capture handles across 8 callbacks"
    finally:
        mss.MSS = real


def test_the_app_is_a_qobject_so_its_slots_have_thread_affinity():
    """The invariant the previous test cannot check, because it supplies its own QObject.

    Everything that receives a signal from the recogniser thread must be a QObject living on the
    GUI thread, or Qt connects it directly and the handler runs on the worker -- touching widgets
    from the wrong thread. `App` receives four such signals (read_done, lookup_done, failed,
    warmed). Nothing in the connect() calls looks different when this is wrong; the only symptom
    is an access violation.
    """
    from PySide6.QtCore import QObject

    from app.main import App

    assert issubclass(App, QObject)


def test_a_second_snip_replaces_the_first(qt):
    """Widgets from the previous reading must be torn down, not stacked underneath."""
    window = ResultWindow()
    window.show_capture(Image.new("RGB", (300, 80), "white"), (10, 10, 300, 80))
    window.show_reading(_reading("研究生命起源"))
    first = window._chips.count()

    window.show_capture(Image.new("RGB", (300, 80), "white"), (10, 10, 300, 80))
    window.show_reading(_reading("中国菜"))
    qt.processEvents()  # deleteLater runs on the event loop

    assert window._chips.count() < first
    assert [t.text for t in window._tokens] == ["中国菜"]
