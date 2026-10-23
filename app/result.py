from app.i18n import tr
"""The snip result: the capture, and what was read out of it underneath.

Structurally the extension's result.js, minus everything that existed to survive a hostile page.
Gone: the shadow root (nothing to isolate from), the stylesheet double-load, and the whole
#position / #applyCompact / #applyGutter / setZoom block, which was arithmetic for fitting a card
inside someone else's viewport. A native window has an OS to do that.

Kept, because they are the parts that earn their place:

  * the capture on top, always -- "when the text comes back wrong, seeing what was actually
    captured is what tells the user to zoom in and snip again"
  * the recognised line, editable, re-segmenting on commit. The extension calls this the most
    valuable thing in the window and it is right
  * word chips, and candidate tabs under them, so a bad split costs a click rather than a re-snip
"""

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal, Slot
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QShortcut,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.flow_layout import wrap_in_flow
from core.reading import Token

SHOT_MAX_HEIGHT = 260
#: The transcript grows between these before it starts scrolling. The floor is three-ish lines,
#: so a stream of subtitles shows some history rather than one line at a time.
TRANSCRIPT_MIN_HEIGHT = 78
TRANSCRIPT_MAX_HEIGHT = 190
#: Lines the transcript keeps before it starts dropping the oldest.
#:
#: A watched region appends forever, and a subtitle track is a line every few seconds -- so an
#: evening of watching is tens of thousands of lines in a QPlainTextEdit, every one of them
#: re-laid-out by _fit_log on each new arrival. Unbounded growth in the one widget that is
#: guaranteed to be on screen during a long session is worth a ceiling whatever else is wrong.
#: Far more than is readable: the box shows about six at a time.
TRANSCRIPT_MAX_LINES = 400
#: Chips wrap, so a long enough line has no natural height. Four rows is as much of a sentence as
#: is worth showing at once; past that the chips scroll and the definitions keep their room.
CHIP_ROWS_SHOWN = 4
CHIP_SPACING = 5
WINDOW_WIDTH = 460
#: Left and right inset of everything below the capture.
BODY_MARGIN = 14
EDGE = 12

STYLE = """
#card { background: #151A22; border: 1px solid #2A313D; border-radius: 10px; }
#shot { background: #0E1116; border-bottom: 1px solid #2A313D; }
QLabel { color: #E6EAF2; }
#status { color: #98A2B4; font-size: 12px; padding: 2px 14px 8px; }
#meta   { color: #6B7488; font-size: 11px; padding: 0 14px 8px; }
#line {
  background: #0E1116; color: #F2F5FA; border: 1px solid #2A313D; border-radius: 6px;
  padding: 7px 9px; font-size: 17px; selection-background-color: #33407A;
}
#line:focus { border-color: #5A6BC4; }
#translation {
  background: #101923; color: #C6D8E8; border: 1px solid #2D3D4D; border-radius: 6px;
  padding: 7px 9px; font-size: 13px; selection-background-color: #33407A;
}
#translationTitle { color: #8FA5BC; font-size: 11px; }
QPushButton#translationRetry { color: #9FB3D9; background: transparent; border: none; font-size: 11px; }
QPushButton#chip {
  background: #1D2430; color: #D7DEEA; border: 1px solid #2E3745; border-radius: 6px;
  padding: 5px 10px; font-size: 16px;
}
QPushButton#chip:hover { border-color: #4A566C; }
QPushButton#chip:checked { background: #2C3A66; border-color: #5A6BC4; color: #FFFFFF; }
QPushButton#chip:disabled { color: #5C6478; background: #171C25; border-color: #232A36; }
QPushButton#anki {
  background: #1D2430; color: #9FB3D9; border: 1px solid #2E3745; border-radius: 6px;
  padding: 3px 9px; font-size: 12px;
}
QPushButton#anki:hover { border-color: #5A6BC4; color: #E6EAF2; }
QPushButton#anki:disabled { color: #5C6478; background: #171C25; border-color: #232A36; }
/* After :disabled, not before. Qt resolves a tie in specificity by source order, and every one
   of these states is also disabled -- put them first and the grey wins every time. */
QPushButton#anki[state="added"], QPushButton#anki[state="duplicate"] {
  color: #7FB77E; border-color: #2F5A38; background: #16241A;
}
QPushButton#anki[state="added"]:hover, QPushButton#anki[state="duplicate"]:hover {
  color: #B6E5B5; border-color: #4C8A58;
}
QPushButton#anki[state="error"] { color: #D98A8A; border-color: #5A3030; background: #241618; }
QPushButton#tab {
  background: transparent; color: #98A2B4; border: none; border-bottom: 2px solid transparent;
  padding: 4px 9px; font-size: 12px;
}
QPushButton#tab:checked { color: #C9D3E6; border-bottom-color: #5A6BC4; }
#headword { font-size: 21px; font-weight: 600; }
#pinyin { color: #8FA0FF; font-size: 14px; }
#sense { color: #C6CEDC; font-size: 13px; }
#divider { background: #242C38; }
/* QScrollArea gives its viewport an opaque background from the *palette*, not the stylesheet,
   so styling the QScrollArea alone leaves a white slab behind the definitions. The scrolled
   widget has to be named and cleared too. */
QScrollArea { border: none; background: transparent; }
#entryHost, #chipHost, #tabHost, #entryRow { background: transparent; }
QScrollBar:vertical { background: transparent; width: 9px; margin: 2px; }
QScrollBar::handle:vertical { background: #333C4C; border-radius: 4px; min-height: 28px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QPushButton#action {
  background: rgba(14, 17, 22, 0.72); border: 1px solid #333C4C; border-radius: 6px;
}
QPushButton#action:hover { background: rgba(44, 58, 102, 0.92); border-color: #5A6BC4; }
QPushButton#action:checked { background: #2C3A66; border-color: #5A6BC4; }
"""

