from pathlib import Path

from PIL import Image

from core.ocr.ppocr import PPOCR


def test_vertical_column_with_upright_number():
    path = Path(__file__).parents[1] / "bench/fixtures/vertical-text-with-horizontal-number.png"
    with Image.open(path) as image:
        engine = PPOCR()
        full = engine.read(image)
        assert full.orientation == "vertical"
        assert full.text.startswith("對了")
        assert "現在最新的顯示卡是298喔" in full.text
        # Reuse the pipeline after the detector-only rescue, with the column isolated.
        isolated = engine.read(image.crop((0, 0, 36, 215)), orientation="vertical")
        assert "顯示卡是298喔" in isolated.text
