from types import SimpleNamespace

import numpy as np
from PIL import Image

from app import capture
from app.capture import Frame
from app.overlay import Selection
from app.region_area import RegionArea
from app.region_border import BORDER_INSET, BORDER_WIDTH, RegionBorder
from app.result import ResultWindow
from app.window import MainWindow


def test_selection_returns_a_region_area():
    area = Selection(-100, 20, 30, 40).rect
    assert isinstance(area, RegionArea)
    assert (area.x, area.y, area.width, area.height) == (-100, 20, 30, 40)


def test_frame_crops_region_area_in_virtual_coordinates():
    pixels = np.zeros((4, 6, 4), dtype=np.uint8)
    pixels[1:3, 2:5] = (10, 20, 30, 255)
    frame = Frame(pixels.tobytes(), 6, 4, (-4, -2), ())
    image = frame.crop(RegionArea(-2, -1, 3, 2))
    assert image.size == (3, 2)
    assert np.all(np.asarray(image) == (30, 20, 10))


def test_grab_region_passes_named_coordinates_to_mss(monkeypatch):
    requests = []

    def grab(rectangle):
        requests.append(rectangle)
        return SimpleNamespace(bgra=bytes((10, 20, 30, 255)), width=1, height=1)

    monkeypatch.setattr(capture, "_sct", lambda: SimpleNamespace(grab=grab))
    image = capture.grab_region(RegionArea(-100, 20, 0, 0))
    assert requests == [{"left": -100, "top": 20, "width": 1, "height": 1}]
    assert image.getpixel((0, 0)) == (30, 20, 10)


def test_border_uses_region_area_coordinates(qt_application):
    border = RegionBorder("#ffb020")
    try:
        border.set_region(RegionArea(-100, 20, 300, 80))
        pad = BORDER_WIDTH + BORDER_INSET
        geometry = border.geometry()
        assert (geometry.x(), geometry.y(), geometry.width(), geometry.height()) == (
            -100 - pad, 20 - pad, 300 + 2 * pad, 80 + 2 * pad,
        )
    finally:
        border.deleteLater()


def test_result_placement_accepts_region_area(qt_application):
    window = ResultWindow(0)
    try:
        window.show_capture(Image.new("RGB", (300, 80)), RegionArea(10, 20, 300, 80))
        assert window.screen().availableGeometry().contains(window.geometry())
    finally:
        window.deleteLater()


def test_main_window_describes_region_area(qt_application):
    window = MainWindow("ctrl+shift+space", "ctrl+shift+w", "#ffb020")
    try:
        window.set_watching(True, RegionArea(-100, 20, 300, 80))
        assert "300×80 at -100, 20" in window._status_hint.text()
    finally:
        window.deleteLater()
