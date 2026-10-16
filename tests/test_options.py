import os
from types import SimpleNamespace
from unittest.mock import Mock
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from app.main import App
from app.options import OptionsDialog
from app.worker import EngineThread
from core.config import load


@pytest.fixture(scope="session")
def qt():
    return QApplication.instance() or QApplication([])


def test_options_selects_text_language(qt):
    dialog = OptionsDialog("ja")
    try:
        assert dialog.language == "ja"
        dialog.language_choice.setCurrentIndex(0)
        assert dialog.language == "zh"
        dialog.reject()
        assert dialog.result() == OptionsDialog.DialogCode.Rejected
    finally:
        dialog.deleteLater()
        qt.processEvents()


def test_user_language_selector_is_independent_of_text_language(qt):
    from app.i18n import set_language, localize
    dialog = OptionsDialog("ja", user_language="es")
    try:
        set_language("es")
        localize(dialog)
        assert dialog.user_language == "es" and dialog.language == "ja"
        assert dialog.windowTitle() == "Opciones"
        dialog.user_language_choice.setCurrentIndex(0)
        assert dialog.user_language == "en" and dialog.language == "ja"
        set_language("en")
        localize(dialog)
        assert dialog.windowTitle() == "Options"
    finally:
        set_language("en")
        dialog.deleteLater()
        qt.processEvents()


def test_default_change_preserves_current_region_and_persists(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"session":{"language":"ja"}}')
    app = SimpleNamespace(language="ja", _next_language="ja", config=load(path), window=Mock(),
        engine=Mock(), translation=Mock(), result=Mock(), _watch_active=True)
    App.set_default_language(app, "zh")
    assert app.language == "ja" and app._watch_active
    assert load(path).session.language == "zh"
    app.engine.set_language.assert_not_called()
    app.translation.set_language.assert_not_called()
    app.result.set_language.assert_not_called()
    App._apply_capture_language(app)
    assert app.language == "zh"
    app.engine.set_language.assert_called_once_with("zh")
    app.translation.set_language.assert_called_once_with("zh")
    app.result.set_language.assert_called_once_with("zh")
    app.result.set_anki_enabled.assert_called_once_with(app.config.anki.enabled, app.config.anki.deck)


def test_old_language_result_cannot_replace_new_capture():
    app = SimpleNamespace(language="zh", result=Mock(), window=Mock())
    App._on_reading(app, SimpleNamespace(language="ja"))
    app.result.show_reading.assert_not_called()


def test_worker_language_change_is_queued_before_new_capture(qt, monkeypatch):
    import app.worker as module
    worker = EngineThread("ja")
    calls, readings = [], []
    monkeypatch.setattr(module, "read_line", lambda line, language: calls.append(language) or [])
    worker.engine._engine = lambda: SimpleNamespace(read=lambda *a, **k: SimpleNamespace(
        text="text", orientation="horizontal", undetected=False, scores=(), elapsed_ms=1))
    worker.engine.read_done.connect(readings.append)
    loop = QEventLoop()
    poll, timeout = QTimer(), QTimer()
    poll.timeout.connect(lambda: len(readings) == 2 and loop.quit())
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    try:
        worker.read("first")
        worker.set_language("zh")
        worker.read("second")
        poll.start(10)
        timeout.start(2000)
        loop.exec()
        assert calls == ["ja", "zh"]
        assert [r.language for r in readings] == ["ja", "zh"]
    finally:
        poll.stop()
        timeout.stop()
        worker.stop()
        qt.processEvents()
