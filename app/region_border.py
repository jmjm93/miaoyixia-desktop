"""A coloured frame drawn around a watched region, so it is never invisible.

A watcher that runs unseen is a bad deal: it costs CPU, it updates a window on its own initiative,
and the user has no way to remember which patch of screen it is looking at. Outlining the region
makes all three obvious at a glance.

The colour is the identity. The same one appears on the result window, so a reading can be traced
back to the rectangle that produced it without reading any labels -- which is what makes this
extend cleanly to several regions later, each with its own colour.

Two properties make it liveable over a game:

  * click-through, so it cannot intercept a mouse press meant for whatever is underneath, and
  * frame only, no fill, so it never obscures the text it surrounds.
"""

import random

from app.region_area import RegionArea

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


#: Thickness of the outline. Thin enough not to cover anything, thick enough to see over artwork.
BORDER_WIDTH = 3

#: How far outside the watched rectangle the frame sits, so it never covers the text itself.
BORDER_INSET = 2


class RegionBorder(QWidget):
    """An always-on-top outline around one screen rectangle."""

    def __init__(self, colour: str | None = None):
        super().__init__(None)
        if colour is not None:
            self._colour = QColor(colour)
        else: 
            self._colour = QColor(RegionBorder.random_colour())
        
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput  # click-through: mouse events pass to what is beneath
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        # Never take focus. Showing this must not pull a fullscreen game out of the foreground.
        self.setAttribute(Qt.WA_ShowWithoutActivating)

    @property
    def colour(self) -> QColor:
        return self._colour

    def set_region(self, rect: RegionArea) -> None:
        """Frame this rectangle, given in virtual-desktop coordinates."""
        x, y, width, height = rect.x, rect.y, rect.width, rect.height
        pad = BORDER_WIDTH + BORDER_INSET
        # The window is grown to sit *outside* the region, so the outline never covers the first
        # or last row of pixels the recogniser is going to read.
        self.setGeometry(x - pad, y - pad, width + pad * 2, height + pad * 2)
        self.update()

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        pen = QPen(self._colour, BORDER_WIDTH)
        pen.setJoinStyle(Qt.MiterJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        # Inset by half the pen width: Qt strokes centred on the path, so drawing on the exact
        # widget rect would clip the outer half of the line.
        half = BORDER_WIDTH // 2
        painter.drawRect(
            QRect(half, half, self.width() - BORDER_WIDTH, self.height() - BORDER_WIDTH)
        )

    def show_over(self, rect: RegionArea) -> None:
        self.set_region(rect)
        self.show()
        self.raise_()

    @staticmethod
    def random_colour() -> str:
        hue = random.randrange(360)
        colour = QColor.fromHsv(hue, 200, 255)
        return colour.name()  # Hex string, e.g. "#ff8537"
