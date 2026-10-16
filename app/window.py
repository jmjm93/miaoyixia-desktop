from app.i18n import tr
"""The app's front door.

Until now the whole thing was a tray icon and two chords, which is fine once you know them and
opaque before that. This is the discoverable version: the actions are buttons, the hotkeys are
printed beside them rather than memorised, and the current state says itself in words.

Deliberately small and always reachable. It is a launcher, not a workspace -- everything
interesting still happens in the overlay and the result window.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

STYLE = """
#root { background: #12161E; }
QLabel { color: #E6EAF2; }
#wordmark { font-size: 26px; font-weight: 600; }
#tagline { color: #8A93A6; font-size: 12px; }
#hint { color: #6B7488; font-size: 11px; }

QPushButton#primary, QPushButton#secondary {
  border-radius: 8px; padding: 11px 14px; font-size: 14px; text-align: left;
}
QPushButton#primary {
  background: #2C3A66; color: #FFFFFF; border: 1px solid #4A5C9E;
}
QPushButton#primary:hover { background: #35467C; border-color: #6377C9; }
QPushButton#secondary {
  background: #1B222E; color: #D7DEEA; border: 1px solid #2E3745;
}
QPushButton#secondary:hover { background: #232C3B; border-color: #4A566C; }
QPushButton#secondary:checked {
  background: #3A2A1A; border-color: #FFB020; color: #FFD79A;
}
QPushButton#quiet {
  background: transparent; color: #8A93A6; border: none; font-size: 12px; padding: 6px;
}
QPushButton#quiet:hover { color: #D7DEEA; }

#status { background: #0E1116; border: 1px solid #232A36; border-radius: 8px; }
#statusText { font-size: 13px; }
#statusHint { color: #6B7488; font-size: 11px; }
#swatch { border-radius: 4px; }
"""


def _swatch(colour: QColor, size: int = 14) -> QPixmap:
    """The colour chip that ties a reading to the rectangle it came from."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(colour)
    painter.drawRoundedRect(0, 0, size, size, 3, 3)
    painter.end()
    return pixmap


class MainWindow(QWidget):
    """Buttons for the things the hotkeys do."""

    snip_requested = Signal()
    watch_toggled = Signal()
    quit_requested = Signal()
    options_requested = Signal()

    def __init__(self, snip_hotkey: str, watch_hotkey: str, region_colour: QColor, language: str = "zh"):
        super().__init__(None)
        self.setWindowTitle("瞄一下")
        self.setStyleSheet(STYLE)
        self.setFixedWidth(340)

        root = QFrame(self)
        root.setObjectName("root")
        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.addWidget(root)

        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(14)

        wordmark = QLabel(tr("瞄一下"))
        wordmark.setObjectName("wordmark")
        from core.languages import LANGUAGES
        tagline = QLabel(tr(f"Read the {LANGUAGES[language]} on your screen"))
        self._tagline = tagline
        tagline.setObjectName("tagline")
        layout.addWidget(wordmark)
        layout.addWidget(tagline)

        self._snip = QPushButton(tr(f"  Snip once\t\t{snip_hotkey}"))
        self._snip.setObjectName("primary")
        self._snip.setCursor(Qt.PointingHandCursor)
        self._snip.setToolTip(tr("Drag a box over any text and read it"))
        self._snip.clicked.connect(self.snip_requested)
        layout.addWidget(self._snip)

        self._watch_idle_label = f"  Watch a region\t{watch_hotkey}"
        self._watch = QPushButton(self._watch_idle_label)
        self._watch.setObjectName("secondary")
        self._watch.setCheckable(True)
        self._watch.setCursor(Qt.PointingHandCursor)
        self._watch.setToolTip(
            tr("Pin an area that keeps changing -- a dialogue box -- and re-read it automatically")
        )
        self._watch.clicked.connect(self.watch_toggled)
        layout.addWidget(self._watch)

        # --- state -------------------------------------------------------------------
        status = QFrame()
        status.setObjectName("status")
        status_layout = QHBoxLayout(status)
        status_layout.setContentsMargins(12, 10, 12, 10)
        status_layout.setSpacing(10)

        self._swatch_label = QLabel()
        self._swatch_label.setObjectName("swatch")
        self._swatch_label.setPixmap(_swatch(region_colour))
        self._swatch_label.setFixedSize(14, 14)
        self._swatch_label.hide()
        status_layout.addWidget(self._swatch_label, 0, Qt.AlignTop)

        text_column = QVBoxLayout()
        text_column.setSpacing(2)
        self._status = QLabel(tr("Starting…"))
        self._status.setObjectName("statusText")
        self._status_hint = QLabel(tr("loading the dictionary and recogniser"))
        self._status_hint.setObjectName("statusHint")
        self._status_hint.setWordWrap(True)
        text_column.addWidget(self._status)
        text_column.addWidget(self._status_hint)
        status_layout.addLayout(text_column, 1)

        layout.addWidget(status)

        footer = QHBoxLayout()
        hint = QLabel(tr("Runs in the tray. Closing this window leaves it running."))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        quit_button = QPushButton(tr("Quit"))
        options_button = QPushButton(tr("Options"))
        options_button.setObjectName("quiet")
        options_button.clicked.connect(self.options_requested)
        quit_button.setObjectName("quiet")
        quit_button.setCursor(Qt.PointingHandCursor)
        quit_button.clicked.connect(self.quit_requested)
        footer.addWidget(hint, 1)
        footer.addWidget(options_button, 0, Qt.AlignBottom)
        footer.addWidget(quit_button, 0, Qt.AlignBottom)
        layout.addLayout(footer)

    # --- state the window reflects -------------------------------------------------------

    def set_language(self, language: str) -> None:
        from core.languages import LANGUAGES
        self._tagline.setText(tr(f"New captures: {LANGUAGES[language]}"))

    def set_ready(self, ready: bool, detail: str = "") -> None:
        self._snip.setEnabled(ready)
        self._watch.setEnabled(ready)
        if ready:
            self._status.setText(tr("Ready"))
            self._status_hint.setText(tr(detail or "Snip anything, or pin a region to watch"))
        else:
            self._status.setText(tr("Starting…"))
            self._status_hint.setText(tr(detail or "loading the dictionary and recogniser"))

    def set_watching(self, watching: bool, region: tuple[int, int, int, int] | None = None) -> None:
        self._watch.setChecked(watching)
        self._watch.setText(tr("  Stop watching" if watching else self._watch_idle_label))
        self._swatch_label.setVisible(watching)
        if watching:
            self._status.setText(tr("Watching a region"))
            where = f"{region[2]}×{region[3]} at {region[0]}, {region[1]}" if region else ""
            self._status_hint.setText(
                tr(f"{where} — re-read whenever the text changes" if where else "re-reading on change")
            )
        else:
            self._status.setText(tr("Ready"))
            self._status_hint.setText(tr("Snip anything, or pin a region to watch"))

    def set_reading(self, line: str) -> None:
        """Echo the most recent reading, so the window shows something is happening."""
        if line:
            self._status_hint.setText(tr(line[:60] + ("…" if len(line) > 60 else "")))

    def closeEvent(self, event):  # noqa: N802
        """Hide rather than quit: the tray icon is the app's real lifetime."""
        event.ignore()
        self.hide()


def app_icon() -> QIcon:
    """The wordmark's first character on a dark round-rect. Placeholder until there is real art."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#12161E"))
    painter.drawRoundedRect(2, 2, 60, 60, 14, 14)
    painter.setPen(QColor("#FFFFFF"))
    font = painter.font()
    font.setPointSize(34)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "瞄")
    painter.end()
    return QIcon(pixmap)