#: Anki button states in which clicking does something. Everything else -- the check that has
#: not come back, the add in flight, the failure -- is an outcome to read, not an offer.
ANKI_ACTIONABLE = frozenset({"idle", "duplicate", "added"})

#: Gap between the action buttons and the window edge.
ACTIONS_INSET = 8


def _action_icon(kind: str) -> QIcon:
    """Draw the button glyphs rather than typing them.

    The extension made the same call for the same reason -- "a font character inherits the page's
    own emoji and symbol rendering, and '⟲' in particular lands somewhere different in every
    fallback font". Drawing removes the dependency on what happens to be installed.
    """
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor("#D7DEEA"))
    pen.setWidthF(2.4)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)

    if kind == "close":
        painter.drawLine(11, 11, 21, 21)
        painter.drawLine(21, 11, 11, 21)
    elif kind == "rescan":
        for x, y, dx, dy in ((7, 8, 5, 5), (25, 8, -5, 5),
                              (7, 24, 5, -5), (25, 24, -5, -5)):
            painter.drawLine(x, y, x + dx, y)
            painter.drawLine(x, y, x, y + dy)
        painter.drawLine(10, 16, 22, 16)
    elif kind == "translation":
        painter.drawRoundedRect(QRect(6, 7, 20, 17), 3, 3)
        painter.drawLine(10, 12, 18, 12)
        painter.drawLine(14, 10, 14, 19)
        painter.drawLine(18, 20, 21, 14)
        painter.drawLine(21, 14, 24, 20)
    else:  # retry: an open circle with a tick at the end, read as "go round again"
        painter.drawArc(QRect(9, 9, 14, 14), 30 * 16, 290 * 16)
        painter.drawLine(21, 6, 21, 12)
        painter.drawLine(21, 12, 15, 12)

    painter.end()
    return QIcon(pixmap)


