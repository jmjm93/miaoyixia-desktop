"""Selection hides app windows before capture and restores their prior visibility."""
from types import SimpleNamespace, MethodType
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QWidget

from app.main import App


def make_app():
    app = SimpleNamespace(
        window=QWidget(), result=QWidget(), border=QWidget(), overlay=None,
        frame=None, _snip_pending=False, _pin_next=False, _windows_to_restore=[],
        _stop_watch=Mock(), _on_failed=Mock(), _on_chosen=Mock(),
    )
    for name in ("start_snip", "_begin_snip", "_on_cancelled", "pin_region", "_on_retry"):
        setattr(app, name, MethodType(getattr(App, name), app))
    return app


def test_hide_before_deferred_capture_and_restore_only_visible(monkeypatch):
    app = make_app()
    app.window.show()
    app.border.show()
    scheduled = []
    monkeypatch.setattr("app.main.QTimer.singleShot", lambda ms, callback: scheduled.append(callback))
    grab = Mock()
    monkeypatch.setattr("app.main.capture.grab", grab)

    app.start_snip()
    assert not any(w.isVisible() for w in (app.window, app.result, app.border))
    grab.assert_not_called()
    app.start_snip()
    app.pin_region()
    assert len(scheduled) == 1
    assert not app._pin_next
    app._on_cancelled()
    assert app.window.isVisible()
    assert not app.result.isVisible()
    assert not app.border.isVisible()
    app.window.close()


@pytest.mark.parametrize("fail_overlay", [False, True])
def test_capture_or_overlay_failure_restores_windows_and_allows_retry(monkeypatch, fail_overlay):
    app = make_app()
    app.result.show()
    monkeypatch.setattr("app.main.QTimer.singleShot", lambda ms, callback: None)
    grab = Mock(return_value=object())
    overlay = Mock()
    if fail_overlay:
        overlay.start.side_effect = RuntimeError("overlay unavailable")
    else:
        grab.side_effect = RuntimeError("display unavailable")
    monkeypatch.setattr("app.main.capture.grab", grab)
    monkeypatch.setattr("app.main.SnipOverlay", Mock(return_value=overlay))

    app.pin_region()
    app._begin_snip()
    assert app.result.isVisible()
    assert not app.window.isVisible()
    assert app.overlay is None
    assert not app._snip_pending and not app._pin_next
    app._on_failed.assert_called_once()
    app.start_snip()
    assert app._snip_pending
    app.result.close()


@pytest.mark.parametrize("mode", ["automatic", "manual"])
def test_repeated_region_retry_keeps_watch_and_border(monkeypatch, mode):
    app = make_app()
    app._watch_active = True
    app._watch_session = 1
    app._region_mode = mode
    app.result = Mock()
    app.engine = Mock()
    app.watcher = Mock()
    app._apply_capture_language = Mock()
    app._on_chosen = MethodType(App._on_chosen, app)

    def stop_watch():
        app._watch_active = False
        app.border.hide()

    def watch_state(session, watching):
        if watching:
            app.border.show()

    app._stop_watch = stop_watch
    app._on_watch_state = watch_state
    app.watcher.start.side_effect = lambda rect, session: watch_state(session, True)
    monkeypatch.setattr("app.main.QTimer.singleShot", lambda ms, callback: None)

    for rect in ((10, 20, 100, 50), (30, 40, 120, 60)):
        app._on_retry()
        assert app._pin_next
        assert not app.border.isVisible()
        app.frame = Mock()
        app._snip_pending = False
        app._on_chosen(SimpleNamespace(rect=rect))
        assert app._watch_active
        assert app.region == rect
        assert app.border.isVisible()
        assert not app._pin_next
    app.border.close()


def test_ordinary_retry_does_not_pin_region():
    app = SimpleNamespace(_watch_active=False, start_snip=Mock(), pin_region=Mock())
    App._on_retry(app)
    app.start_snip.assert_called_once()
    app.pin_region.assert_not_called()
