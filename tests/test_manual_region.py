from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from PIL import Image
from app.region_area import RegionArea
from app.main import App
from core.config import WatchConfig, load


def fake_app(mode="automatic", active=True):
    region = SimpleNamespace(id=1, _mode=mode, _watch_active=active, _watch_session=7,
                             rectangle=RegionArea(10, 20, 300, 80), watcher=Mock(), result=Mock())
    app = SimpleNamespace(regions=[region], overlay=None, _snip_pending=False, engine=Mock(),
                          config=SimpleNamespace(watch=WatchConfig(0.35)))
    return app


def test_manual_mode_stops_watcher_and_invalidates_automatic_results():
    app = fake_app()
    App.set_region_mode(app, app.regions[0], "manual")
    app.regions[0].watcher.stop.assert_called_once()
    app.regions[0].watcher.start.assert_not_called()
    app.engine.set_watch_session.assert_called_once_with(8, 1)
    assert app.regions[0]._watch_active and app.regions[0]._mode == "manual"
    image = Image.new("RGB", (8, 8))
    App._on_watch_frame(app, app.regions[0], 7, image)
    App._on_watch_frame(app, app.regions[0], 8, image)
    app.engine.read_region_watch.assert_not_called()


def test_returning_to_automatic_restarts_same_region():
    app = fake_app("manual")
    App.set_region_mode(app, app.regions[0], "automatic")
    app.regions[0].watcher.start.assert_called_once_with(app.regions[0].rectangle, session=8)
    App._on_watch_frame(app, app.regions[0], 8, "image")
    app.engine.read_region_watch.assert_called_once_with("image", app.regions[0])


@pytest.mark.parametrize("active,overlay", [(True, None), (False, None), (True, object())])
def test_manual_rescan_captures_only_on_request(monkeypatch, active, overlay):
    app = fake_app("manual", active)
    app.overlay = overlay
    grab = Mock(return_value="capture")
    monkeypatch.setattr("app.main.capture.grab_region", grab)
    App.rescan_region(app)
    if active and overlay is None:
        grab.assert_called_once_with(app.regions[0].rectangle)
        app.engine.read_region_watch.assert_called_once_with("capture", app.regions[0])
    else:
        grab.assert_not_called()


def test_manual_config_and_hotkey_load(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"watch":{"mode":"manual","rescan_hotkey":"alt+r"}}')
    config = load(path)
    assert not config.error
    assert config.watch.mode == "manual"
    assert config.watch.rescan_hotkey == "alt+r"
