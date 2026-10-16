import json
import os
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QObject, QTimer
from PySide6.QtWidgets import QApplication

from app.main import App
from core.config import load


def wait_until(predicate):
    loop = QEventLoop()
    poll = QTimer()
    poll.timeout.connect(lambda: predicate() and loop.quit())
    poll.start(10)
    QTimer.singleShot(2000, loop.quit)
    loop.exec()
    assert predicate()


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
        wait_until(lambda: logged.called)
        assert app.config is original
        assert "keeping the last good one" in logged.call_args.args[0]
        path.unlink()
        app._on_config_changed(str(path))
        assert app.config is original
        path.write_text(json.dumps({"anki": {"deck": "New Deck"},
                                    "diagnostics": {"health_seconds": 10}}), encoding="utf-8")
        wait_until(lambda: app.config.anki.deck == "New Deck")
        assert app._health_timer.interval() == 10000
        replacement = tmp_path / "replacement.json"
        replacement.write_text('{"anki": {"deck": "Replaced Deck"}}', encoding="utf-8")
        replacement.replace(path)
        wait_until(lambda: app.config.anki.deck == "Replaced Deck")
        path.write_text('{"anki": {"deck": "Third Deck"}}', encoding="utf-8")
        wait_until(lambda: app.config.anki.deck == "Third Deck")
        assert str(path) in app._config_watcher.files()
    finally:
        app._config_timer.stop()
        app._health_timer.stop()
        app.deleteLater()
        qt.processEvents()
