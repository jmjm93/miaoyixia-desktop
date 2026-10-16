"""Recognition and lookup, off the GUI thread.

A snip costs 100-500ms of ONNX inference and the first one also pays ~1.3s to parse the
dictionary. On the GUI thread that is a frozen, unpainted window at exactly the moment the user is
waiting to see something, so all of it lives on one long-lived worker thread.

One thread rather than a pool, deliberately. The models are the expensive thing and they are
loaded once and reused -- the same reasoning that put the extension's recogniser in an offscreen
document that outlives its service worker. A pool would either duplicate them per thread or need
locking around them, and snips are serial anyway: there is one user drawing one box.
"""

import time
from dataclasses import dataclass

from PIL import Image
from PySide6.QtCore import QObject, QThread, Signal, Slot

from core.languages import ocr_script, validate, warm as warm_language
from core.ocr.ppocr import PPOCR
from core.reading import Token, read_line
from core.watch_text import dialogue_key


@dataclass(frozen=True)
class Reading:
    """Everything the result window needs from one snip."""

    line: str
    tokens: list[Token]
    orientation: str
    undetected: bool
    scores: tuple[float, ...]
    ocr_ms: float
    total_ms: float
    #: "snip" for a deliberate capture, "watch" for a pinned-region update. The window treats
    #: them differently: a snip may take focus, a watch update must never steal it from a game.
    source: str = "snip"
    image: Image.Image | None = None
    session: int = 0
    region: tuple[int, int, int, int] | None = None
    language: str = ""
    user_language: str = ""

    @property
    def empty(self) -> bool:
        return not self.line


class Engine(QObject):
    """Lives on the worker thread. Talk to it only through signals and queued slots."""

    warmed = Signal(float)
    read_done = Signal(object)  # Reading
    lookup_done = Signal(object)  # Reading, with no image involved
    failed = Signal(str)
    watch_finished = Signal()
    watch_failed = Signal(int, str)

    def __init__(self, language: str = "zh"):
        super().__init__()
        self.language = validate(language)
        self.user_language = "en"
        self._ocr: PPOCR | None = None
        self._ignored_suffixes = ()

    @Slot(object)
    def set_ignored_suffixes(self, suffixes) -> None:
        self._ignored_suffixes = tuple(suffixes)

    def _engine(self) -> PPOCR:
        if self._ocr is None:
            self._ocr = PPOCR(script=ocr_script(self.language))
        return self._ocr

    @Slot(str)
    def set_language(self, language: str) -> None:
        language = validate(language)
        if language != self.language:
            self.language = language
            self._ocr = None

    @Slot(str)
    def set_user_language(self, language: str) -> None:
        self.user_language = language

    def _parse(self, text):
        return read_line(text, self.language, "es") if self.user_language == "es" else read_line(text, self.language)

    @Slot()
    def warm(self) -> None:
        """Pay every one-off cost before the user asks for anything.

        Both halves matter. The dictionary is ~1.3s of JSON, and ONNX Runtime defers graph setup
        to the first inference -- so constructing the recogniser is not enough, it has to actually
        read something.
        """
        started = time.perf_counter()
        try:
            warm_language(self.language)
            self._engine().read(Image.new("RGB", (64, 64), "white"))
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            self.failed.emit(f"could not start the recogniser: {exc}")
            return
        self.warmed.emit((time.perf_counter() - started) * 1000)

    @Slot(object, object, str)
    def read(self, image: Image.Image, orientation: str | None = None, source: str = "snip",
             session: int = 0, region=None) -> None:
        started = time.perf_counter()
        try:
            reading = self._engine().read(image, orientation=orientation)
            line = dialogue_key(reading.text, self._ignored_suffixes)
            tokens = self._parse(line)
        except Exception as exc:  # noqa: BLE001
            if source == "watch":
                self.watch_failed.emit(session, f"recognition failed: {exc}")
            else:
                self.failed.emit(f"recognition failed: {exc}")
            return

        # An empty reading is a normal outcome on a textured panel, not a failure. The extension
        # is explicit that this "does not throw" -- the window says nothing was legible and shows
        # the capture, which is something the user can act on.
        self.read_done.emit(
            Reading(
                line=line,
                tokens=tokens,
                orientation=reading.orientation,
                undetected=reading.undetected,
                scores=reading.scores,
                ocr_ms=reading.elapsed_ms,
                total_ms=(time.perf_counter() - started) * 1000,
                source=source,
                image=image,
                session=session,
                region=region,
                language=self.language,
                user_language=self.user_language,
            )
        )

    @Slot(object)
    def read_watch(self, request) -> None:
        image, orientation, session, region = request
        try:
            self.read(image, orientation, "watch", session, region)
        finally:
            self.watch_finished.emit()

    @Slot(str)
    def lookup(self, line: str, source="edit") -> None:
        """Re-segment a line the user corrected by hand, with no re-snip.

        Per the extension, this is the highest-value interaction in the whole window: "recognition
        may fumble a stylised glyph, but the capture is right there above the box to check
        against", and no engine change buys as much.
        """
        started = time.perf_counter()
        try:
            tokens = self._parse(line)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"lookup failed: {exc}")
            return
        self.lookup_done.emit(
            Reading(
                line=line,
                tokens=tokens,
                orientation="",
                undetected=False,
                scores=(),
                ocr_ms=0.0,
                total_ms=(time.perf_counter() - started) * 1000,
                source=source,
                language=self.language,
                user_language=self.user_language,
            )
        )

    @Slot(str)
    def refresh_locale(self, line):
        self.lookup(line, "locale")


