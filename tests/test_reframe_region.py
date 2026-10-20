from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.main import App
from app.region import RegionMode
from app.region_area import RegionArea


def make_app(mode, active):
    region = SimpleNamespace(
        id=7, rectangle=RegionArea(10, 20, 300, 80), colour="#ffb020",
        _mode=mode, _watch_active=active, _watch_session=3, _watched_line="old text",
        watcher=Mock(), border=Mock(), result=Mock(),
    )
    app = SimpleNamespace(
        regions=[region], _reframe_region_id=7, _reframe_was_active=active,
        overlay=object(), _pin_next=False, frame=Mock(), engine=Mock(),
        _apply_capture_language=Mock(),
        config=SimpleNamespace(watch=SimpleNamespace(rescan_hotkey="ctrl+shift+r")),
    )
    return app, region


@pytest.mark.parametrize("mode,active", [
    (RegionMode.AUTOMATIC, True), (RegionMode.MANUAL, True),
    (RegionMode.AUTOMATIC, False),
])
def test_chosen_restores_region_state_without_pin_next(mode, active):
    app, region = make_app(mode, active)
    rectangle = RegionArea(100, 200, 400, 90)
    App._on_chosen(app, SimpleNamespace(rect=rectangle))
    assert app.overlay is None
    assert app._reframe_region_id is None
    assert app._reframe_was_active is False
    assert region.rectangle is rectangle
    assert region._watched_line is None
    assert region._watch_session == 4
    assert region._watch_active is active
    region.result.set_region_colour.assert_called_once_with(region.colour)
    region.result.set_region_mode.assert_called_once_with(mode, active, "ctrl+shift+r")
    if active and mode == RegionMode.AUTOMATIC:
        region.watcher.start.assert_called_once_with(rectangle, session=4)
    else:
        region.watcher.start.assert_not_called()
    if active:
        region.border.show_over.assert_called_once_with(rectangle)


def test_start_snip_saves_state_before_pausing_target(monkeypatch):
    app, region = make_app(RegionMode.AUTOMATIC, True)
    other = SimpleNamespace(watcher=Mock(), border=Mock(), id=8)
    app.regions.append(other)
    app.overlay = None
    app._reframe_was_active = False
    app.qt = Mock()
    app._on_chosen = Mock()
    app._on_cancelled = Mock()
    monkeypatch.setattr("app.main.capture.grab", Mock(return_value=app.frame))
    monkeypatch.setattr("app.main.SnipOverlay", Mock())
    App.start_snip(app)
    assert app._reframe_was_active is True
    assert region._watch_active is False
    region.watcher.stop.assert_called_once()
    region.border.hide.assert_called_once()
    other.watcher.stop.assert_not_called()
    other.border.hide.assert_not_called()


def test_cancel_restores_original_rectangle_and_monitoring():
    app, region = make_app(RegionMode.AUTOMATIC, True)
    rectangle = region.rectangle
    region._watch_active = False
    App._on_cancelled(app)
    assert region.rectangle is rectangle
    assert region._watch_active is True
    assert app._reframe_region_id is None
    assert app._reframe_was_active is False
    region.watcher.start.assert_called_once_with(rectangle, session=3)
    region.result.show.assert_called_once()
