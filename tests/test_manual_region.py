from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from PIL import Image
from app.region_area import RegionArea
from app.main import App
from core.config import WatchConfig, load


def fake_app(mode="automatic", active=True):
    app = SimpleNamespace(_region_mode=mode, _watch_active=active, _watch_session=7,
        region=RegionArea(10, 20, 300, 80), overlay=None, watcher=Mock(), engine=Mock(), result=Mock(),
        config=SimpleNamespace(watch=WatchConfig(0.35)), _on_watch_state=Mock(), _on_failed=Mock())
    return app


def test_manual_mode_stops_watcher_and_invalidates_automatic_results():
    app = fake_app()
    App.set_region_mode(app, "manual")
    app.watcher.stop.assert_called_once()
    app.watcher.start.assert_not_called()
    app.engine.set_watch_session.assert_called_once_with(8)
    assert app._watch_active and app._region_mode == "manual"
    image = Image.new("RGB", (8, 8))
    App._on_watch_frame(app, 7, image)
    App._on_watch_frame(app, 8, image)
    app.engine.read_watch.assert_not_called()


def test_returning_to_automatic_restarts_same_region():
    app = fake_app("manual")
    App.set_region_mode(app, "automatic")
    app.watcher.start.assert_called_once_with(app.region, session=8)
    App._on_watch_frame(app, 8, "image")
    app.engine.read_watch.assert_called_once_with("image", 8, app.region)


@pytest.mark.parametrize("active,overlay", [(True, None), (False, None), (True, object())])
def test_manual_rescan_captures_only_on_request(monkeypatch, active, overlay):
    app = fake_app("manual", active)
    app.overlay = overlay
    grab = Mock(return_value="capture")
    monkeypatch.setattr("app.main.capture.grab_region", grab)
    App.rescan_region(app)
    if active and overlay is None:
        grab.assert_called_once_with(app.region)
        app.engine.read_watch.assert_called_once_with("capture", 7, app.region)
    else:
        grab.assert_not_called()


def test_manual_config_and_hotkey_load(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"watch":{"mode":"manual","rescan_hotkey":"alt+r"}}')
    config = load(path)
    assert not config.error
    assert config.watch.mode == "manual"
    assert config.watch.rescan_hotkey == "alt+r"
