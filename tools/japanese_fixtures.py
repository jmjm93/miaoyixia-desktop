"""Reproduce synthetic printed Japanese OCR controls using Windows Yu Gothic."""
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

def main():
    root = Path(__file__).resolve().parents[1] / "bench" / "japanese"
    root.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype("C:/Windows/Fonts/YuGothM.ttc", 44)
    cases = {"horizontal-conjugation": "昨日ご飯を食べました。",
             "horizontal-compound": "日本語を勉強しています。",
             "horizontal-kana": "ありがとうございます",
             "horizontal-katakana": "ゲームのキャラクター",
             "vertical-printed": "日本語を読む"}
    expected = {"_note": "Synthetic printed controls; not real manga or game captures."}
    for name, text in cases.items():
        vertical = name.startswith("vertical")
        image = Image.new("RGB", (100, len(text)*54+40) if vertical else (len(text)*46+40, 100), "white")
        draw = ImageDraw.Draw(image)
        if vertical:
            for index, char in enumerate(text):
                draw.text((28, 20+index*54), char, font=font, fill="black")
        else:
            draw.text((20,20), text, font=font, fill="black")
        image.save(root / f"{name}.png")
        expected[name] = {"text": text, "script": "japanese", "orientation": "vertical" if vertical else "horizontal"}
    (root / "expected.json").write_text(json.dumps(expected, ensure_ascii=False, indent=2), encoding="utf-8")

if __name__ == "__main__":
    main()
