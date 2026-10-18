"""Exercise slow OCR on a real QThread, including failures and region replacement."""
import os
import threading
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PySide6.QtCore import QEventLoop, QObject, QTimer, Slot
from PySide6.QtWidgets import QApplication

from app.region_area import RegionArea
from app.worker import EngineThread, Reading


@pytest.mark.parametrize("failure,invalidate", [(False, False), (True, False), (False, True)])
def test_watch_backlog_keeps_only_the_latest_capture(failure, invalidate):
    qt = QApplication.instance() or QApplication([])
    entered, release = threading.Event(), threading.Event()
    calls, readings, errors = [], [], []
    images = [Image.new("RGB", (8, 8), (i, i, i)) for i in range(10)]
    region = RegionArea(1, 2, 8, 8)

    class FakeOCR:
        def read(self, image, orientation=None):
            calls.append(image)
            if len(calls) == 1:
                entered.set()
                if not release.wait(3):
                    raise RuntimeError("test timed out")
                if failure:
                    raise ValueError("bad capture")
            return SimpleNamespace(text="", orientation="horizontal", undetected=False,
                                   scores=(), elapsed_ms=1)

    class Receiver(QObject):
        @Slot(object)
        def received(self, reading):
            readings.append(reading)

        @Slot(int, str)
        def failed(self, session, message):
            errors.append((session, message))

    worker = EngineThread()
    receiver = Receiver()
    worker.engine._ocr = FakeOCR()
    worker.engine.read_done.connect(receiver.received)
    worker.engine.watch_failed.connect(receiver.failed)
    try:
        worker.set_watch_session(1)
        worker.read_watch(images[0], 1, region)
        assert entered.wait(2)
        for image in images[1:]:
            worker.read_watch(image, 1, region)
        if invalidate:
            worker.set_watch_session(2)
            worker.read_watch(images[1], 1, region)  # old queued capture is refused
            worker.read_watch(images[-1], 2, region)
        release.set()
        loop = QEventLoop()
        poll = QTimer()
        poll.timeout.connect(lambda: (len(readings) + len(errors) >= 2) and loop.quit())
        poll.start(10)
        QTimer.singleShot(3000, loop.quit)
        loop.exec()
        assert len(readings) + len(errors) == 2
        assert calls == [images[0], images[-1]]
        assert readings[-1].image is images[-1]
        assert readings[-1].region == region
        assert readings[-1].session == (2 if invalidate else 1)
        assert bool(errors) is failure
        assert not worker._watch_busy
        assert worker._pending_watch is None
    finally:
        release.set()
        worker.stop()
        qt.processEvents()


def test_stopping_discards_the_pending_watch_capture():
    qt = QApplication.instance() or QApplication([])
    worker = EngineThread()
    try:
        worker._watch_busy = True
        worker.set_watch_session(1)
        worker.read_watch(Image.new("RGB", (8, 8)), 1, RegionArea(0, 0, 8, 8))
        worker.set_watch_session(2)
        worker._watch_finished()
        assert worker._pending_watch is None
        assert not worker._watch_busy
    finally:
        worker.stop()
        qt.processEvents()


@pytest.mark.parametrize("active,session", [(False, 3), (True, 2), (True, 3)])
def test_watch_results_cannot_reopen_a_stopped_or_replaced_region(active, session):
    from app.main import App
    from core.config import WatchConfig

    image = Image.new("RGB", (8, 8))
    region = RegionArea(1, 2, 8, 8)
    app = SimpleNamespace(language="zh", _counts={"watch": 0}, _watch_active=active, _watch_session=3,
                          _watched_line=None, config=SimpleNamespace(watch=WatchConfig(0.35)),
                          result=Mock(), window=Mock())
    reading = Reading("中文", [], "horizontal", False, (), 1, 1,
                      source="watch", image=image, session=session, region=region)
    App._on_reading(app, reading)
    if active and session == 3:
        app.result.show_capture.assert_called_once_with(image, region, activate=False, reposition=False)
        app.result.show_reading.assert_called_once_with(reading, append=True)
    else:
        app.result.show_capture.assert_not_called()
        app.result.show_reading.assert_not_called()
