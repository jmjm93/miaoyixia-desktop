"""Drag a box over anything on screen.

A port of the extension's snip.js, and the reasoning there survives the move intact:

    This deliberately does *not* go looking for the text itself. [...] The user settles all of
    that in one drag. When the result comes back wrong they zoom the page in and drag again,
    which is a better answer than any heuristic we could write.

That was written to justify not guessing which DOM element held the art. It applies with more
force here, where the thing on screen might be a game, a video or a PDF and there is no document
to interrogate at all.

What the desktop changes:

  * The frame is already frozen (see capture.py), so this paints a still image rather than
    floating over live content. The extension had to swallow wheel and touchmove events to stop
    the page scrolling mid-drag; there is nothing left to scroll.
  * The overlay spans every monitor as one window, so a selection can be drawn on either screen.
  * Not every pixel of that span is real. Mismatched display heights leave a dead zone belonging
    to no monitor, and it is painted as void and refused as a selection.
"""

from dataclasses import dataclass

from app.region_area import RegionArea

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPen, QRegion
from PySide6.QtWidgets import QWidget

from .capture import Frame

def _point(event) -> QPoint:
    """Qt6 deprecates QMouseEvent.pos(); position() is the float-precision replacement."""
    return event.position().toPoint()


# Drags shorter than this in either direction are a mis-click, not a selection. Straight from
# snip.js, where it stops "a stray click while aiming" handing OCR a sliver of nothing.
MIN_SIZE = 8

# How far the un-selected screen is knocked back. Enough to make the selection obviously the
# subject, not so far that the user cannot see what they are aiming at -- they are framing text
# they have to be able to read.
DIM = 130

VOID = QColor(8, 10, 14)
MARCHING = QColor(255, 255, 255)
READOUT_BG = QColor(17, 22, 33, 235)
READOUT_FG = QColor(240, 243, 248)


@dataclass(frozen=True)
class Selection:
    """A chosen region, in virtual-desktop coordinates."""

    x: int
    y: int
    width: int
    height: int

    @property
    def rect(self) -> RegionArea:
        return RegionArea(self.x, self.y, self.width, self.height)


