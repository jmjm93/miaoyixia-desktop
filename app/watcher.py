"""Watch one pinned region and speak up when its text changes.

Most applications draw their text in the same place every time -- a game's dialogue box does not
move between lines. So instead of snipping the same rectangle over and over, pin it once and let
the region report its own changes.

The costs that shape it (see capture.grab_region and capture.ink_mask):

    grab a region              ~16.6ms   vsync-bound, near-constant whatever the size
    edge-mask + distance        ~1.0ms
    detection only            7-288ms    depending on region width
    full OCR of that region  150-691ms   the thing worth avoiding

The obvious design is a cheap fingerprint that fires when the text changes. That design does not
work, and it was worth measuring rather than assuming. Four candidate gates were scored on how
far they move under a background-only change versus a text-only change, and ALL FOUR overlapped
-- the background move was larger every time. Replacing one word alters a few percent of a
region; a lighting change alters all of it. No threshold separates those.

So the cheap gate is used only for what it can actually prove. On a genuinely static screen it
scores exactly 0.0, which is most of the time while someone is reading, and that skips the tick
for 18ms. Anything else falls through to recognition, and **the recognised text is the authority
on whether anything happened** -- an exact string comparison, which cannot be fooled by lighting.

The consequence is a cost that depends on the material rather than a fixed budget: a still screen
costs ~2% of a core, and a constantly-animating one costs whatever OCR costs at the chosen
cadence. MIN_OCR_GAP_MS bounds the bad case.
"""

import time

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from .capture import grab_region, ink_mask, mask_distance, release_capture

#: How often to look.
#:
#: Was one second, which turned out to be the whole latency problem: subtitles that changed every
#: second or two were missed entirely, and of the ~3.5s worst case roughly 3s was simply waiting
#: between ticks. A quiet tick costs 19ms measured (17ms capture, which is vsync-bound, plus 1-3ms
#: for the gate), so 250ms of interval spends about 8% of one core while nothing is happening --
#: a fair price for being four times as responsive.
DEFAULT_INTERVAL_MS = 250

# TWO thresholds, because there are two different questions and one number cannot answer both.
# Conflating them is what made the first version emit exactly once and then go silent forever.

#: "Is the region still moving?" -- deliberately tolerant.
#:
#: Real screens are never perfectly still. Traced against a live region for 12 ticks, ambient
#: jitter -- a blinking cursor, antialiasing, compositor dithering -- measured 0.006 to 0.014
#: every single tick, and never once fell below 0.0015. A threshold taken from a *static desktop*
#: (which really does score 0.0000) meant the region never counted as settled and recognition
#: never ran at all.
SETTLING_DISTANCE = 0.02

#: "Is this provably the identical image?" -- exact, and it has to be.
#:
#: Zero, not "small". The measurements are blunt about why: a text-only change moved the mask by
#: as little as 0.0030, which is *below* the settling threshold above. So any tolerant comparison
#: used to skip work would discard real new text. Exact equality of the mask cannot: if a glyph
#: changed anywhere, the mask changed somewhere, so distance 0.0 proves nothing happened.
IDENTICAL = 0.0

#: Consecutive settled ticks before reading.
#:
#: One, not two. This exists because game dialogue is often typed out character by character, and
#: a region sampled mid-animation holds half a sentence -- but each extra tick of confirmation is
#: a whole interval of latency, and subtitles do not type themselves out, they simply appear. One
#: quiet tick after motion is enough to tell a finished line from a moving one, and the cost of
#: occasionally being wrong is one wasted read that the text comparison discards anyway.
SETTLE_TICKS = 1

#: Read anyway if the region has not settled for this long.
#:
#: Liveness. A region over a permanently animating scene may never settle, and waiting forever for
#: quiet is exactly the failure this replaced. Being early costs one OCR whose result the text
#: comparison discards; being late means the feature does not work.
FORCE_AFTER_MS = 1200

#: Floor on how often OCR may run, however busy the region looks.
#:
#: Bounds the animated case, and has to clear the cost of a read or the requests pile up behind
#: each other. Measured: 152ms for a 278px-wide region, 444ms at 514px, 652ms at 1612px. 500ms
#: suits a typical subtitle band; a very wide region is slower than this floor and is then limited
#: by the recogniser rather than by the rule, which is the honest outcome.
MIN_OCR_GAP_MS = 500