class EngineThread(QObject):
    """Owns the worker thread and the Engine on it.

    Requests go out as *signals*, never as method calls. This is the whole point and it is easy to
    get wrong: `moveToThread` changes which thread a QObject's slots run on **only when they are
    invoked through the signal/slot machinery**. Calling `engine.read(...)` as a plain Python
    method runs it right there on the caller's thread, so the worker thread sits idle while the
    GUI blocks for the length of an inference -- which is precisely the freeze this class exists
    to prevent, and it fails silently.

    Connecting a signal to a slot whose receiver lives on another thread makes the connection
    queued automatically, so emitting is the safe default.

    Not a QThread subclass, either: adding slots to a QThread subclass runs them on the thread
    that *created* it, since only run() executes on the new one.
    """

    #: image, orientation-or-None, source
    request_read = Signal(object, object, str)
    request_lookup = Signal(str)
    request_warm = Signal()
    request_watch = Signal(object)
    request_suffixes = Signal(object)
    request_language = Signal(str)
    request_user_language = Signal(str)
    request_locale_refresh = Signal(str)

    def __init__(self, language: str = "zh"):
        super().__init__()
        self.thread = QThread()
        self.thread.setObjectName("recogniser")
        self.engine = Engine(language)
        self.engine.moveToThread(self.thread)

        self.request_read.connect(self.engine.read)
        self.request_lookup.connect(self.engine.lookup)
        self.request_warm.connect(self.engine.warm)
        self.request_watch.connect(self.engine.read_watch)
        self.request_suffixes.connect(self.engine.set_ignored_suffixes)
        self.request_language.connect(self.engine.set_language)
        self.request_user_language.connect(self.engine.set_user_language)
        self.request_locale_refresh.connect(self.engine.refresh_locale)
        self.engine.watch_finished.connect(self._watch_finished)
        self._watch_busy = False
        self._pending_watch = None
        self._watch_session = 0

        self.thread.start()

    # Thin wrappers so callers cannot accidentally reach past them to the slots.
    def read(self, image: Image.Image, orientation: str | None = None, source: str = "snip") -> None:
        self.request_read.emit(image, orientation, source)

    def set_watch_session(self, session: int) -> None:
        """Invalidate queued captures when a region is stopped or replaced."""
        self._watch_session = session
        self._pending_watch = None

    def read_watch(self, image: Image.Image, session: int, region, orientation=None) -> None:
        if session != self._watch_session:
            return
        request = (image, orientation, session, region)
        if self._watch_busy:
            self._pending_watch = request
        else:
            self._watch_busy = True
            self.request_watch.emit(request)

    @Slot()
    def _watch_finished(self) -> None:
        self._watch_busy = False
        request, self._pending_watch = self._pending_watch, None
        if request is not None:
            self._watch_busy = True
            self.request_watch.emit(request)

    def lookup(self, line: str) -> None:
        self.request_lookup.emit(line)

    def set_ignored_suffixes(self, suffixes) -> None:
        self.request_suffixes.emit(suffixes)

    def set_language(self, language: str) -> None:
        self.request_language.emit(language)

    def set_user_language(self, language: str) -> None:
        self.request_user_language.emit(language)

    def refresh_locale(self, line: str) -> None:
        self.request_locale_refresh.emit(line)

    def warm(self) -> None:
        self.request_warm.emit()

    def stop(self) -> None:
        self.thread.quit()
        # Bounded: a hung inference must not stop the app from exiting.
        self.thread.wait(3000)
