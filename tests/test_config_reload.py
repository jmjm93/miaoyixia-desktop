import json
import os
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QObject, QTimer
from PySide6.QtWidgets import QApplication

from app.main import App
from core.config import load


def wait_until(predicate, description):
    loop = QEventLoop()
    poll = QTimer()
    poll.timeout.connect(lambda: predicate() and loop.quit())
    poll.start(10)
    QTimer.singleShot(2000, loop.quit)
    loop.exec()
    assert predicate(), f"Timed out waiting for {description}"


def test_live_config_survives_invalid_edits_deletion_and_atomic_replacement(tmp_path, monkeypatch):
    qt = QApplication.instance() or QApplication([])
    logged = Mock()
    monkeypatch.setattr("app.main.log", logged)
    path = tmp_path / "config.json"
    path.write_text('{"anki": {"enabled": true}}', encoding="utf-8")

    class ConfigApp(App):
        def __init__(self):
            QObject.__init__(self)
            self.config = load(path)
            self.result = Mock()
            self.engine = Mock()
            self._health_timer = QTimer(self)
            self._health_timer.setInterval(60000)
            self._setup_config_watcher()

    app = ConfigApp()
    try:
        original = app.config
        path.write_text('{"watch": {"min_han_fraction": "invalid"}}', encoding="utf-8")
        wait_until(lambda: logged.called, "invalid config to be logged")
        assert app.config is original
        assert "keeping the last good one" in logged.call_args.args[0]
        path.unlink()
        app._on_config_changed(str(path))
        assert app.config is original
        path.write_text(json.dumps({"anki": {"deck": "New Deck"},
                                    "diagnostics": {"health_seconds": 10}}), encoding="utf-8")
        wait_until(lambda: app.config.anki.deck == "New Deck", "recreated config to load")
        assert app._health_timer.interval() == 10000
        replacement = tmp_path / "replacement.json"
        replacement.write_text('{"anki": {"deck": "Replaced Deck"}}', encoding="utf-8")
        replacement.replace(path)
        wait_until(lambda: app.config.anki.deck == "Replaced Deck", "atomic replacement to load")
        path.write_text('{"anki": {"deck": "Third Deck"}}', encoding="utf-8")
        wait_until(lambda: app.config.anki.deck == "Third Deck", "edit after replacement to load")
        assert str(path) in app._config_watcher.files()
    finally:
        app._config_timer.stop()
        app._health_timer.stop()
        app.deleteLater()
        qt.processEvents()


def test_directory_notification_reloads_even_while_file_is_still_registered(tmp_path):
    qt = QApplication.instance() or QApplication([])
    path = tmp_path / "config.json"
    path.write_text('{"anki": {"deck": "Original"}}', encoding="utf-8")
    app = App.__new__(App)
    QObject.__init__(app)
    app.config = load(path)
    app.result = Mock()
    app.engine = Mock()
    app._health_timer = QTimer(app)
    app._setup_config_watcher()
    try:
        # Isolate the directory notification: the file signal may be delayed or
        # coalesced during a save, while files() still contains the config path.
        app._config_watcher.blockSignals(True)
        path.write_text('{"anki": {"deck": "Updated"}}', encoding="utf-8")
        assert str(path) in app._config_watcher.files()
        app._on_config_directory_changed(str(tmp_path))
        wait_until(lambda: app.config.anki.deck == "Updated", "directory-triggered reload")
    finally:
        app._config_timer.stop()
        app._health_timer.stop()
        app.deleteLater()
        qt.processEvents()