class Watcher(QObject):
    """Lives on its own thread. Drive it with signals.

    Its own thread rather than the GUI's because a tick blocks for a frame of vsync, and a 17ms
    stutter once a second is visible. Not the recogniser's thread either: that one is busy for
    200ms at a time doing OCR, and the watcher would queue behind it and drift.
    """

    #: A settled, changed region. Carries the PIL image so the caller need not grab it again.
    caught = Signal(object)
    caught_session = Signal(int, object)
    #: Watching started or stopped, for the UI to reflect.
    state = Signal(bool)
    state_session = Signal(int, bool)

    def __init__(self):
        super().__init__()
        self._timer: QTimer | None = None
        self._region: tuple[int, int, int, int] | None = None
        #: Edge mask of the previous tick, to tell whether anything is moving.
        self._previous = None
        #: Edge mask as it stood when the region was last handed on for recognition.
        self._reported = None
        self._stable = 0
        self._last_ocr = 0.0
        self._session = 0

    @Slot(object, int, int)
    def start(self, region: tuple[int, int, int, int], interval_ms: int = DEFAULT_INTERVAL_MS,
              session: int = 0) -> None:
        # The timer is created here rather than in __init__ so it belongs to this thread. A QTimer
        # created on the GUI thread and started from another one never fires.
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._tick)

        self._region = region
        self._session = session
        self._previous = None
        self._stable = 0
        # The force timer runs from when watching began, not from the epoch. Otherwise the very
        # first tick is always "overdue" and reads a region that may still be animating -- and the
        # snip that pinned it has just been read anyway.
        self._last_ocr = time.monotonic() * 1000
        self._reported = None
        self._timer.start(max(200, interval_ms))
        self.state.emit(True)
        self.state_session.emit(self._session, True)

    @Slot()
    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
        self._region = None
        self._previous = None
        self._reported = None
        self._stable = 0
        # Runs on this thread, so it closes this thread's capture handles. Not holding a device
        # context open across a session that has stopped looking at the screen.
        release_capture()
        self.state.emit(False)
        self.state_session.emit(self._session, False)

    @property
    def watching(self) -> bool:
        return self._timer is not None and self._timer.isActive()

    def _tick(self) -> None:
        if self._region is None:
            return
        try:
            image = grab_region(self._region)
        except Exception:  # noqa: BLE001 - a display can be unplugged mid-watch
            self.stop()
            return

        now = time.monotonic() * 1000
        mask = ink_mask(image)
        moved = mask_distance(mask, self._previous)
        self._previous = mask

        if moved <= SETTLING_DISTANCE:
            self._stable += 1
        else:
            # Something is moving -- text, background, or both; the gate cannot tell which. Prefer
            # to wait rather than read a half-drawn line.
            self._stable = 0

        # ...but never wait indefinitely. A region over a permanently animating scene would
        # otherwise never be read at all, which is worse than reading it a beat early.
        overdue = now - self._last_ocr >= FORCE_AFTER_MS
        if self._stable < SETTLE_TICKS and not overdue:
            return

        # The one skip that is safe: bit-for-bit identical to what was last read, so no glyph
        # anywhere can have changed. Free on a genuinely static screen, which is the common case
        # while somebody is reading. See IDENTICAL for why a tolerant comparison here would
        # swallow real text instead of saving work.
        if self._reported is not None and mask_distance(mask, self._reported) <= IDENTICAL:
            return

        if now - self._last_ocr < MIN_OCR_GAP_MS:
            return

        self._last_ocr = now
        self._reported = mask
        self.caught.emit(image)
        self.caught_session.emit(self._session, image)


class WatcherThread(QObject):
    """Owns the watcher thread. Requests go out as signals, for the reason EngineThread does."""

    request_start = Signal(object, int, int)
    request_stop = Signal()

    def __init__(self):
        super().__init__()
        self.thread = QThread()
        self.thread.setObjectName("watcher")
        self.watcher = Watcher()
        self.watcher.moveToThread(self.thread)

        self.request_start.connect(self.watcher.start)
        self.request_stop.connect(self.watcher.stop)

        self.thread.start()

    def start(self, region: tuple[int, int, int, int], interval_ms: int = DEFAULT_INTERVAL_MS,
              session: int = 0) -> None:
        self.request_start.emit(region, interval_ms, session)

    def stop(self) -> None:
        self.request_stop.emit()

    def shutdown(self) -> None:
        self.request_stop.emit()
        self.thread.quit()
        self.thread.wait(3000)
