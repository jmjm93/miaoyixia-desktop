"""Selection, retry and service routing across independent region windows."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from PIL import Image
from PySide6.QtCore import QObject
from app.main import App
from app.region_area import RegionArea
from app.region import RegionMode
from app.window import MainWindow
from app.worker import Reading
from core.config import load


class RegionApp(App):
    def __init__(self, qt, config):
        QObject.__init__(self)
        self.qt, self.config = qt, config
        self.language = self._next_language = "zh"
        self.user_language = "en"
        self.regions = []
        self._next_region_id = 0
        self._snip_pending = self._pin_next = False
        self._reframe_region_id = None
        self._windows_to_restore = []
        self._paused_regions = []
        self.overlay = self.frame = None
        self.window = MainWindow("ctrl+space", "ctrl+w", "#FFB020")
        self.engine, self.tray = Mock(), Mock()
        self._counts = {"snip": 0, "watch": 0, "edit": 0}


@pytest.fixture
def region_app(qt_application, tmp_path, monkeypatch):
    app = RegionApp(qt_application, load(tmp_path / "config.json"))
    monkeypatch.setattr("app.main.QTimer.singleShot", lambda ms, callback: None)
    yield app
    for region in list(app.regions):
        app._on_result_closed(region)
    app.window.close()
    qt_application.processEvents()


def create(app, active=True):
    region = app._create_new_region(RegionArea(10, 20, 120, 60))
    region._watch_active = active
    region._mode = RegionMode.MANUAL
    region.result.show()
    if active:
        region.border.show_over(region.rectangle)
    return region


def test_hide_all_and_cancel_preserves_visibility(region_app):
    app = region_app
    first, second = create(app), create(app)
    second.result.hide()
    app.window.show()
    app.start_snip()
    assert all(not w.isVisible() for r in app.regions for w in (r.result, r.border))
    assert not app.window.isVisible()
    app.pin_region()
    assert not app._pin_next
    app._on_cancelled()
    assert first.result.isVisible() and not second.result.isVisible()
    assert first.border.isVisible() and second.border.isVisible()
    assert first._watch_active and second._watch_active
    assert app.window.isVisible()


@pytest.mark.parametrize("overlay_failure", [False, True])
def test_failure_restores_regions(region_app, monkeypatch, overlay_failure):
    app = region_app
    first, second = create(app), create(app)
    grab, overlay = Mock(return_value=object()), Mock()
    if overlay_failure:
        overlay.start.side_effect = RuntimeError("overlay failed")
    else:
        grab.side_effect = RuntimeError("capture failed")
    monkeypatch.setattr("app.main.capture.grab", grab)
    monkeypatch.setattr("app.main.SnipOverlay", Mock(return_value=overlay))
    app._on_retry(first.id)
    app._begin_snip()
    assert app.overlay is None and not app._snip_pending
    assert app._reframe_region_id is None
    assert first.result.isVisible() and second.result.isVisible()
    assert first.border.isVisible() and second.border.isVisible()


@pytest.mark.parametrize("mode", [RegionMode.MANUAL, RegionMode.AUTOMATIC])
def test_repeated_retry_preserves_both_regions(region_app, mode):
    app = region_app
    first, second = create(app), create(app)
    first._mode = mode
    first.watcher.start = Mock()
    for x in (30, 50):
        app._on_retry(first.id)
        app.frame = Mock()
        app.frame.crop.return_value = Image.new("RGB", (120, 60), "white")
        app._snip_pending = False
        app._on_chosen(SimpleNamespace(rect=RegionArea(x, 20, 120, 60)))
        assert app.regions == [first, second]
        assert first.rectangle.x == x
        assert first._watch_active and second._watch_active
        assert first.border.isVisible() and second.border.isVisible()
        assert second.result.isVisible()
    assert first.watcher.start.call_count == (2 if mode == RegionMode.AUTOMATIC else 0)


def test_new_capture_keeps_existing_region(region_app):
    app = region_app
    first = create(app)
    app.pin_region()
    app.frame = Mock()
    app.frame.crop.return_value = Image.new("RGB", (120, 60), "white")
    app._snip_pending = False
    app._on_chosen(SimpleNamespace(rect=RegionArea(50, 50, 120, 60)))
    second = app.regions[1]
    assert first.id != second.id and first.colour != second.colour
    assert first._watch_active and second._watch_active
    assert first.result.isVisible() and second.result.isVisible()


def test_readings_and_close_are_isolated(region_app):
    app = region_app
    first, second = create(app), create(app)
    first.result.show_reading, second.result.show_reading = Mock(), Mock()
    reading = Reading("你好", [], "horizontal", False, (), 1, 1,
                      session=second._watch_session, region_id=second.id)
    app._on_reading(reading)
    second.result.show_reading.assert_called_once_with(reading)
    first.result.show_reading.assert_not_called()
    app._on_result_closed(first)
    assert app.regions == [second] and second._watch_active
    app._on_reading(Reading("old", [], "", False, (), 1, 1, region_id=first.id))
    app._on_reading(Reading("stale", [], "", False, (), 1, 1, region_id=second.id, session=-1))
    assert second.result.show_reading.call_count == 1


def test_services_and_languages_are_isolated(region_app):
    app = region_app
    first = create(app)
    app._next_language = "ja"
    second = create(app)
    first.anki.inspect, second.anki.inspect = Mock(), Mock()
    first.translation.translate, second.translation.translate = Mock(), Mock()
    first.result._translation_enabled = second.result._translation_enabled = True
    first.result.anki_inspect.emit(1, [])
    second.result.anki_inspect.emit(1, [])
    first.result.translation_requested.emit(1, "你好")
    second.result.translation_requested.emit(1, "日本語")
    assert first.anki.inspect.call_count == second.anki.inspect.call_count == 1
    first.translation.translate.assert_called_once_with(1, "你好", "en")
    second.translation.translate.assert_called_once_with(1, "日本語", "en")
    assert first.language == "zh" and second.language == "ja"


def test_app_startup_and_shutdown_with_multiple_regions(qt_application, tmp_path, monkeypatch):
    config = load(tmp_path / "config.json")
    monkeypatch.setattr("app.main.app_config.load", lambda: config)
    monkeypatch.setattr("app.main.app_config.write_defaults", lambda: False)
    monkeypatch.setattr("app.main.GlobalHotkey.register", lambda self: None)
    monkeypatch.setattr("app.main.GlobalHotkey.unregister", lambda self: None)
    monkeypatch.setattr("app.main.EngineThread", Mock(return_value=Mock()))
    app = App(qt_application)
    try:
        first, second = create(app), create(app)
        assert first.id != second.id
        app.quit()
        assert app.regions == []
        app.engine.stop.assert_called_once()
    finally:
        app._health_timer.stop()
        app._config_timer.stop()
        app.tray.hide()
        app.window.close()
