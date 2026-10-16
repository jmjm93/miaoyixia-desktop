"""Pixels off the screen, frozen at the moment the user asked for them.

The Chrome extension screenshots the tab and *then* crops. It gets away with the order because a
web page holds still. This app is aimed at games and video, so the order is reversed and it
matters: the whole virtual desktop is grabbed first, and everything afterwards -- the dimmed
overlay, the drag, the crop -- reads from that one frozen frame.

Two things fall out of that, and both are the point:

  * the overlay cannot appear in its own capture, and
  * a video or a game does not move underneath a selection that has already been drawn.

The extension's snip.js has to swallow wheel and touchmove events to stop the page scrolling
mid-drag. Freezing removes the entire class of problem instead of defending against one case
of it.
"""

import hashlib
import threading
from dataclasses import dataclass

import mss
import numpy as np
from PIL import Image


@dataclass(frozen=True)
class Monitor:
    """One physical display, in virtual-desktop coordinates."""

    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def contains(self, x: int, y: int) -> bool:
        return self.x <= x < self.right and self.y <= y < self.bottom


@dataclass(frozen=True)
class Frame:
    """The whole virtual desktop at one instant, held as raw BGRA.

    Deliberately *not* a PIL image. Converting 4480x1440 to RGB costs ~34ms, and almost none of
    it is ever wanted: the overlay wants the raw buffer (Qt's RGB32 format is BGRA on
    little-endian, so it wraps these bytes with no copy at all) and OCR wants one small crop. So
    the conversion happens per-crop, on the few thousand pixels that matter.

    `origin` is where the top-left sits in virtual coordinates, and it is very often negative: a
    display placed left of the primary one starts at a negative x. Every rectangle this module
    accepts is in virtual coordinates, so nothing outside here has to know.
    """

    bgra: bytes
    width: int
    height: int
    origin: tuple[int, int]
    monitors: tuple[Monitor, ...]

    def covered(self, x: int, y: int) -> bool:
        """Whether a virtual point is on an actual display.

        Not every point in the bounding box is. With a 2560x1440 beside a 1920x1080 the desktop
        is 4480x1440, and the bottom 360 rows of the shorter display's column belong to no
        monitor at all. The overlay must not offer that dead zone as selectable, and a capture
        taken there would be undefined pixels rather than anything the user saw.
        """
        return any(m.contains(x, y) for m in self.monitors)

    def crop(self, rect: tuple[int, int, int, int]) -> Image.Image:
        """Cut a virtual-coordinate rectangle (x, y, w, h) out as an RGB image.

        This is where BGRA becomes RGB, on the crop alone.
        """
        x, y, width, height = rect
        left = x - self.origin[0]
        top = y - self.origin[1]
        # Clamped rather than trusted: a drag can finish outside the frame if a display is
        # unplugged mid-selection, and the reshape below would otherwise index out of bounds.
        left = max(0, min(left, self.width - 1))
        top = max(0, min(top, self.height - 1))
        right = max(left + 1, min(left + width, self.width))
        bottom = max(top + 1, min(top + height, self.height))

        whole = np.frombuffer(self.bgra, dtype=np.uint8).reshape(self.height, self.width, 4)
        # Drop alpha, then reverse BGR into RGB. Both are views; ascontiguousarray is the single
        # copy, and it copies only the crop.
        patch = whole[top:bottom, left:right, 2::-1]
        return Image.fromarray(np.ascontiguousarray(patch))


def _monitors(sct) -> tuple[Monitor, ...]:
    # mss puts the union rectangle at index 0 and the real displays after it.
    return tuple(
        Monitor(x=m["left"], y=m["top"], width=m["width"], height=m["height"])
        for m in sct.monitors[1:]
    )


# One MSS per thread, kept alive. Constructing it costs ~40ms -- it opens a device context -- and
# paying that on every hotkey press would be a third of the budget for nothing. Per thread rather
# than global because MSS holds a per-thread DC on Windows and is not safe to share.
#
# A plain dict keyed by thread id, and NOT threading.local(), which is what this was and which
# leaked the display out from under the app:
#
#   PySide6 runs a slot on a QThread by taking the GIL with PyGILState_Ensure and dropping it
#   again on the way out. For a thread Python did not create, the last PyGILState_Release
#   *destroys the thread state* -- and threading.local() data lives in the thread state, so it
#   goes with it. Every timer tick therefore saw an empty local, built a fresh MSS, and left the
#   previous one's three GDI objects behind: a device context, a memory DC and a bitmap.
#
#   Measured at exactly 3 GDI objects and ~290KB per tick, four ticks a second, against Windows'
#   hard ceiling of 10,000 GDI objects per process. Roughly fourteen minutes of watching to
#   exhaust it, at which point object creation starts failing inside Qt and the process dies of
#   an access violation with no Python frame. That is the crash, and the log shows the climb
#   arriving at exactly 10000.
#
#   None of this is visible from the thread's identity: threading.get_ident() is stable across
#   the teardown, because it is the OS thread that persists, not Python's state for it. A dict
#   keyed on that id therefore survives exactly where the thread-local does not.
_instances: dict[int, "mss.MSS"] = {}
_instances_lock = threading.Lock()


