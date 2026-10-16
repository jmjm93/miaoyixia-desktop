"""One network request in flight and only the newest pending sentence."""
from PySide6.QtCore import QObject, QThread, Signal, Slot

from core.translation import Translator
from threading import Event


class TranslationWorker(QObject):
    completed = Signal(int, str, str)

    def __init__(self, source_lang: str = "zh-CN", cancelled=None):
        super().__init__()
        self.client = Translator(cancelled=lambda: (cancelled is not None and cancelled.is_set()) or QThread.currentThread().isInterruptionRequested(),
                                 source_lang=source_lang)

    @Slot(int, str, str)
    def translate(self, ticket: int, text: str, target: str) -> None:
        try:
            translated = self.client.translate(text, target)
        except Exception as exc:
            self.completed.emit(ticket, "", str(exc))
        else:
            self.completed.emit(ticket, translated, "")

    @Slot(str)
    def set_source(self, source: str) -> None:
        self.client.source_lang = source


class TranslationThread(QObject):
    requested = Signal(int, str, str)
    source_changed = Signal(str)

    def __init__(self, source_lang: str = "zh-CN"):
        super().__init__()
        self.thread = QThread()
        self.thread.setObjectName("translation")
        self._cancelled = Event()
        self.worker = TranslationWorker(source_lang, self._cancelled)
        self.worker.moveToThread(self.thread)
        self.requested.connect(self.worker.translate)
        self.source_changed.connect(self.worker.set_source)
        self.worker.completed.connect(self._finished)
        self.thread.finished.connect(self.worker.deleteLater)
        self._busy = False
        self._pending = None
        self.thread.start()

    def translate(self, ticket: int, text: str, target: str) -> None:
        request = (ticket, text, target)
        if self._busy:
            self._pending = request
        else:
            self._cancelled.clear()
            self._busy = True
            self.requested.emit(*request)

    @Slot(int, str, str)
    def _finished(self, _ticket: int, _text: str, _error: str) -> None:
        self._busy = False
        request, self._pending = self._pending, None
        if request is not None:
            self._cancelled.clear()
            self._busy = True
            self.requested.emit(*request)

    def cancel_pending(self) -> None:
        self._pending = None
        self._cancelled.set()

    def set_language(self, language: str) -> None:
        self.cancel_pending()
        self.source_changed.emit("ja" if language == "ja" else "zh-CN")

    def stop(self) -> None:
        self.cancel_pending()
        self.thread.requestInterruption()
        self.thread.quit()
        # Keep the QThread alive until its bounded network call has returned.
        self.thread.wait()
