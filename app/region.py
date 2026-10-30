from .region_border import RegionBorder
from .watcher import WatcherThread
from .result import ResultWindow
from .region_area import RegionArea

from enum import StrEnum
from PySide6.QtCore import QObject, Slot

class RegionMode(StrEnum):
    AUTOMATIC = "automatic"
    MANUAL = "manual"

class Region(QObject):
    def __init__(self, id: int, rectangle: RegionArea, colour: str, mode: RegionMode = RegionMode.AUTOMATIC, language="zh"):
        super().__init__()
        self.id = id
        self.rectangle: RegionArea = rectangle
        self.colour: str = colour
        self.border: RegionBorder = RegionBorder(self.colour)
        self.watcher: WatcherThread = WatcherThread()
        self.language = language
        self.result: ResultWindow = ResultWindow(self.id, language)

        self._watched_line: str | None = None
        self._watch_session = 0
        self._watch_active = False
        self._mode: RegionMode = mode

    @Slot(int, object)
    def on_frame(self, session, image):
        self.app._on_watch_frame(self, session, image)

    @Slot(int, bool)
    def on_state(self, session, watching):
        self.app._on_watch_state(self, session, watching)

    def close(self) -> None:
        self.app._on_result_closed(self)
