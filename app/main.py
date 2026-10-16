"""瞄一下 — read the Chinese on your screen.

    python -m app.main

Wiring only. The interesting parts live next door: capture.py freezes the screen, overlay.py takes
the selection, worker.py recognises and looks up, result.py shows it.

The snip flow, in order, because the order is the design:

    hotkey -> freeze the whole desktop -> show the overlay over that still -> drag -> crop the
    still -> show the capture immediately -> recognise on the worker thread -> show the reading

Showing the capture *before* the reading is deliberate, and inherited: the extension's result
window exists in all three states because "when the result comes back wrong, seeing what was
actually captured is what tells the user to zoom in and snip again".
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QFileSystemWatcher, QObject, Qt, QTimer, Slot  # noqa: E402
from PySide6.QtGui import QAction, QIcon, QPainter, QPixmap  # noqa: E402
from PySide6.QtNetwork import QLocalServer, QLocalSocket  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon  # noqa: E402

from app import capture  # noqa: E402
from app.anki import AnkiThread  # noqa: E402
from app.hotkey import GlobalHotkey, HotkeyError  # noqa: E402
from app.overlay import SnipOverlay  # noqa: E402
from app.result import ResultWindow  # noqa: E402
from app.region_border import REGION_COLOURS, RegionBorder  # noqa: E402
from app.watcher import WatcherThread  # noqa: E402
from app import health  # noqa: E402
from app.window import MainWindow, app_icon  # noqa: E402
from app.worker import EngineThread  # noqa: E402
from app.translation import TranslationThread  # noqa: E402
from app.options import OptionsDialog  # noqa: E402
from core.languages import LANGUAGES, validate  # noqa: E402
from core.watch_text import dialogue_key  # noqa: E402
from app.i18n import tr, localize, set_language as set_ui_language  # noqa: E402
from core import config as app_config  # noqa: E402

HOTKEY = "ctrl+shift+space"
#: Pin the next selection as a watched region instead of reading it once.
WATCH_HOTKEY = "ctrl+shift+w"


class App(QObject):
    """The wiring, and a QObject on purpose.

    Being a QObject is load-bearing, not decoration. Qt chooses a signal's connection type from
    the *receiver's* thread affinity: a slot on a QObject living in another thread gets a queued
    connection, which is what marshals the call back onto that thread. A plain Python callable has
    no affinity to inspect, so PySide6 connects it directly and runs it on whichever thread
    emitted -- here the recogniser thread, touching widgets, which Windows answers with an access
    violation and no Python traceback.

    The @Slot decorators below are part of the same story: they only mean anything on a QObject.
    """

    def __init__(self, qt: QApplication, language: str = "zh"):
        super().__init__()
        self.language = validate(language)
        self._next_language = self.language
        self.qt = qt
        self.overlay: SnipOverlay | None = None
        self.frame: capture.Frame | None = None
        self.region: tuple[int, int, int, int] | None = None

        self.result = ResultWindow(self.language)
        self.result.edited.connect(self._on_edited)
        self.result.retry.connect(self._on_retry)
        self.result.closed.connect(self._on_result_closed)

        # Settings, such as they are: one JSON file beside the app, written out with the
        # defaults the first time so there is something to edit.
        self.config = app_config.load()
        self.user_language = self.config.session.user_language
        set_ui_language(self.user_language)
        if app_config.write_defaults():
            log(f"wrote default config to {self.config.path}")
        if self.config.error:
            # Not fatal: the defaults are already in force. But silently ignoring a file the user
            # edited is how a typo becomes an hour of confusion.
            log(f"config ignored, using defaults — {self.config.error}")

        self.anki = AnkiThread()
        self.anki.anki.inspected.connect(self.result.apply_anki_states)
        self.anki.anki.added.connect(self.result.anki_added)
        self.anki.anki.failed.connect(self.result.anki_failed)
        self.anki.anki.unreachable.connect(self.result.anki_unreachable)
        self.result.anki_inspect.connect(self._on_anki_inspect)
        self.result.anki_add.connect(self._on_anki_add)
        self.result.anki_browse.connect(self._on_anki_browse)
        anki_config = self.config.anki_for(self.language)
        self.result.set_anki_enabled(anki_config.enabled, anki_config.deck)

        self.translation = TranslationThread("ja" if self.language == "ja" else "zh-CN")
        self.translation.worker.completed.connect(self.result.apply_translation)
        self.result.translation_requested.connect(self._on_translation_requested)
        self.result.translation_cancelled.connect(self.translation.cancel_pending)
        self.result.set_translation_enabled(self.config.translation.enabled,
                                            self._translation_target())

        # Watched, not merely read once. Without this the only way to apply an edit is to quit
        # from the tray and launch again -- and launching again while the old copy is alive is a
        # no-op by design (see _claim_single_instance), so the obvious gesture, double-clicking
        # the shortcut, silently changes nothing. Turning Anki on for the first time is exactly
        # when someone edits this file, and exactly when that trap costs the most.
        self._setup_config_watcher()

        self.engine = EngineThread(self.language)
        self.engine.set_user_language(self.user_language)
        self.engine.set_ignored_suffixes(self.config.watch.ignored_suffixes)
        self.engine.engine.read_done.connect(self._on_reading)
        self.engine.engine.lookup_done.connect(self._on_reading)
        self.engine.engine.failed.connect(self._on_failed)
        self.engine.engine.warmed.connect(self._on_warmed)
        self.engine.engine.watch_failed.connect(self._on_watch_failed)

        #: True while the next selection should be pinned rather than read once.
        self._pin_next = False
        #: The last line shown from a watched region. The authority on whether anything changed --
        #: see watcher.py for why no pixel-level gate can answer that question.
        self._watched_line: str | None = None
        self._watch_session = 0
        self._watch_active = False
        self._region_mode = self.config.watch.mode
        self.result.mode_changed.connect(self.set_region_mode)
        self.result.rescan_requested.connect(self.rescan_region)
        self.result.set_region_mode(self._region_mode, False, self.config.watch.rescan_hotkey)

        self.watcher = WatcherThread()
        self.watcher.watcher.caught_session.connect(self._on_watch_frame)
        self.watcher.watcher.state_session.connect(self._on_watch_state)

        # The visible half of watching: a coloured frame on screen, and the same colour on the
        # result window. One region for now, so one colour.
        self.region_colour = REGION_COLOURS[0]
        self.border = RegionBorder(self.region_colour)

        self.window = MainWindow(HOTKEY, WATCH_HOTKEY, self.border.colour, self.language)
        self.window.snip_requested.connect(self.start_snip)
        self.window.watch_toggled.connect(self.toggle_watch)
        self.window.quit_requested.connect(self.quit)
        self.window.options_requested.connect(self.show_options)
        self.window.set_ready(False)

        self.tray = QSystemTrayIcon(app_icon())
        self.tray.setToolTip(f"瞄一下 — starting…  ({HOTKEY})")
        menu = QMenu()
        snip_action = QAction(f"Snip\t{HOTKEY}", menu)
        snip_action.triggered.connect(self.start_snip)
        self._watch_action = QAction(f"Watch a region	{WATCH_HOTKEY}", menu)
        self._watch_action.triggered.connect(self.toggle_watch)
        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(snip_action)
        menu.addAction(self._watch_action)
        options_action = QAction("Options", menu)
        options_action.triggered.connect(self.show_options)
        menu.addAction(options_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        show_action = QAction("Show 瞄一下", menu)
        show_action.triggered.connect(self.show_window)
        menu.insertAction(snip_action, show_action)
        menu.insertSeparator(snip_action)
        # Clicking the tray icon opens the window rather than snipping: the window is now the
        # discoverable route, and a stray click should not dim the whole screen.
        self.tray.activated.connect(
            lambda reason: self.show_window() if reason == QSystemTrayIcon.Trigger else None
        )
        self.tray.show()
        localize(self.window)
        localize(self.result)
        self._translate_tray()

        self.hotkeys: list[GlobalHotkey] = []
        for spec, slot in ((HOTKEY, self.start_snip), (WATCH_HOTKEY, self.toggle_watch),
                           (self.config.watch.rescan_hotkey, self.rescan_region)):
            hotkey = GlobalHotkey(spec)
            hotkey.pressed.connect(slot)
            try:
                hotkey.register()
            except HotkeyError as exc:
                # Not fatal: the tray menu offers both, so the app stays usable without them.
                self.tray.showMessage("瞄一下", f"{exc}\nUse the tray icon instead.", app_icon(), 8000)
            self.qt.installNativeEventFilter(hotkey)
            self.hotkeys.append(hotkey)
        self._rescan_hotkey = self.hotkeys[-1]

        # --- diagnostics ---------------------------------------------------------------
        # How much work has happened, so a health line says what the process has been doing and
        # not merely what it is holding. A leak per watch tick and a leak per snip look identical
        # in a memory figure alone, and completely different against these.
        self._counts = {"snip": 0, "watch": 0, "edit": 0}
        self._first_sample = health.sample()
        log(f"baseline {self._first_sample.line()}")

        self._health_timer = QTimer(self)
        self._health_timer.timeout.connect(self._log_health)
        self._health_timer.start(max(5, self.config.diagnostics.health_seconds) * 1000)

        # Warm on the worker thread as soon as the loop is running, so the first snip of the
        # session does not pay 1.3s for the dictionary and the ONNX graph setup.
        QTimer.singleShot(0, self.engine.warm)

    @Slot()
    def _log_health(self) -> None:
        latest = health.sample()
        work = "  ".join(f"{name} {count}" for name, count in self._counts.items())
        log(f"{latest.line()}  [{work}]  {health.growth(self._first_sample, latest)}")
        if latest.gdi_alarming:
            # Worth saying loudly and before the fact: past Windows' 10,000 GDI ceiling object
            # creation simply fails, and whatever assumed it succeeded faults. That is the shape
            # of the crash this instrumentation was added for.
            log(f"WARNING gdi objects {latest.gdi} approaching the {health.GDI_LIMIT} limit")

    # --- the snip flow ------------------------------------------------------------------

    @Slot()
    def show_options(self) -> None:
        dialog = OptionsDialog(self._next_language, self.window, self.user_language)
        localize(dialog)
        if dialog.exec() == OptionsDialog.DialogCode.Accepted:
            self.set_default_language(dialog.language)
            self.set_user_language(dialog.user_language)
        dialog.deleteLater()

    def _translate_tray(self):
        for action in self.tray.contextMenu().actions():
            source = action.property("originalText") or action.text()
            action.setProperty("originalText", source)
            action.setText(tr(source))

    def set_user_language(self, language):
        self.user_language = language
        set_ui_language(language)
        self.engine.set_user_language(language)
        localize(self.window)
        localize(self.result)
        self._translate_tray()
        self.result.set_translation_enabled(self.config.translation.enabled, self._translation_target())
        if self.result._translation_line:
            self.engine.refresh_locale(self.result._translation_line)
        if not app_config.remember_language(self._next_language, self.config.path, language):
            log("could not save user language")

    def _translation_target(self):
        return "es" if getattr(self, "user_language", "en") == "es" else "en"

    def set_default_language(self, language: str) -> None:
        self._next_language = validate(language)
        self.window.set_language(language)
        if not app_config.remember_language(language, self.config.path):
            log("could not save the preferred language; applies until the app exits")

    def _apply_capture_language(self) -> None:
        if self.language == self._next_language:
            return
        self.language = self._next_language
        self.engine.set_language(self.language)
        self.translation.set_language(self.language)
        self.result.set_language(self.language)
        anki_config = self.config.anki_for(self.language)
        self.result.set_anki_enabled(anki_config.enabled, anki_config.deck)

    @Slot()
    def start_snip(self) -> None:
        if self.overlay is not None:
            return  # already framing
        self._stop_watch()

        # Freeze first, then show the overlay over that still. The reverse order would put the
        # overlay in its own capture, and would let a game move under a drawn selection.
        # The border sits over the very region being re-framed, so it would otherwise be
        # baked into the still. Hidden for the grab and restored by _on_watch_state.
        border_was_visible = self.border.isVisible()
        if border_was_visible:
            self.border.hide()
            self.qt.processEvents()

        self.frame = capture.grab()
        if border_was_visible and self.region:
            self.border.show_over(self.region)

        self.overlay = SnipOverlay(self.frame)
        self.overlay.chosen.connect(self._on_chosen)
        self.overlay.cancelled.connect(self._on_cancelled)
        self.overlay.start()

    @Slot()
    def pin_region(self) -> None:
        """Snip, then keep watching whatever was framed."""
        self._pin_next = True
        self.start_snip()

    @Slot(object)
    def _on_chosen(self, selection) -> None:
        self.overlay = None
        self._apply_capture_language()
        self.region = selection.rect

        crop = self.frame.crop(selection.rect)
        if not self._pin_next:
            self.result.set_region_colour(None)
        # On screen straight away, before anything has been recognised.
        self.result.show_capture(crop, selection.rect)
        self.engine.read(crop, None)

        if self._pin_next:
            self._pin_next = False
            self._watched_line = None
            self._watch_session += 1
            self._watch_active = True
            self.engine.set_watch_session(self._watch_session)
            if self._region_mode == "automatic":
                self.watcher.start(selection.rect, session=self._watch_session)
            else:
                self._on_watch_state(self._watch_session, True)

    @Slot(int, object)
    def _on_watch_frame(self, session: int, image) -> None:
        """Read only frames belonging to the current region."""
        if self._watch_active and session == self._watch_session and self._region_mode == "automatic":
            self.engine.read_watch(image, session, self.region)

    @Slot()
    def rescan_region(self) -> None:
        if not self._watch_active or not self.region or self.overlay is not None:
            return
        try:
            image = capture.grab_region(self.region)
        except Exception as exc:
            self._on_failed(f"capture failed: {exc}")
            return
        self.engine.read_watch(image, self._watch_session, self.region)

    @Slot(str)
    def set_region_mode(self, mode: str) -> None:
        if mode == self._region_mode:
            return
        self._region_mode = mode
        if self._watch_active:
            self.watcher.stop()
            self._watch_session += 1
            self.engine.set_watch_session(self._watch_session)
            if mode == "automatic":
                self.watcher.start(self.region, session=self._watch_session)
            self._on_watch_state(self._watch_session, True)
        else:
            self.result.set_region_mode(mode, False, self.config.watch.rescan_hotkey)

    def _stop_watch(self) -> None:
        self._watch_active = False
        self._watch_session += 1
        self.engine.set_watch_session(self._watch_session)
        self.watcher.stop()
        self._on_watch_state(self._watch_session, False)

    @Slot(int, str)
    def _on_watch_failed(self, session: int, message: str) -> None:
        if self._watch_active and session == self._watch_session:
            self._on_failed(message)

    @Slot()
    def show_window(self) -> None:
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    @Slot(int, bool)
    def _on_watch_state(self, session: int, watching: bool) -> None:
        if session != self._watch_session:
            return
        if watching and not self._watch_active:
            return
        if not watching and self._watch_active:
            self._watch_active = False
            self._watch_session += 1
            self.engine.set_watch_session(self._watch_session)
        self._watch_action.setText(tr("Stop watching" if watching else f"Watch a region\t{WATCH_HOTKEY}"))
        self.tray.setToolTip(f"瞄一下 — {'watching' if watching else 'ready'}  ({HOTKEY})")
        self.window.set_watching(watching, self.region if watching else None)
        self.result.set_region_mode(self._region_mode, watching, self.config.watch.rescan_hotkey)
        if watching and self._region_mode == "manual":
            self.window._status.setText(tr("Manual region"))
            self.window._status_hint.setText(tr(f"Rescan with the region button or {self.config.watch.rescan_hotkey}"))
            self.tray.setToolTip("瞄一下 — manual region")

        if watching and self.region:
            self.border.show_over(self.region)
            self.result.set_region_colour(self.region_colour)
        else:
            self.border.hide()
            self.result.set_region_colour(None)

    @Slot()
    def toggle_watch(self) -> None:
        if self._watch_active:
            self._stop_watch()
        else:
            self.pin_region()

    @Slot()
    def _on_cancelled(self) -> None:
        self.overlay = None
        self._pin_next = False

    @Slot()
    def _on_result_closed(self) -> None:
        """Closing the window ends the watch it was showing.

        The window IS the watched region's output, so leaving the watcher running behind a closed
        window would burn CPU and hold a frame on screen with nothing to show for it. Closing is
        the natural "I am done with this region" gesture.
        """
        self._stop_watch()

    @Slot()
    def _on_retry(self) -> None:
        """Reframe. Deferred by a beat, so the window is really gone before the screen freezes.

        hide() only queues the compositor work; grabbing immediately would capture the result
        window sitting on top of the very thing the user is trying to re-snip.
        """
        QTimer.singleShot(120, self.start_snip)

    @Slot(object)
    def _on_reading(self, reading) -> None:
        if getattr(reading, "user_language", "") and reading.user_language != getattr(self, "user_language", "en"):
            return
        if getattr(reading, "language", "") and reading.language != self.language:
            return  # an earlier capture finished while a new language was being selected
        if reading.source == "locale":
            self.result.set_tokens(reading.tokens, preserve=True)
            return
        self._counts[reading.source if reading.source in self._counts else "edit"] += 1
        if reading.source == "watch":
            if not self._watch_active or reading.session != self._watch_session:
                return
            # The text is the authority on whether anything happened. The cheap pixel gate in the
            # watcher can only prove a region untouched, never that it changed -- so a lighting
            # shift behind a translucent panel gets this far, and is stopped here by a text
            # comparison. Trailing dialogue advance cursors do not reset the selected word.
            if dialogue_key(reading.line) == dialogue_key(self._watched_line):
                return
            self._watched_line = reading.line
            if not reading.line:
                return  # the box emptied between lines; leave the last reading up

            # Different is not the same as Chinese. The comparison above only proves the region
            # says something new, so an English subtitle, a clock ticking over, or a textured
            # panel the whole-crop fallback guessed at all get this far -- and each would replace
            # a perfectly good reading with nothing worth reading. The last good line stays up
            # instead, and _watched_line is still advanced so the same rejected text is not
            # re-examined on every tick.
            if not self.config.watch.accepts(reading.line, self.language):
                return

            # Neither focus nor position moves: the user is playing a game, and a window that
            # grabbed focus or hopped about on every line of dialogue would be worse than useless.
            self.result.show_capture(
                reading.image, reading.region, activate=False, reposition=False
            )
            self.window.set_reading(reading.line)
            self.result.show_reading(reading, append=True)
            return

        self.window.set_reading(reading.line)
        self.result.show_reading(reading)
        if getattr(self, "_watch_active", False):
            # The initial snip/corrected line already on screen is the watch baseline.
            self._watched_line = reading.line
        if self.region:
            self.result._place(self.region)

    def _setup_config_watcher(self) -> None:
        self._config_watcher = QFileSystemWatcher(self)
        self._config_timer = QTimer(self)
        self._config_timer.setSingleShot(True)
        self._config_timer.setInterval(100)
        self._config_timer.timeout.connect(lambda: self._on_config_changed(""))
        self._config_watcher.fileChanged.connect(lambda _path: self._config_timer.start())
        self._config_watcher.directoryChanged.connect(self._on_config_directory_changed)
        self._watch_config()

    def _watch_config(self) -> None:
        path = str(self.config.path)
        directory = str(self.config.path.parent)
        if directory not in self._config_watcher.directories():
            self._config_watcher.addPath(directory)
        if self.config.path.exists() and path not in self._config_watcher.files():
            self._config_watcher.addPath(path)

    @Slot(str)
    def _on_config_directory_changed(self, _path: str) -> None:
        if str(self.config.path) not in self._config_watcher.files():
            self._config_timer.start()

    @Slot(str)
    def _on_config_changed(self, _path: str) -> None:
        """Re-read config.json when it changes on disk.

        The re-watch is not belt and braces. Editors overwhelmingly save by writing a new file
        and renaming it over the old one, which destroys the inode QFileSystemWatcher is holding
        -- so the first save is seen and every one after it is not, unless the path is added
        back. A brief absence mid-rename is why this tolerates the file not being there yet.
        """
        self._watch_config()
        if not self.config.path.exists():
            return  # wait for recreation rather than applying defaults mid-save
        config = app_config.load(self.config.path)
        if config.error:
            log(f"config ignored, keeping the last good one — {config.error}")
            return

        old_watch = self.config.watch
        old_language = self.config.session.language
        self.config = config
        if hasattr(self, "user_language") and config.session.user_language != self.user_language:
            self.set_user_language(config.session.user_language)
        if hasattr(self, "_next_language") and config.session.language != old_language:
            self._next_language = config.session.language
            self.window.set_language(self._next_language)
        if hasattr(self, "_rescan_hotkey") and config.watch.rescan_hotkey != old_watch.rescan_hotkey:
            previous = self._rescan_hotkey.spec
            self._rescan_hotkey.unregister()
            self._rescan_hotkey.spec = config.watch.rescan_hotkey
            try:
                self._rescan_hotkey.register()
            except HotkeyError as exc:
                log(f"rescan hotkey unavailable: {exc}; keeping {previous}")
                self._rescan_hotkey.spec = previous
                try:
                    self._rescan_hotkey.register()
                except HotkeyError as restore_error:
                    log(str(restore_error))
                self.tray.showMessage("瞄一下", str(exc) + "\nUse the Rescan button.")
        if hasattr(self, "_region_mode"):
            if config.watch.mode != old_watch.mode:
                self.set_region_mode(config.watch.mode)
            self.result.set_region_mode(self._region_mode, self._watch_active,
                                        self._rescan_hotkey.spec)
        self.engine.set_ignored_suffixes(config.watch.ignored_suffixes)
        anki_config = config.anki_for(getattr(self, "language", "zh"))
        self.result.set_anki_enabled(anki_config.enabled, anki_config.deck)
        target = "es" if getattr(self, "user_language", "en") == "es" else "en"
        self.result.set_translation_enabled(config.translation.enabled, target)
        self._health_timer.setInterval(max(5, config.diagnostics.health_seconds) * 1000)
        log(f"config reloaded — anki {'on' if config.anki.enabled else 'off'}")

    @Slot(int, object)
    def _on_anki_inspect(self, ticket: int, cards) -> None:
        self.anki.inspect(ticket, self.config.anki_for(self.language), cards)

    @Slot(int, str)
    def _on_translation_requested(self, ticket: int, text: str) -> None:
        if self.result._translation_enabled:
            self.translation.translate(ticket, text, "es" if getattr(self, "user_language", "en") == "es" else "en")

    @Slot(int, int, object)
    def _on_anki_add(self, ticket: int, index: int, card) -> None:
        self.anki.add(ticket, index, self.config.anki_for(self.language), card)

    @Slot(int, int, object)
    def _on_anki_browse(self, ticket: int, index: int, card) -> None:
        self.anki.browse(ticket, index, self.config.anki_for(self.language), card)

    @Slot(str)
    def _on_edited(self, line: str) -> None:
        self.engine.lookup(line)

    @Slot(float)
    def _on_warmed(self, ms: float) -> None:
        self.tray.setToolTip(f"瞄一下 — ready  ({HOTKEY})")
        self.window.set_ready(True, "Snip text, pin a region, or open Options")
        log(f"ready in {ms:.0f}ms")

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self.result.set_error(message)
        log(f"error: {message}")

    def quit(self) -> None:
        self._log_health()
        log("--- quitting ---")
        for hotkey in self.hotkeys:
            hotkey.unregister()
        self.border.hide()
        self.watcher.shutdown()
        self.engine.stop()
        self.anki.stop()
        self.translation.stop()
        self.qt.quit()


LOG = app_config.CONFIG_PATH.parent / "miaoyixia.log"


_log_handle = None


def log(message: str) -> None:
    """Say something, into the log file as well as stdout.

    Under pythonw there is no console at all, and a launcher may or may not be redirecting
    stdout -- so anything printed only to stdout is liable to vanish. The log file is the one
    place that is always there.

    Stamped, because the log had no times in it at all and the first question asked of a crash
    that happens "after some time" is how long, and after how much work. Faulthandler's own dump
    is unstamped, so the stamped line above it is what dates the crash.
    """
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {message}"
    print(line, flush=True)
    if _log_handle is not None:
        _log_handle.write(line + "\n")


def _install_crash_log() -> None:
    """Leave evidence when something goes wrong.

    Written after a crash that produced nothing at all to look at. PySide6 routes an exception
    raised inside a virtual method -- paintEvent, mousePressEvent -- through sys.excepthook and
    then may take the process down, so without a hook the only symptom is a window that vanishes.
    faulthandler covers the other half: a fault inside Qt or ONNX itself, where there is no Python
    exception to catch.
    """
    import faulthandler
    import traceback

    global _log_handle
    handle = LOG.open("a", encoding="utf-8", buffering=1)
    _log_handle = handle
    # all_threads is the default, but it is the whole value of the dump here and too
    # important to leave implicit: the crash already seen was on a thread with no Python
    # frame, so the only hope of naming it is the state of every *other* thread at that
    # moment.
    faulthandler.enable(file=handle, all_threads=True)

    def hook(kind, value, tb):
        handle.write("\n--- unhandled exception ---\n")
        traceback.print_exception(kind, value, tb, file=handle)
        traceback.print_exception(kind, value, tb, file=sys.stderr)

    sys.excepthook = hook


#: Name of the loopback socket used to notice a second launch.
SINGLE_INSTANCE_KEY = "miaoyixia-desktop"


def _claim_single_instance() -> "QLocalServer | None":
    """Be the only copy running, and make a second launch useful rather than broken.

    Two copies would both try to register the same global hotkeys -- the second fails, since
    RegisterHotKey is exclusive -- and would each hold their own tray icon, recogniser and 200MB
    of dictionary. Worse, launching again is the natural thing to do when the window is hidden and
    you have forgotten it is already running.

    So a second launch connects to the first, tells it to show its window, and exits.
    """
    probe = QLocalSocket()
    probe.connectToServer(SINGLE_INSTANCE_KEY)
    if probe.waitForConnected(300):
        probe.write(b"show")
        probe.flush()
        probe.waitForBytesWritten(300)
        probe.disconnectFromServer()
        return None

    # No listener: either nothing is running, or a previous copy crashed and left the socket
    # behind. Removing a stale name is safe precisely because the connect above just failed.
    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
    server = QLocalServer()
    server.listen(SINGLE_INSTANCE_KEY)
    return server


def main() -> int:
    _install_crash_log()
    log("--- starting ---")
    qt = QApplication(sys.argv)
    qt.setApplicationName("miaoyixia")
    # The tray is the app's real home; closing the result window must not end the session.
    qt.setQuitOnLastWindowClosed(False)

    server = _claim_single_instance()
    if server is None:
        log("already running; asked the live copy to show itself")
        return 0

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "瞄一下", "No system tray is available on this desktop.")
        return 1

    language = app_config.load().session.language
    app = App(qt, language)  # noqa: F841 - held by the event loop
    # A second launch pokes this socket instead of starting a rival copy.
    server.newConnection.connect(app.show_window)
    # Open on launch. The tray still owns the app's lifetime -- closing this window only hides it
    # -- but starting invisible is what made the hotkeys the only way in.
    app.show_window()
    return qt.exec()


if __name__ == "__main__":
    sys.exit(main())
