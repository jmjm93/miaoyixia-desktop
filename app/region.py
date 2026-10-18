from .region_border import RegionBorder
from .watcher import WatcherThread
from .result import ResultWindow
from.region_area import RegionArea

from enum import StrEnum

class RegionMode(StrEnum):
    AUTOMATIC = "automatic"
    MANUAL = "manual"

class Region:
    def __init__(self, id: int, rectangle: RegionArea, colour: str, mode: RegionMode = RegionMode.AUTOMATIC):
        super().__init__()
        self.id = id;
        self.rectangle: RegionArea = rectangle;
        self.colour: str = colour;
        self.border: RegionBorder = RegionBorder(self.colour);
        self.watcher: WatcherThread = WatcherThread();
        self.result: ResultWindow = ResultWindow(self.id);

        self._watched_line: str | None = None
        self._watch_session = 0
        self._watch_active = False
        self._mode: RegionMode = mode

    def close(self) -> None:
        self.watcher.shutdown()
        self.border.close()
        self.result.close()