class ResultWindow(QWidget):
    """One window per snip, reused across snips."""

    #: The user corrected the recognised line; look the corrected text up instead.
    edited = Signal(str)
    #: Close and go straight back to framing -- the usual answer to a capture that read badly.
    retry = Signal()
    #: Dismissed on purpose, by the close button or Escape. Distinct from hide(), which the retry
    #: path also uses: this one means "I am done", and a watched region should stop watching.
    closed = Signal()
    #: Ask whether these cards are already in the collection. (ticket, [Card]) -- see app/anki.py
    #: for what the ticket is for.
    anki_inspect = Signal(int, object)
    #: Add one of them. (ticket, index within the candidate, Card)
    anki_add = Signal(int, int, object)
    #: Show the one already in the collection. (ticket, index, Card)
    anki_browse = Signal(int, int, object)
    translation_requested = Signal(int, str)
    translation_cancelled = Signal()
    mode_changed = Signal(str)
    rescan_requested = Signal()

    def __init__(self, language: str = "zh"):
        super().__init__(None)
        from core.languages import validate
        self.language = validate(language)
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating, False)
        self.setStyleSheet(STYLE)
        self.setFixedWidth(WINDOW_WIDTH)

        self._drag_from: QPoint | None = None
        self._tokens: list[Token] = []
        self._active = 0
        self._candidate = 0

        # Anki. Off until main.py says the config enabled it, so a window built by a test or by
        # someone who has never configured Anki has no button and asks nothing of the network.
        self._anki_enabled = False
        self._anki_deck = ""
        #: Bumped on every render. A reply quoting an older ticket describes a word that is no
        #: longer on screen -- words are clicked through faster than a round trip -- and applying
        #: it would grey out the button of whatever happens to be showing now.
        self._anki_ticket = 0
        self._anki_buttons: list[QPushButton] = []
        self._anki_cards: tuple = ()
        self._translation_enabled = False
        self._translation_override = None
        self._translation_target = "en"
        self._translation_ticket = 0
        self._translation_line = ""

        card = QFrame(self)
        card.setObjectName("card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)

        self._layout = QVBoxLayout(card)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        # --- which region this came from ---------------------------------------------
        # A solid bar in the watched region's colour, matching the frame drawn on screen. Hidden
        # for an ordinary snip, where there is no rectangle left behind to tie it back to. This is
        # the whole identification scheme: no labels to read, just the same colour in two places.
        self._region_bar = QFrame()
        self._region_bar.setObjectName("regionBar")
        # Six, not four: the card is rounded at 10px, so the ends of a thinner bar are eaten by
        # the corner radius and what survives reads as a rendering artefact rather than a marker.
        self._region_bar.setFixedHeight(6)
        self._region_bar.hide()
        self._layout.addWidget(self._region_bar)

        # --- the capture -------------------------------------------------------------
        self._shot = QLabel()
        self._shot.setObjectName("shot")
        self._shot.setAlignment(Qt.AlignCenter)
        self._shot.setMinimumHeight(60)
        self._layout.addWidget(self._shot)

        self._status = QLabel()
        self._status.setObjectName("status")
        self._status.setWordWrap(True)
        self._layout.addWidget(self._status)

        # --- the recognised line -----------------------------------------------------
        body = QVBoxLayout()
        body.setContentsMargins(BODY_MARGIN, 6, BODY_MARGIN, 12)
        body.setSpacing(10)

        # A transcript, not a single line. While a region is being watched this accumulates every
        # line that has appeared in it, newest last -- so a subtitle that has already gone by is
        # still readable, which a box holding only the latest reading cannot offer.
        #
        # Still editable, because that is the most valuable thing in the window: correcting a
        # fumbled glyph by eye and pressing Enter re-looks-up without a re-snip. Enter acts on the
        # line the cursor is on, which also means an earlier line can be revisited by clicking
        # into it -- the definitions below always describe one line, never the whole log.
        self._log = QPlainTextEdit()
        self._log.setObjectName("line")
        self._log.setPlaceholderText(tr("nothing legible"))
        self._log.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._log.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._log.textChanged.connect(self._fit_log)
        body.addWidget(self._log)

        # Whole-sentence translation, independent of the word selected below.
        self._translation_host = QWidget()
        translation_layout = QVBoxLayout(self._translation_host)
        translation_layout.setContentsMargins(0, 0, 0, 0)
        translation_layout.setSpacing(4)
        translation_header = QHBoxLayout()
        self._translation_title = QLabel(tr("Translation · MyMemory"))
        self._translation_title.setObjectName("translationTitle")
        translation_header.addWidget(self._translation_title)
        translation_header.addStretch(1)
        self._translation_retry = QPushButton(tr("Retry"))
        self._translation_retry.setObjectName("translationRetry")
        self._translation_retry.setCursor(Qt.PointingHandCursor)
        self._translation_retry.clicked.connect(self._request_translation)
        translation_header.addWidget(self._translation_retry)
        translation_layout.addLayout(translation_header)
        self._translation = QPlainTextEdit()
        self._translation.setObjectName("translation")
        self._translation.setReadOnly(True)
        self._translation.setPlaceholderText(tr("The full text translation will appear here"))
        self._translation.setFixedHeight(90)
        self._translation.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        translation_layout.addWidget(self._translation)
        body.addWidget(self._translation_host)
        self._translation_host.hide()
        self._translation_retry.hide()

        # Chips: one per segmented word.
        #
        # Wrapping, not a row. A row is what this was, and a long sentence -- twenty-one chips out
        # of thirty-eight characters -- squeezed every one of them to 16px, which is narrower than
        # their own padding: unreadable, and barely clickable. Each chip now keeps the width its
        # text needs and the ones that do not fit start a new line, the way the sentence they came
        # from would.
        chip_host = QWidget()
        chip_host.setObjectName("chipHost")
        self._chips = wrap_in_flow(chip_host, spacing=CHIP_SPACING)
        chip_host.setAutoFillBackground(False)

        # Rows are capped and then scroll, for the same reason the transcript and the definitions
        # are. A snip is not always one line: the recogniser joins every text box it finds in the
        # region into a single string, so a box dragged over a manhua page or a paragraph of a PDF
        # -- both of which this is for -- segments into a hundred chips. Unbounded, those rows
        # push the definitions off the bottom of the screen, which is the one thing _place refuses
        # to allow.
        chip_scroll = QScrollArea()
        chip_scroll.setWidget(chip_host)
        chip_scroll.setWidgetResizable(True)
        chip_scroll.setFrameShape(QFrame.NoFrame)
        chip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        chip_scroll.viewport().setAutoFillBackground(False)
        body.addWidget(chip_scroll)
        self._chip_scroll = chip_scroll
        self._chip_host = chip_host

        # Candidate tabs: the other dictionary lengths at the selected word's position.
        self._tabs = QHBoxLayout()
        self._tabs.setSpacing(2)
        self._tabs.setContentsMargins(0, 0, 0, 0)
        tab_host = QWidget()
        tab_host.setObjectName("tabHost")
        tab_host.setLayout(self._tabs)
        body.addWidget(tab_host)
        self._tab_host = tab_host

        # The entry itself, scrollable because a common word has many senses.
        self._entry = QVBoxLayout()
        self._entry.setSpacing(6)
        self._entry.setContentsMargins(0, 0, 0, 0)
        entry_host = QWidget()
        entry_host.setObjectName("entryHost")
        entry_host.setLayout(self._entry)
        scroll = QScrollArea()
        scroll.setObjectName("entryScroll")
        scroll.setWidget(entry_host)
        scroll.setWidgetResizable(True)
        # A floor as well as a ceiling. Without the floor the window shrinks to its sizeHint and
        # the definitions get whatever is left over -- which on a tall capture was two clipped
        # lines. The definitions are the reason the window exists; the capture can give up room
        # for them, which is what SHOT_MAX_HEIGHT is for.
        scroll.setMinimumHeight(150)
        scroll.setMaximumHeight(260)
        scroll.setFrameShape(QFrame.NoFrame)
        # Belt and braces with the stylesheet above: the viewport fills itself from the palette
        # unless told not to, and that is what painted the definitions onto white.
        scroll.viewport().setAutoFillBackground(False)
        entry_host.setAutoFillBackground(False)
        body.addWidget(scroll)
        self._scroll = scroll

        self._layout.addLayout(body)

        self._meta = QLabel()
        self._meta.setObjectName("meta")
        self._layout.addWidget(self._meta)
        self._dictionary_source = QLabel(tr('<a href="https://www.edrdg.org/wiki/index.php/JMdict-EDICT_Dictionary_Project">'
                            'JMdict · EDRDG</a> · <a href="https://www.edrdg.org/edrdg/licence.html">CC BY-SA 4.0</a>'))
        self._dictionary_source.setObjectName("meta")
        self._dictionary_source.setOpenExternalLinks(True)
        self._layout.addWidget(self._dictionary_source)
        self._dictionary_source.setVisible(self.language == "ja")

        # --- close and retry ---------------------------------------------------------
        # Children of the window rather than of the card, and positioned in resizeEvent rather
        # than by a layout: they float over the capture. The extension learned this the hard way
        # -- inside the scrolling card "these went off the top the moment the window had more in
        # it than would fit".
        #
        # Retry sits before close, in the order the user reaches for them: a capture that read
        # badly is far more often reframed than abandoned.
        self._actions = QWidget(self)
        actions = QHBoxLayout(self._actions)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(5)
        for kind, tip, slot in (
            ("mode", "Switch to manual mode", self._toggle_mode),
            ("rescan", "Rescan region", self.rescan_requested.emit),
            ("translation", "Enable translation", self._toggle_translation),
            ("retry", "Snip again", self._retry),
            ("close", "Close  (Esc)", self.dismiss),
        ):
            button = QPushButton()
            button.setObjectName("action")
            button.setIcon(_action_icon(kind))
            if kind == "mode":
                self._mode_button = button
                button.setIcon(QIcon())
                button.setText(tr("A"))
                button.setStyleSheet("color: #D7DEEA;")
                button.setAccessibleName("Switch automatic/manual region mode")
            elif kind == "rescan":
                self._rescan_button = button
                button.setIcon(_action_icon("rescan"))
                button.setEnabled(False)
                button.setAccessibleName("Rescan pinned region")
            button.setIconSize(QSize(16, 16))
            button.setFixedSize(26, 26)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(tr(tip))
            button.clicked.connect(slot)
            if kind == "translation":
                self._translation_toggle = button
                button.setCheckable(True)
                button.setAccessibleName("Toggle whole-text translation")
            actions.addWidget(button)
        self._actions.adjustSize()
        self._region_mode = "automatic"

        QShortcut(QKeySequence(Qt.Key_Escape), self, self.dismiss)
        # Commit the edited line. Enter rather than a button: this is one line of text and the
        # reading below it is what the user is actually after.
        QShortcut(QKeySequence(Qt.Key_Return), self._log, self._commit)
        QShortcut(QKeySequence(Qt.Key_Enter), self._log, self._commit)

    # --- capture -----------------------------------------------------------------------

    def set_language(self, language: str) -> None:
        from core.languages import validate
        self._clear()
        self.language = validate(language)
        self._dictionary_source.setVisible(language == "ja")

    def _toggle_mode(self) -> None:
        self.mode_changed.emit("manual" if self._region_mode == "automatic" else "automatic")

    def set_region_mode(self, mode: str, active: bool, hotkey: str) -> None:
        self._region_mode = mode
        self._mode_button.setText(tr("M" if mode == "manual" else "A"))
        self._mode_button.setToolTip(tr(f"{mode.capitalize()} mode · click to switch"))
        self._rescan_button.setEnabled(active)
        self._rescan_button.setToolTip(tr(f"Rescan pinned region ({hotkey})"))

    def show_capture(
        self,
        image,
        near: tuple[int, int, int, int],
        activate: bool = True,
        reposition: bool = True,
    ) -> None:
        """Put the capture on screen before recognition has finished.

        The user sees what they framed rather than an empty wait, which is also what makes a bad
        reading self-evident when it arrives.

        `activate` must be False for updates driven by the region watcher. Taking focus is right
        after a deliberate snip -- the user probably wants to edit the line -- but a watched region
        updates while they are playing, and stealing focus from a fullscreen game every time a new
        line of dialogue appears would make the app unusable and the game worse.

        `reposition` likewise: a watched window should stay where it was put, not hop about as
        each new line changes the card's height.
        """
        self.setAttribute(Qt.WA_ShowWithoutActivating, not activate)
        data = image.convert("RGB").tobytes("raw", "RGB")
        qimage = QImage(data, image.width, image.height, image.width * 3, QImage.Format_RGB888)
        self._shot_bytes = data  # QImage does not copy; keep the buffer alive
        pixmap = QPixmap.fromImage(qimage)

        available = WINDOW_WIDTH - 2
        if pixmap.width() > available or pixmap.height() > SHOT_MAX_HEIGHT:
            pixmap = pixmap.scaled(
                QSize(available, SHOT_MAX_HEIGHT), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        self._shot.setPixmap(pixmap)

        if activate:
            self._clear()
            self._status.setText(tr("reading…"))
            self._meta.setText(tr(""))
        self.show()

        # Both of these are conditional, and both matter for a watched region. Moving the window
        # on every new line undoes any placement the user chose by hand -- they will have dragged
        # it clear of the thing they are reading, and having it jump back is worse than it being
        # slightly wrong. Raising is skipped for the same reason: the window already carries
        # WindowStaysOnTopHint, so raise_() buys nothing and can pop it over a fullscreen game.
        if reposition:
            self._place(near)
        if activate:
            self.raise_()

    def _place(self, near: tuple[int, int, int, int]) -> None:
        """Below the snipped region, flipping above when there is no room.

        The rule is the extension's popup rule, for its reason: the window must not cover the
        thing it describes.

        The screen is chosen from the SNIP, never from where this window currently sits. Asking
        `screenAt(self.mapToGlobal(...))` seems natural and is a trap: the window's position is an
        output of this function, so using it as an input makes the placement self-referential. In
        practice it latched onto whichever monitor the window had drifted to and clamped every
        later snip into that monitor's bounds -- a snip at x=400 on the primary display placed the
        window at x=-473 on the secondary one, and it never came back, because each placement
        re-read the wrong position it had just written. The visible symptom was a window with its
        top cut off: definitions showing, capture and recognised line clipped away above the
        screen edge.
        """
        x, y, w, h = near
        centre = QPoint(x + w // 2, y + h // 2)
        screen = QGuiApplication.screenAt(centre) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()

        # Size settled before positioning: the height decides whether it can sit below the snip.
        self.adjustSize()
        size = self.size()

        top = y + h + EDGE
        if top + size.height() > area.bottom():
            flipped = y - EDGE - size.height()
            if flipped >= area.top():
                top = flipped

        # The last word, whatever the preference above worked out. Staying wholly on screen is not
        # negotiable; which side of the snip it lands on is. A window taller than the display
        # pins to the top, so the capture and the line stay visible and the definitions scroll.
        top = max(area.top(), min(top, area.bottom() - size.height() + 1))
        left = max(area.left(), min(x, area.right() - size.width() + 1))
        self.move(int(left), int(top))
        self._keep_actions_in_corner()

    # --- reading -----------------------------------------------------------------------

    def show_reading(self, reading, append: bool = False) -> None:
        """Show a reading. `append` adds to the transcript instead of replacing it.

        A snip replaces: it is a new context and the old text is not about it. A watched region
        appends: the previous subtitle is still worth being able to read.

        Either way the chips and definitions below describe exactly one line -- the newest -- so
        the transcript grows without the lookup below it becoming a list of everything ever seen.
        """
        if append:
            self.append_line(reading.line)
        else:
            self.set_line(reading.line)
        old = self._translation_line
        common = 0
        for before, after in zip(old, reading.line):
            if before != after:
                break
            common += 1
        # A few unstable glyphs at the end must not undo a definition being studied.
        # New text is still displayed; this preserves a matching token/candidate only.
        preserve = append and common >= 8 and max(len(old), len(reading.line)) - common <= 3
        self.set_tokens(reading.tokens, preserve=preserve)
        self._translation_line = reading.line
        self._request_translation()

        bits = [f"{reading.ocr_ms:.0f}ms"]
        if reading.orientation:
            bits.append(reading.orientation)
        if reading.undetected:
            bits.append("whole-crop fallback")
        if reading.scores:
            bits.append(f"min score {min(reading.scores):.2f}")
        self._meta.setText(tr("  ·  ".join(bits)))

    def set_tokens(self, tokens: list[Token], preserve: bool = False) -> None:
        previous = None
        if preserve and 0 <= self._active < len(self._tokens):
            token = self._tokens[self._active]
            if token.candidates and 0 <= self._candidate < len(token.candidates):
                previous = (token.start, token.text, token.candidates[self._candidate].headword)
        self._tokens = tokens
        self._clear_chips()

        if not tokens:
            self._status.setText(tr("nothing legible — try framing tighter, or type it above"))
            self._chip_scroll.hide()
            self._tab_host.hide()
            return

        self._status.setText(tr(""))
        self._chip_scroll.show()
        for index, token in enumerate(tokens):
            chip = QPushButton(token.text)
            chip.setObjectName("chip")
            chip.setCheckable(True)
            chip.setCursor(Qt.PointingHandCursor)
            # A character the dictionary has nothing for -- punctuation, or something OCR
            # invented. Shown so the line reads whole, but there is nothing to select.
            chip.setEnabled(bool(token.candidates))
            chip.clicked.connect(lambda _=False, i=index: self.select_token(i))
            self._chips.addWidget(chip)
            # Shown here rather than left to the layout's own pass, because the height of the
            # chip area is worked out below and a layout item holding a widget that has not been
            # shown yet measures zero. Without this the whole strip came out 0px tall.
            chip.show()
        self._fit_chips(chip.sizeHint().height())

        first = next((i for i, t in enumerate(tokens) if t.candidates), 0)
        self.select_token(first)
        if previous:
            start, text, headword = previous
            for index, token in enumerate(tokens):
                if token.start == start and token.text == text:
                    candidate = next((i for i, c in enumerate(token.candidates) if c.headword == headword), None)
                    if candidate is not None:
                        self.select_token(index)
                        self._show_candidates(token, candidate)
                    break

    def select_token(self, index: int) -> None:
        if not (0 <= index < len(self._tokens)):
            return
        self._active = index
        for i in range(self._chips.count()):
            widget = self._chips.itemAt(i).widget()
            if isinstance(widget, QPushButton):
                widget.setChecked(i == index)

        token = self._tokens[index]
        # Open on the candidate segmentation chose, not the longest one. See
        # core.reading._default_candidate for why the extension's default is wrong after a snip.
        self._show_candidates(token, token.default)

    def _show_candidates(self, token: Token, which: int) -> None:
        self._clear_layout(self._tabs)
        self._candidate = which

        if not token.candidates:
            self._tab_host.hide()
            self._render_entry(None)
            return

        # Only worth a row when there is a choice to make.
        self._tab_host.setVisible(len(token.candidates) > 1)
        for i, candidate in enumerate(token.candidates):
            tab = QPushButton(candidate.headword)
            tab.setObjectName("tab")
            tab.setCheckable(True)
            tab.setChecked(i == which)
            tab.setCursor(Qt.PointingHandCursor)
            tab.clicked.connect(lambda _=False, t=token, i=i: self._show_candidates(t, i))
            self._tabs.addWidget(tab)
        self._tabs.addStretch(1)

        self._render_entry(token.candidates[which])

    def _render_entry(self, candidate) -> None:
        self._clear_layout(self._entry)
        # Every button rendered below belongs to the ticket minted here, and nothing older is
        # allowed to touch them again.
        self._anki_ticket += 1
        self._anki_buttons = []
        self._anki_cards = candidate.cards if candidate else ()

        if candidate is None:
            self._entry.addStretch(1)
            return

        for index, card in enumerate(candidate.cards):
            head = QLabel(card.headword)
            head.setObjectName("headword")
            if self._anki_enabled:
                # One button per reading rather than one per word: 行 xíng and 行 háng are two
                # notes, and which of them is being studied is the user's call, not ours.
                self._entry.addWidget(self._headword_row(head, index, card))
            else:
                self._entry.addWidget(head)

            if card.has_variants:
                # Both scripts, because the reader of one may be mining the other.
                other = card.traditional if card.headword == card.simplified else card.simplified
                variant = QLabel(other)
                variant.setObjectName("pinyin")
                self._entry.addWidget(variant)

            if card.language == "ja" and card.as_read and card.as_read != card.headword:
                surface = QLabel(tr(f"As read: {card.as_read}"))
                surface.setObjectName("sense")
                self._entry.addWidget(surface)
            pinyin = QLabel(card.pronunciation)
            pinyin.setObjectName("pinyin")
            self._entry.addWidget(pinyin)

            for n, sense in enumerate(card.senses, 1):
                label = QLabel(f"{n}. {sense}" if len(card.senses) > 1 else sense)
                label.setObjectName("sense")
                label.setWordWrap(True)
                self._entry.addWidget(label)

            if card is not candidate.cards[-1]:
                rule = QFrame()
                rule.setObjectName("divider")
                rule.setFixedHeight(1)
                self._entry.addWidget(rule)

        self._entry.addStretch(1)

        if self._anki_enabled and self._anki_buttons:
            # Asked after rendering, never before. The round trip is Anki's to be slow at, and
            # blocking the definitions on it would undo the reason this window is quick.
            self.anki_inspect.emit(self._anki_ticket, list(candidate.cards))

    # --- whole-text translation ---------------------------------------------------------

    def _invalidate_translation(self) -> None:
        self._translation_ticket += 1
        self.translation_cancelled.emit()

    def set_translation_enabled(self, enabled: bool, target: str = "en") -> None:
        if self._translation_override is not None:
            enabled = self._translation_override
        self._translation_toggle.setChecked(enabled)
        self._translation_toggle.setToolTip(tr("Disable translation" if enabled else "Enable translation"))
        if (enabled, target) == (self._translation_enabled, self._translation_target):
            return
        self._translation_enabled, self._translation_target = enabled, target
        self._translation_title.setText(tr(f"Translation · {target.upper()} · MyMemory"))
        self._translation_host.setVisible(enabled)
        self._request_translation()

    def _toggle_translation(self) -> None:
        self._translation_override = not self._translation_enabled
        self.set_translation_enabled(self._translation_override, self._translation_target)

    def _request_translation(self) -> None:
        self._invalidate_translation()
        self._translation.clear()
        self._translation_retry.hide()
        if not self._translation_enabled or not self._translation_line.strip():
            return
        self._translation.setPlainText(tr("Translating…"))
        self.translation_requested.emit(self._translation_ticket, self._translation_line)

    @Slot(int, str, str)
    def apply_translation(self, ticket: int, text: str, error: str) -> None:
        if ticket != self._translation_ticket or not self._translation_enabled:
            return
        self._translation.setPlainText(tr(f"Translation unavailable: {error}") if error else text)
        self._translation_retry.setVisible(bool(error))

    # --- anki ---------------------------------------------------------------------------
    #
    # Every handler below is reached from the Anki thread, so each is a @Slot on a QObject --
    # that pairing is what makes Qt queue the call back onto the GUI thread before it touches
    # a widget. A bare lambda in the same place has no affinity to inspect and runs on the
    # worker instead; see App's docstring for what Windows does about that.

    def set_anki_enabled(self, enabled: bool, deck: str = "", refresh: bool = False) -> None:
        """Turn the add button on or off, and show the change straight away.

        Re-rendering matters because this is reached from a config reload, and a switch you have
        just flipped that does nothing until the next snip reads as a switch that does nothing.
        The candidate tab is carried over rather than reset -- the user picked it, and this is
        not their edit.
        """
        if not refresh and (enabled, deck) == (self._anki_enabled, self._anki_deck):
            return
        self._anki_enabled = enabled
        self._anki_deck = deck
        if self._tokens and 0 <= self._active < len(self._tokens):
            self._show_candidates(self._tokens[self._active], self._candidate)

    def _headword_row(self, head: QLabel, index: int, card) -> QWidget:
        """The headword with its add button, as one widget rather than a nested layout.

        A widget because _clear_layout only deletes what it can reach through item.widget(), and
        a layout added to a layout answers None to that -- the row and everything in it would
        survive the next render and stack up behind it.
        """
        row = QWidget()
        row.setObjectName("entryRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(head)
        layout.addStretch(1)

        button = QPushButton(tr("+ Anki"))
        button.setObjectName("anki")
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(lambda _=False, i=index: self._anki_clicked(i))
        # Starts greyed, not enabled. The extension starts its button live to keep the popup
        # instant, and that is a small lie this window does not need to tell: nothing has been
        # asked of Anki yet, so whether the word can be added is genuinely unknown. Worse, with
        # Anki closed the reply may be a connection that hangs rather than one refused, leaving a
        # button that invites a click for as long as the timeout -- and can do nothing with it.
        # Anki answers a local call in milliseconds when it is running, so the wait costs nothing
        # when there is something to wait for.
        self._set_anki_state(button, "checking", "+ Anki", "Checking Anki…")
        layout.addWidget(button, 0, Qt.AlignTop)
        self._anki_buttons.append(button)
        return row

    def _anki_clicked(self, index: int) -> None:
        """Add it, or -- when the deck already has it -- go and look at it.

        A word already mined is the commonest thing this button has to say, and "you cannot have
        this" is a poor use of the only control in reach. Anki can open its browser on a query,
        so the dead end becomes the way through to the note.
        """
        button = self._anki_buttons[index]
        state = button.property("state")
        if state not in ANKI_ACTIONABLE:
            return
        if state in ("duplicate", "added"):
            self.anki_browse.emit(self._anki_ticket, index, self._anki_cards[index])
            return
        self._set_anki_state(button, "busy", "adding…", "")
        self.anki_add.emit(self._anki_ticket, index, self._anki_cards[index])

    @staticmethod
    def _set_anki_state(button: QPushButton, state: str, text: str, tooltip: str) -> None:
        """Only 'idle' stays clickable; every other state is an outcome, not an offer.

        The unpolish/polish pair is not optional: Qt resolves property selectors when a widget is
        polished, so a stylesheet keyed on [state] does not repaint just because the property
        changed.
        """
        button.setProperty("state", state)
        button.setText(tr(text))
        button.setToolTip(tr(tooltip))
        button.setEnabled(state in ANKI_ACTIONABLE)
        button.style().unpolish(button)
        button.style().polish(button)

    @Slot(int, object)
    def apply_anki_states(self, ticket: int, result: dict) -> None:
        """Anki has answered: turn the buttons on, or say why not.

        This is the only thing that makes a button live, which is the point -- until it runs, the
        window has no grounds for offering one.
        """
        if ticket != self._anki_ticket:
            return
        for index, state in enumerate(result.get("states", ())):
            if index >= len(self._anki_buttons):
                break
            button = self._anki_buttons[index]
            card = self._anki_cards[index] if index < len(self._anki_cards) else None
            word = card.headword if card else ""
            if state["duplicate"]:
                self._set_anki_state(button, "duplicate", "✓ in deck", self._browse_tip("Already in"))
            elif not state["canAdd"]:
                self._set_anki_state(button, "error", "✕ Anki", state["error"])
            else:
                self._set_anki_state(
                    button, "idle", "+ Anki", f"Add {word} to {self._anki_deck or 'Anki'}"
                )

    def _browse_tip(self, lead: str) -> str:
        return f"{lead} {self._anki_deck or 'Anki'} — click to open it in Anki"

    @Slot(int, int, object)
    def anki_added(self, ticket: int, index: int, result: dict) -> None:
        if ticket != self._anki_ticket or index >= len(self._anki_buttons):
            return
        created = result.get("created") or []
        tip = self._browse_tip("Added to")
        if created:
            tip += "  (created " + " and ".join(created) + ")"
        label = "✓ added"
        if result.get("audioError"):
            label = "✓ added · no audio"
            tip += "  Audio unavailable: " + result["audioError"]
        elif result.get("audioSource"):
            tip += "  Audio: " + result["audioSource"]
        self._set_anki_state(self._anki_buttons[index], "added", label, tip)

    @Slot(int, int, str, bool)
    def anki_failed(self, ticket: int, index: int, message: str, duplicate: bool) -> None:
        if ticket != self._anki_ticket or index >= len(self._anki_buttons):
            return
        button = self._anki_buttons[index]
        if duplicate:
            self._set_anki_state(button, "duplicate", "✓ in deck", self._browse_tip("Already in"))
        else:
            self._set_anki_state(button, "error", "✕ Anki", message)

    @Slot(int, str)
    def anki_unreachable(self, ticket: int, message: str) -> None:
        """Anki is not running. Say so on the buttons and leave the reading alone.

        Not routed to set_error: the recognised text is perfectly good, and replacing the status
        line with a connection complaint would read as though the snip had failed.
        """
        if ticket != self._anki_ticket:
            return
        for button in self._anki_buttons:
            self._set_anki_state(button, "error", "✕ Anki", message)

    # --- editing -----------------------------------------------------------------------

    def current_line(self) -> str:
        """The line the cursor is on -- the one the definitions below describe."""
        text = self._log.textCursor().block().text().strip()
        if text:
            return text
        # Cursor parked on a blank line: fall back to the newest real one, which is what somebody
        # watching a stream almost always means.
        for line in reversed(self._log.toPlainText().splitlines()):
            if line.strip():
                return line.strip()
        return ""

    def set_line(self, text: str) -> None:
        """Replace the transcript. A fresh snip is a fresh context."""
        self._log.blockSignals(True)
        self._log.setPlainText(text or "")
        self._log.blockSignals(False)
        self._move_to_end()
        self._fit_log()

    def append_line(self, text: str) -> None:
        """Add a line to the transcript, for a watched region."""
        if not text:
            return
        existing = self._log.toPlainText()
        if existing.strip():
            # Oldest first out. Done before the comparison below so the newest line is still the
            # one being compared against.
            kept = existing.splitlines()
            if len(kept) >= TRANSCRIPT_MAX_LINES:
                existing = "\n".join(kept[-(TRANSCRIPT_MAX_LINES - 1) :])
            # Never repeat the previous line. The engine already dedupes by text, but a region
            # re-pinned mid-stream can re-announce what is still on screen.
            if existing.splitlines()[-1].strip() == text.strip():
                return
            text = existing.rstrip("\n") + "\n" + text

        # Only follow the tail if the view was already at the tail. Somebody scrolled up is
        # reading an earlier line, and yanking them back down would undo that.
        bar = self._log.verticalScrollBar()
        was_at_end = bar.value() >= bar.maximum() - 2

        self._log.blockSignals(True)
        self._log.setPlainText(text)
        self._log.blockSignals(False)
        self._fit_log()
        if was_at_end:
            self._move_to_end()

    def _move_to_end(self) -> None:
        cursor = self._log.textCursor()
        cursor.movePosition(QTextCursor.End)
        self._log.setTextCursor(cursor)
        bar = self._log.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _commit(self) -> None:
        text = self.current_line()
        if text:
            self.edited.emit(text)

    def _fit_log(self) -> None:
        """Grow with the transcript, up to a cap, then scroll.

        Taller floor than a single line had: a transcript that shows one line at a time is just a
        worse version of the box it replaced.
        """
        doc = self._log.document()
        doc.setTextWidth(self._log.viewport().width())
        height = int(doc.size().height()) + 14
        self._log.setFixedHeight(max(TRANSCRIPT_MIN_HEIGHT, min(height, TRANSCRIPT_MAX_HEIGHT)))

    def _fit_chips(self, row_height: int) -> None:
        """Grow with the rows, up to CHIP_ROWS_SHOWN, then scroll. The chips' _fit_log.

        Set outright rather than left to sizeHint, because QScrollArea caches the size of the
        widget inside it and only reconsiders when that widget is resized -- which is the wrong
        way round here, since the widget's height is what the scroll area is being asked to
        decide. Left to itself it settled on the height of the first reading and kept it for
        every one after.

        `row_height` comes from a chip rather than from a constant: the chips are sized by the
        stylesheet's font, and a display scaling that font would turn a pixel count written down
        here into either a clipped row or an empty band under the last one.
        """
        width = self._chip_scroll.viewport().width()
        if width <= 0:  # before the first layout; the card's width is known regardless
            width = WINDOW_WIDTH - 2 - 2 * BODY_MARGIN  # less the card's border and inset
        rows = CHIP_ROWS_SHOWN
        cap = rows * row_height + (rows - 1) * CHIP_SPACING
        self._chip_scroll.setFixedHeight(min(self._chips.heightForWidth(width), cap))

    def dismiss(self) -> None:
        """Close on purpose. Stops a watch, unlike hide()."""
        self.hide()
        self._invalidate_translation()
        self.closed.emit()

    # --- housekeeping ------------------------------------------------------------------

    def _clear(self) -> None:
        self._clear_chips()
        self._translation_line = ""
        self._invalidate_translation()
        self._translation.clear()
        self._translation_retry.hide()

    def _clear_chips(self) -> None:
        # Back to nothing, not to whatever the last reading needed. The strip's height is set
        # outright by _fit_chips, so without this a four-row sentence leaves a four-row gap under
        # "reading…" while the next snip is recognised, and a one-word result under a stripe of
        # empty card.
        self._chip_scroll.setFixedHeight(0)
        self._clear_layout(self._chips)
        self._clear_layout(self._tabs)
        self._clear_layout(self._entry)

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def set_region_colour(self, colour: str | None) -> None:
        """Mark this window as belonging to a watched region, or to none.

        `colour` matches the frame drawn around the region on screen, so a reading identifies its
        source without a caption. None hides the bar, which is the ordinary-snip case.
        """
        if colour is None:
            self._region_bar.hide()
            return
        self._region_bar.setStyleSheet(f"#regionBar {{ background: {colour}; }}")
        self._region_bar.show()

    def set_error(self, message: str) -> None:
        self._status.setText(tr(message))

    # --- window chrome, since there is none ---------------------------------------------

    def _retry(self) -> None:
        self._invalidate_translation()
        self.retry.emit()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._keep_actions_in_corner()

    def _keep_actions_in_corner(self) -> None:
        size = self._actions.sizeHint()
        self._actions.setGeometry(
            self.width() - size.width() - ACTIONS_INSET, ACTIONS_INSET, size.width(), size.height()
        )
        self._actions.raise_()

    def mousePressEvent(self, event):  # noqa: N802
        """Start a drag. A frameless window has no title bar to grab, so the whole card is one."""
        if event.button() == Qt.LeftButton:
            self._drag_from = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802
        if event.buttons() & Qt.LeftButton and getattr(self, "_drag_from", None) is not None:
            self.move(event.globalPosition().toPoint() - self._drag_from)
            event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._drag_from = None
        event.accept()
