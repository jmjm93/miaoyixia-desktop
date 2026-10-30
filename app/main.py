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
from app.region_border import RegionBorder  # noqa: E402
from app import health  # noqa: E402
from app.window import MainWindow, app_icon  # noqa: E402
from app.worker import EngineThread  # noqa: E402
from app.translation import TranslationThread  # noqa: E402
from app.options import OptionsDialog  # noqa: E402
from core.languages import validate  # noqa: E402
from core.watch_text import dialogue_key  # noqa: E402
from app.i18n import tr, localize, set_language as set_ui_language  # noqa: E402
from app.region import Region, RegionMode
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
        self.regions: list[Region] = []
        self._next_region_id: int = 0

        self._reframe_region_id: int | None = None
        self._snip_pending = False
        self._windows_to_restore = []
        self._paused_regions = []

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
        self.engine.engine.region_failed.connect(self._on_region_failed)

        #: True while the next selection should be pinned rather than read once.
        self._pin_next = False
        


        self.window = MainWindow(HOTKEY, WATCH_HOTKEY, "#FFB020", self.language)
        self.window.snip_requested.connect(self.start_snip)
        self.window.watch_toggled.connect(self.pin_region)
        self.window.quit_requested.connect(self.quit)
        self.window.options_requested.connect(self.show_options)
        self.window.set_ready(False)

        self.tray = QSystemTrayIcon(app_icon())
        self.tray.setToolTip(f"瞄一下 — starting…  ({HOTKEY})")
        menu = QMenu()
        snip_action = QAction(f"Snip\t{HOTKEY}", menu)
        snip_action.triggered.connect(self.start_snip)
        self._watch_action = QAction(f"Watch a region	{WATCH_HOTKEY}", menu)
        self._watch_action.triggered.connect(self.pin_region)
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
        self._translate_tray()

        self.hotkeys: list[GlobalHotkey] = []
        for spec, slot in ((HOTKEY, self.start_snip), (WATCH_HOTKEY, self.pin_region),
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
        dialog = OptionsDialog(self._next_language, self.window, self.user_language, self.config)
        localize(dialog)
        if dialog.exec() == OptionsDialog.DialogCode.Accepted:
            self._on_config_changed("")
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
        for region in self.regions:
            localize(region.result)
            region.result.set_translation_enabled(self.config.translation.enabled, self._translation_target())
            if region.result._translation_line:
                self.engine.lookup_region(region.result._translation_line, region, "locale")
        self._translate_tray()
        if not app_config.remember_language(self._next_language, self.config.path, language):
            log("could not save user language")

    def _translation_target(self):
        return "es" if getattr(self, "user_language", "en") == "es" else "en"

    def set_default_language(self, language: str) -> None:
        self._next_language = validate(language)
        self.window.set_language(language)
        if not app_config.remember_language(language, self.config.path):
            log("could not save the preferred language; applies until the app exits")

    def _apply_capture_language(self, region):
        region.result.set_language(region.language)
        config = self.config.anki_for(region.language)
        region.result.set_anki_enabled(config.enabled, config.deck)

    @Slot()
    def start_snip(self) -> None:
        if self.overlay is not None or self._snip_pending:
            return
        self._snip_pending = True
        windows = [self.window]
        self._paused_regions = []
        for region in self.regions:
            windows.extend((region.result, region.border))
            if region._watch_active:
                self._paused_regions.append(region.id)
                region.watcher.stop()
                region._watch_session += 1
                self.engine.set_watch_session(region._watch_session, region.id)
        self._windows_to_restore = [window for window in windows if window.isVisible()]
        for window in windows:
            window.hide()
        QTimer.singleShot(120, self._begin_snip)

    def _begin_snip(self):
        try:
            self.frame = capture.grab()
            self.overlay = SnipOverlay(self.frame)
            self.overlay.chosen.connect(self._on_chosen)
            self.overlay.cancelled.connect(self._on_cancelled)
            self.overlay.start()
        except Exception as exc:
            if self.overlay is not None:
                self.overlay.hide()
                self.overlay.deleteLater()
            self.frame = None
            self._on_cancelled()
            self._on_failed(f"capture failed: {exc}")
        finally:
            self._snip_pending = False

    def _restore_after_snip(self, selected=None):
        windows, self._windows_to_restore = self._windows_to_restore, []
        live_windows = [self.window] + [w for r in self.regions for w in (r.result, r.border)]
        for window in windows:
            if window in live_windows and (selected is None or window is not selected.result):
                window.setAttribute(Qt.WA_ShowWithoutActivating, True)
                window.show()
        paused, self._paused_regions = self._paused_regions, []
        for region in self.regions:
            if region.id in paused and region._watch_active:
                if region._mode == RegionMode.AUTOMATIC:
                    region.watcher.start(region.rectangle, session=region._watch_session)
                region.border.show_over(region.rectangle)
        self._update_region_status()

    @Slot()
    def pin_region(self):
        if self.overlay is not None or self._snip_pending:
            return
        self._pin_next = True
        self.start_snip()

    @Slot(object)
    def _on_chosen(self, selection):
        reframe_id = self._reframe_region_id
        pin = self._pin_next
        self.overlay = None
        self._reframe_region_id = None
        self._pin_next = False
        region = self._find_region(reframe_id) if reframe_id is not None else self._create_new_region(selection.rect)
        if region is None:
            self._restore_after_snip()
            return
        region.rectangle = selection.rect
        region._watched_line = None
        region._watch_session += 1
        if reframe_id is None:
            region._watch_active = pin
        self.engine.set_watch_session(region._watch_session, region.id)
        try:
            crop = self.frame.crop(region.rectangle)
            region.result.set_region_colour(region.colour if region._watch_active else None)
            region.result.show_capture(crop, region.rectangle)
            self.engine.read(crop, region)
            region.result.set_region_mode(region._mode, region._watch_active, self.config.watch.rescan_hotkey)
            if region._watch_active:
                region.border.show_over(region.rectangle)
                if region._mode == RegionMode.AUTOMATIC and region.id not in self._paused_regions:
                    region.watcher.start(region.rectangle, session=region._watch_session)
        except Exception as exc:
            region.result.set_error(f"capture failed: {exc}")
        finally:
            self._restore_after_snip(region)

    def _create_new_region(self, rect):
        colours = ("#FFB020", "#3FC7A1", "#FF6B8A", "#7C8CFF")
        used = {r.colour for r in self.regions}
        colour = next((c for c in colours if c not in used), RegionBorder.random_colour())
        region = Region(self._next_region_id, rect, colour, RegionMode(self.config.watch.mode), self._next_language)
        self._next_region_id += 1
        self.regions.append(region)
        self._setup_new_region(region)
        return region

    def _find_region(self, region_id):
        return next((r for r in self.regions if r.id == region_id), None)

    def _update_region_status(self):
        active = [r for r in self.regions if r._watch_active]
        self.window.set_watching(False)
        if active:
            self.window._status.setText(tr("Watching regions") + f": {len(active)}")
        self.tray.setToolTip(f"瞄一下 — {len(active)} regions")

    def _on_watch_frame(self, region, session, image):
        if (not self._snip_pending and self.overlay is None and region in self.regions
                and region._watch_active and session == region._watch_session
                and region._mode == RegionMode.AUTOMATIC):
            self.engine.read_region_watch(image, region)

    def rescan_region(self, region=None):
        if self.overlay is not None or self._snip_pending:
            return
        targets = [region] if isinstance(region, Region) else list(self.regions)
        for target in targets:
            if target not in self.regions or not target._watch_active:
                continue
            try:
                self.engine.read_region_watch(capture.grab_region(target.rectangle), target)
            except Exception as exc:
                target.result.set_error(f"capture failed: {exc}")

    def set_region_mode(self, region, mode):
        if region not in self.regions:
            return
        region._mode = RegionMode(mode)
        region.watcher.stop()
        region._watch_session += 1
        self.engine.set_watch_session(region._watch_session, region.id)
        if region._watch_active and region._mode == RegionMode.AUTOMATIC:
            region.watcher.start(region.rectangle, session=region._watch_session)
        region.result.set_region_mode(region._mode, region._watch_active, self.config.watch.rescan_hotkey)

    def _stop_watch(self, region):
        region._watch_active = False
        region._watch_session += 1
        self.engine.set_watch_session(region._watch_session, region.id)
        region.watcher.stop()
        region.border.hide()
        region.result.set_region_mode(region._mode, False, self.config.watch.rescan_hotkey)
        self._update_region_status()

    @Slot(int, int, str)
    def _on_region_failed(self, region_id, session, message):
        region = self._find_region(region_id)
        if region is not None and region._watch_session == session:
            region.result.set_error(message)
            log(message)

    @Slot()
    def show_window(self) -> None:
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def _on_watch_state(self, region, session, watching):
        if region not in self.regions or session != region._watch_session:
            return
        if not watching:
            if self._snip_pending or self.overlay is not None:
                return
            self._stop_watch(region)
        elif region._watch_active and not self._snip_pending and self.overlay is None:
            region.border.show_over(region.rectangle)
        self._update_region_status()

    @Slot()
    def toggle_watch(self):
        self.pin_region()

    @Slot()
    def _on_cancelled(self):
        self.overlay = None
        self._pin_next = False
        self._reframe_region_id = None
        self._snip_pending = False
        self._restore_after_snip()

    def _on_result_closed(self, region):
        if region not in self.regions:
            return
        self.regions.remove(region)
        self.engine.forget_region(region.id)
        region.watcher.shutdown()
        region.translation.stop()
        region.anki.stop()
        region.border.hide()
        region.border.deleteLater()
        region.result.hide()
        region.result.deleteLater()
        region.deleteLater()
        self._update_region_status()

    @Slot(int)
    def _on_retry(self, region_id):
        if self.overlay is not None or self._snip_pending or self._find_region(region_id) is None:
            return
        self._reframe_region_id = region_id
        self.start_snip()

    @Slot(object)
    @Slot(object, int)
    def _on_reading(self, reading, region_id=None):
        region = self._find_region(reading.region_id if region_id is None else region_id)
        if region is None or reading.session != region._watch_session:
            return
        if reading.language and reading.language != region.language:
            return
        if reading.user_language and reading.user_language != self.user_language:
            return
        if self._snip_pending or self.overlay is not None:
            return
        if reading.source == "locale":
            region.result.set_tokens(reading.tokens, preserve=True)
            return
        self._counts[reading.source if reading.source in self._counts else "edit"] += 1
        if reading.source == "watch":
            if not region._watch_active:
                return
            if dialogue_key(reading.line) == dialogue_key(region._watched_line):
                return
            region._watched_line = reading.line
            if not reading.line or not self.config.watch.accepts(reading.line, region.language):
                return
            region.result.show_capture(reading.image, region.rectangle, activate=False, reposition=False)
            region.result.show_reading(reading, append=True)
        else:
            region.result.show_reading(reading)
            region._watched_line = reading.line
        self.window.set_reading(reading.line)

    def _setup_config_watcher(self) -> None:
        self._config_watcher = QFileSystemWatcher(self)
        self._config_timer = QTimer(self)
        self._config_timer.setSingleShot(True)
        self._config_timer.setInterval(100)
        self._config_timer.timeout.connect(lambda: self._on_config_changed(""))
        self._config_watcher.fileChanged.connect(lambda _path: self._config_timer.start())
        self._config_watcher.directoryChanged.connect(self._on_config_directory_changed)
        self._watch_config()

    def _setup_new_region(self, region):
        region.app = self
        result = region.result
        region.anki = AnkiThread()
        region.translation = TranslationThread("ja" if region.language == "ja" else "zh-CN")
        region.anki.anki.inspected.connect(result.apply_anki_states)
        region.anki.anki.added.connect(result.anki_added)
        region.anki.anki.failed.connect(result.anki_failed)
        region.anki.anki.unreachable.connect(result.anki_unreachable)
        region.translation.worker.completed.connect(result.apply_translation)
        result.edited.connect(self._on_edited)
        result.retry.connect(self._on_retry)
        result.closed.connect(lambda: self._on_result_closed(region))
        result.anki_inspect.connect(lambda ticket, cards: region.anki.inspect(ticket, self.config.anki_for(region.language), cards))
        result.anki_add.connect(lambda ticket, index, card: region.anki.add(ticket, index, self.config.anki_for(region.language), card))
        result.anki_browse.connect(lambda ticket, index, card: region.anki.browse(ticket, index, self.config.anki_for(region.language), card))
        result.translation_requested.connect(lambda ticket, text: self._on_translation_requested(region, ticket, text))
        result.translation_cancelled.connect(region.translation.cancel_pending)
        result.mode_changed.connect(lambda mode: self.set_region_mode(region, mode))
        result.rescan_requested.connect(lambda: self.rescan_region(region))
        result.set_region_mode(region._mode, False, self.config.watch.rescan_hotkey)
        result.set_translation_enabled(self.config.translation.enabled, self._translation_target())
        self._apply_capture_language(region)
        localize(result)
        region.watcher.watcher.caught_session.connect(region.on_frame)
        region.watcher.watcher.state_session.connect(region.on_state)

    def _on_translation_requested(self, region, ticket, text):
        if region in self.regions and region.result._translation_enabled:
            region.translation.translate(ticket, text, self._translation_target())

    def _watch_config(self) -> None:
        path = str(self.config.path)
        directory = str(self.config.path.parent)
        if directory not in self._config_watcher.directories():
            self._config_watcher.addPath(directory)
        if self.config.path.exists() and path not in self._config_watcher.files():
            self._config_watcher.addPath(path)

    @Slot(str)
    def _on_config_directory_changed(self, _path: str) -> None:
        # A directory notification can arrive before Qt removes a deleted or
        # replaced file from files(), especially on Windows. Do not discard that
        # notification based on a watch list that may still describe the old file.
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
        old_config = self.config
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
        self.engine.set_ignored_suffixes(config.watch.ignored_suffixes)
        for region in getattr(self, "regions", []):
            if config.watch.mode != old_watch.mode:
                self.set_region_mode(region, config.watch.mode)
            region.result.set_region_mode(region._mode, region._watch_active, config.watch.rescan_hotkey)
            anki = config.anki_for(region.language)
            region.result.set_anki_enabled(anki.enabled, anki.deck,
                                           refresh=anki != old_config.anki_for(region.language))
            region.result.set_translation_enabled(config.translation.enabled, self._translation_target())
        self._health_timer.setInterval(max(5, config.diagnostics.health_seconds) * 1000)
        log(f"config reloaded — anki {'on' if config.anki.enabled else 'off'}")









    @Slot(str, int)
    def _on_edited(self, line, region_id):
        region = self._find_region(region_id)
        if region is not None:
            self.engine.lookup_region(line, region)

    @Slot(float)
    def _on_warmed(self, ms: float) -> None:
        self.tray.setToolTip(f"瞄一下 — ready  ({HOTKEY})")
        self.window.set_ready(True, "Snip text, pin a region, or open Options")
        log(f"ready in {ms:.0f}ms")

    @Slot(str)
    def _on_failed(self, message):
        self.window._status.setText(message)
        log(f"error: {message}")

    def quit(self):
        self._log_health()
        log("--- quitting ---")
        for hotkey in self.hotkeys:
            hotkey.unregister()
        for region in list(self.regions):
            self._on_result_closed(region)
        self.engine.stop()
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
