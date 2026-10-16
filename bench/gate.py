"""Does the watch gate separate Chinese from everything else?

    python bench/gate.py

Not a test, in the same sense bench/run.py is not one: it is the measurement the threshold in
core/config.py is chosen from, and it exists to say whether a change to the gate still separates
the two sets -- and by how much.

Two sets of images:

    fixtures/   real Chinese, the same captures the CER harness scores
    negatives/  no Chinese in them at all: a manga panel with no text, a noisy photograph, and
                a UI screenshot whose text is English and Japanese

The negatives matter more than they look. The obvious gate is recognition confidence, and the UI
screenshot is the counterexample that kills it: English at min score 0.995, higher than most of
the real Chinese. Confidence says how sure the model is of glyphs it has already committed to,
which is a different question from whether they were Chinese.
"""

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fixtures import load  # noqa: E402

from core.config import DEFAULTS  # noqa: E402
from core.lang.script import han_fraction  # noqa: E402
from core.ocr.ppocr import PPOCR  # noqa: E402

NEGATIVE_DIR = Path(__file__).parent / "negatives"
THRESHOLD = DEFAULTS["watch"]["min_han_fraction"]
NAME_WIDTH = 40


def measure(engine, path):
    from PIL import Image

    reading = engine.read(Image.open(path))
    return {
        "han": han_fraction(reading.text),
        "score": min(reading.scores) if reading.scores else 0.0,
        "undetected": reading.undetected,
        "text": reading.text,
    }


def main() -> int:
    engine = PPOCR()

    print(f"threshold {THRESHOLD}  (core/config.py, watch.min_han_fraction)\n")
    print(f"{'image':{NAME_WIDTH}} {'han%':>6} {'minscore':>9} {'verdict':>8}  text")
    print("-" * 100)

    positives, negatives = [], []
    for fixture in sorted(load(), key=lambda f: f.name):
        row = measure(engine, fixture.path)
        positives.append(row["han"])
        verdict = "keep" if row["han"] >= THRESHOLD else "SKIPPED"
        print(f"{fixture.name:{NAME_WIDTH}} {row['han']:6.3f} {row['score']:9.3f} "
              f"{verdict:>8}  {row['text'][:30]}")

    print()
    for path in sorted(NEGATIVE_DIR.glob("*.png")):
        row = measure(engine, path)
        negatives.append(row["han"])
        verdict = "skip" if row["han"] < THRESHOLD else "LET THROUGH"
        print(f"{path.stem:{NAME_WIDTH}} {row['han']:6.3f} {row['score']:9.3f} "
              f"{verdict:>8}  {row['text'][:30]}")

    worst_real, best_noise = min(positives), max(negatives)
    print()
    print(f"real Chinese, lowest   {worst_real:.3f}")
    print(f"non-Chinese, highest   {best_noise:.3f}")
    print(f"gap                    {worst_real - best_noise:.3f}"
          f"   threshold sits {THRESHOLD - best_noise:.3f} above the noise,"
          f" {worst_real - THRESHOLD:.3f} below the real")

    if best_noise >= THRESHOLD or worst_real < THRESHOLD:
        print("\nTHE THRESHOLD NO LONGER SEPARATES THEM")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