def _sct():
    key = threading.get_ident()
    with _instances_lock:
        instance = _instances.get(key)
        if instance is None:
            instance = _instances[key] = mss.MSS()
        return instance


def release_capture() -> None:
    """Close and forget this thread's capture handles.

    Worth calling when a thread stops grabbing for good. Not load-bearing -- the app's threads
    live as long as the app does, so there is one instance per thread and it is reused -- but a
    screen-capture handle is not something to leave open on the strength of that.
    """
    key = threading.get_ident()
    with _instances_lock:
        instance = _instances.pop(key, None)
    if instance is not None:
        instance.close()


def grab_region(rect: tuple[int, int, int, int]) -> Image.Image:
    """One rectangle of the screen, live, as RGB. For the pinned watcher.

    Measured at ~16.6ms whatever the size, which is exactly one frame at 60Hz -- and the larger
    grabs quantise to two and four frames. The cost is waiting for the compositor, not copying
    pixels, so a smaller watched region buys nothing below roughly a megapixel. At one tick per
    second that is under 2% of a core.

    If that ever needs beating, the answer is DXGI Desktop Duplication (the `dxcam` package),
    which is event-driven and returns nothing at all while the screen is static -- letting the OS
    do the change detection instead of polling and hashing.
    """
    x, y, width, height = rect
    shot = _sct().grab({"left": x, "top": y, "width": max(1, width), "height": max(1, height)})
    whole = np.frombuffer(shot.bgra, dtype=np.uint8).reshape(shot.height, shot.width, 4)
    return Image.fromarray(np.ascontiguousarray(whole[:, :, 2::-1]))


#: Edge strength, summed over both axes, above which a pixel counts as part of a glyph.
INK_EDGE_ABOVE = 40


def ink_mask(image: Image.Image, above: int = INK_EDGE_ABOVE) -> np.ndarray:
    """Where the hard edges are: a polarity-agnostic stand-in for "where the text is".

    An earlier version of this thresholded on *brightness*, which was wrong and only looked right
    because the first material tested was Genshin's white-on-translucent dialogue. Black text on a
    white manhua bubble is the opposite polarity, and a mid-tone UI can fall entirely on one side
    of a brightness threshold and never register at all.

    Contrast is the property text actually has in every case, whichever way round it runs. This
    costs about the same (~1ms on a 1400x160 region) and does not care about polarity.

    Returns the boolean mask rather than a hash, because equality is the wrong comparison -- see
    `mask_distance`.
    """
    grey = np.asarray(image.convert("L"), dtype=np.int16)
    dx = np.abs(np.diff(grey, axis=1, prepend=grey[:, :1]))
    dy = np.abs(np.diff(grey, axis=0, prepend=grey[:1, :]))
    return (dx + dy) > above


def mask_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Fraction of the mask that differs. 0.0 is identical.

    Deliberately a distance and not an equality test. Hashing a thresholded mask and comparing
    exactly is maximally brittle: every threshold has boundary pixels that flip on the faintest
    perturbation, so an exact hash reports "changed" for a background that merely dimmed.

    A word of caution recorded from the measurements, because it bounds what this can be used
    for. Across the fixtures, four candidate gates -- brightness mask, edge mask, 32x32 dHash and
    a binned edge profile -- were each scored on how far they move when only the background
    changes versus when the text does. All four OVERLAPPED: the background move was the larger in
    every case. That is not a tuning problem, it is arithmetic. Replacing one word touches a few
    percent of a region; a global lighting change touches every pixel of it.

    So this cannot answer "did the text change?". It answers only the easier question, "is this
    region provably untouched?", and it answers that perfectly -- a genuinely static screen scores
    0.0000. Use it to skip work, never to decide that something happened. What actually happened
    is settled by comparing the recognised text.
    """
    if a is None or b is None or a.shape != b.shape:
        return 1.0
    return float((a != b).mean())


def grab() -> Frame:
    """Freeze the entire virtual desktop.

    Measured on the target machine at 4480x1440, MSS warm. Converting the whole frame to RGB up
    front was the wrong instinct and the numbers say so:

        + shot.rgb (Python BGRA->RGB)      ~119ms
        + PIL "BGRX" raw decoder            ~85ms
        this, no full-frame conversion      ~68ms   (bare sct.grab alone is ~51ms)

    The crop that OCR actually reads then costs 0.2ms, so the conversion did not disappear -- it
    moved to the few thousand pixels that are wanted instead of all 6.4 million.
    """
    sct = _sct()
    union = sct.monitors[0]
    shot = sct.grab(union)
    return Frame(
        bgra=shot.bgra,
        width=shot.width,
        height=shot.height,
        origin=(union["left"], union["top"]),
        monitors=_monitors(sct),
    )
