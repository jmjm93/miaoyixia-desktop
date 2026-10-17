"""Keep Qt alive until test objects have been cleaned up."""
import gc
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session", autouse=True)
def qt_application():
    # Module-local fixtures and individual tests share this instance. Retain a
    # strong reference through their teardown rather than relying on shutdown
    # ordering between Python wrappers and Qt's native objects.
    application = QApplication.instance() or QApplication([])
    yield application
    application.closeAllWindows()
    for widget in application.topLevelWidgets():
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    gc.collect()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.fixture(autouse=True)
def drain_qt_deletions(qt_application):
    yield
    # processEvents() alone does not guarantee delivery of DeferredDelete.
    # Release test-owned widgets/watchers while Python and Qt are both alive.
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