class SnipOverlay(QWidget):
    """Full-desktop selection surface over one frozen frame.

    Emits `chosen` with a Selection, or `cancelled`. Exactly one of the two, always -- the caller
    should not have to guard against a window that simply disappears.
    """

    chosen = Signal(Selection)
    cancelled = Signal()

    def __init__(self, frame: Frame):
        super().__init__(None)
        self._frame = frame
        self._origin: QPoint | None = None
        self._box = QRect()
        self._done = False

        # Qt.Tool keeps it out of the taskbar and the alt-tab list; a snip overlay is a mode, not
        # a window someone should be able to switch back to.
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.NoDropShadowWindowHint
        )
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)

        # The frozen pixels, wrapped rather than copied. mss hands back BGRA and Qt's RGB32 is
        # BGRA in memory on little-endian, so the buffer is already in the right layout. The
        # reference is held because QImage does not take ownership and would otherwise be reading
        # freed memory.
        self._buffer = frame.bgra
        self._shot = QImage(self._buffer, frame.width, frame.height, QImage.Format_RGB32)

        self.setGeometry(frame.origin[0], frame.origin[1], frame.width, frame.height)

    # --- geometry ---------------------------------------------------------------------

    def _to_virtual(self, point: QPoint) -> QPoint:
        return QPoint(point.x() + self._frame.origin[0], point.y() + self._frame.origin[1])

    def _clamped(self, point: QPoint) -> QPoint:
        return QPoint(
            max(0, min(point.x(), self._frame.width - 1)),
            max(0, min(point.y(), self._frame.height - 1)),
        )

    @staticmethod
    def _box_between(a: QPoint, b: QPoint) -> QRect:
        """The rectangle spanned by two points, sized by the distance between them.

        Explicitly *not* `QRect(a, b)`, which treats both corners as inclusive and so reports a
        300px drag as 301px wide. That one pixel is not cosmetic: it is the difference between the
        size readout matching the crop, and a 7px drag slipping past the MIN_SIZE mis-click floor
        as an 8px selection. snip.js gets this right by construction, using
        `Math.abs(a.x - b.x)` -- this is the same arithmetic.
        """
        return QRect(
            QPoint(min(a.x(), b.x()), min(a.y(), b.y())),
            QSize(abs(a.x() - b.x()), abs(a.y() - b.y())),
        )

    def _void_regions(self) -> list[QRect]:
        """Parts of the bounding box that belong to no monitor, in widget coordinates.

        Computed as whole-rectangle subtraction rather than per-pixel: the arrangement is a
        handful of rectangles, and `covered()` per pixel would be millions of calls per repaint.
        """
        ox, oy = self._frame.origin
        region = QRegion(QRect(0, 0, self._frame.width, self._frame.height))
        for monitor in self._frame.monitors:
            region -= QRegion(QRect(monitor.x - ox, monitor.y - oy, monitor.width, monitor.height))
        # Iterate, do NOT call region.rects(): that existed in Qt5 and was removed in Qt6, so it
        # raises AttributeError -- inside paintEvent, which takes the process down with it.
        return list(region)

    # --- painting ---------------------------------------------------------------------

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.drawImage(0, 0, self._shot)

        # Dim everything, then punch the selection back to full brightness. The extension does
        # this with one element and an enormous box-shadow; a painter can simply not paint there.
        shade = QColor(0, 0, 0, DIM)
        if self._box.isNull():
            painter.fillRect(self.rect(), shade)
        else:
            box = self._box
            painter.fillRect(QRect(0, 0, self.width(), box.top()), shade)
            painter.fillRect(QRect(0, box.bottom() + 1, self.width(), self.height() - box.bottom() - 1), shade)
            painter.fillRect(QRect(0, box.top(), box.left(), box.height()), shade)
            painter.fillRect(
                QRect(box.right() + 1, box.top(), self.width() - box.right() - 1, box.height()), shade
            )

        # Void areas are painted flat rather than dimmed: there are no pixels there, and showing
        # a dimmed copy of whatever the framebuffer happened to hold would imply otherwise.
        for void in self._void_regions():
            painter.fillRect(void, VOID)

        if not self._box.isNull():
            painter.setPen(QPen(MARCHING, 1))
            painter.drawRect(self._box.adjusted(0, 0, -1, -1))
            self._paint_readout(painter)

    def _paint_readout(self, painter: QPainter) -> None:
        """The live size, in the pixels OCR will actually receive.

        Kept from snip.js, which is explicit about why it is device pixels: showing a size that
        differs from what reaches the recogniser "would be actively misleading". Here the frame is
        captured at native resolution, so widget pixels are those pixels -- but the number is
        still the one that decides whether the text is big enough to read.
        """
        label = f"{self._box.width()} × {self._box.height()}"
        font = QFont(self.font())
        font.setPointSizeF(9.5)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)

        metrics = painter.fontMetrics()
        pad_x, pad_y = 8, 4
        width = metrics.horizontalAdvance(label) + pad_x * 2
        height = metrics.height() + pad_y * 2

        # Below the selection by preference, inside it when there is no room underneath -- the
        # same flip-when-tight rule the result window uses.
        x = self._box.left()
        y = self._box.bottom() + 6
        if y + height > self.height():
            y = max(0, self._box.top() - height - 6)
        x = max(0, min(x, self.width() - width))

        painter.setPen(Qt.NoPen)
        painter.setBrush(READOUT_BG)
        painter.drawRoundedRect(QRect(x, y, width, height), 4, 4)
        painter.setPen(QPen(READOUT_FG))
        painter.drawText(QRect(x, y, width, height), Qt.AlignCenter, label)

    # --- interaction ------------------------------------------------------------------

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() != Qt.LeftButton:
            # Right or middle click backs out, as in snip.js.
            return self._finish(None)
        self._origin = self._clamped(_point(event))
        self._box = self._box_between(self._origin, self._origin)
        self.update()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._origin is None:
            return
        self._box = self._box_between(self._origin, self._clamped(_point(event)))
        self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._origin is None:
            return
        self._box = self._box_between(self._origin, self._clamped(_point(event)))
        if self._box.width() < MIN_SIZE or self._box.height() < MIN_SIZE:
            return self._finish(None)

        virtual = self._to_virtual(self._box.topLeft())
        selection = Selection(virtual.x(), virtual.y(), self._box.width(), self._box.height())

        # A selection has to be on a real display. Anything else would hand OCR undefined pixels
        # from the gap between two differently-sized monitors.
        centre = (selection.x + selection.width // 2, selection.y + selection.height // 2)
        if not self._frame.covered(*centre):
            return self._finish(None)

        self._finish(selection)

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self._finish(None)

    def _finish(self, selection: Selection | None) -> None:
        # Guarded because several paths can reach it -- release, Escape, losing focus -- and the
        # caller is promised exactly one signal.
        if self._done:
            return
        self._done = True
        self.close()

        # Delivered on the next turn of the event loop, never from inside the event handler that
        # reached us. This is not tidiness, it is a use-after-free:
        #
        # _finish runs from mouseReleaseEvent or keyPressEvent, so Qt is part-way through
        # dispatching an event to this very widget. The receiver's natural response to "here is
        # your selection" is to let go of the overlay -- App does exactly that, `self.overlay =
        # None` -- and since nothing else holds a reference, Python destroys the C++ QWidget
        # there and then. Emitting synchronously therefore deletes the widget underneath
        # QApplication::notify, which carries on using it as the stack unwinds.
        #
        # Measured, not theorised: with a synchronous emit the destroyed() signal fires *before*
        # mouseReleaseEvent returns. The result is an access violation inside Qt with no Python
        # frame -- and an intermittent one, since it depends on the allocator having reused the
        # block, which is why it read as "crashes after a while".
        #
        # The lambda holds `self`, so the overlay outlives the event that ended it and is
        # destroyed from the timer instead, where nothing is above it on the stack.
        QTimer.singleShot(0, lambda: self._announce(selection))

    def _announce(self, selection: Selection | None) -> None:
        if selection is None:
            self.cancelled.emit()
        else:
            self.chosen.emit(selection)

    def start(self) -> None:
        """Show the overlay and take the keyboard."""
        self.show()
        self.raise_()
        self.activateWindow()
        # Without an explicit grab the overlay can open behind a fullscreen game and never see a
        # keystroke, leaving the user with a dimmed screen and no way out but the mouse.
        self.setFocus(Qt.OtherFocusReason)


def snip(frame: Frame, on_chosen, on_cancelled=None) -> SnipOverlay:
    """Convenience wrapper. Keep the returned widget alive until it emits."""
    overlay = SnipOverlay(frame)
    overlay.chosen.connect(on_chosen)
    if on_cancelled is not None:
        overlay.cancelled.connect(on_cancelled)
    overlay.start()
    return overlay


__all__ = ["MIN_SIZE", "Selection", "SnipOverlay", "snip", "QGuiApplication"]
