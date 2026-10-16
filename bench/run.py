"""Score the engines against the fixtures.

    python bench/run.py                 tier 1, shipped configuration
    python bench/run.py --sweep         tier 1, one variable at a time

Not a test. There is no threshold to pass -- OCR accuracy on hand-lettered manhua is a number to
push down, and what this exists for is to say whether a change actually pushed it. The
`tesseract` column is what the Chrome extension measured on the same seven images; every number
here is directly comparable to it.
"""

import argparse
import sys
from pathlib import Path

# Windows consoles default to cp1252, which cannot encode either the box-drawing characters or
# the Chinese this whole tool exists to print. Without this the run dies on its first table rule.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent))
# The engines under test are the ones the app ships, imported from core/ rather than copied
# here -- a benchmark measuring a fork of the code is measuring the wrong thing.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cer import cer  # noqa: E402
from fixtures import Fixture, load  # noqa: E402

NAME_WIDTH = 34


def _fmt(value: float | None) -> str:
    # Three decimals, because the interesting failures are now single characters in long lines.
    # game-item-description drops one glyph out of ~190 and scores 0.005; at two decimals that
    # prints as a flat 0.00 and the defect disappears from the table.
    return "  -   " if value is None else f"{value:6.3f}"


def _delta(got: float, baseline: float | None) -> str:
    """How this compares to Tesseract. Blank when the extension recorded no number."""
    if baseline is None:
        return "    "
    if abs(got - baseline) < 0.005:
        return "  = "
    return " ▼▼ " if got < baseline else " ▲▲ "


def report(rows: list[tuple[Fixture, str, float, str]], title: str) -> float:
    """Print one table and return the mean CER."""
    print()
    print(title)
    print("─" * 78)
    print(f"{'fixture':<{NAME_WIDTH}} {'tess':>6} {'ours':>6}      {'reading'}")
    print("─" * 78)

    total = 0.0
    for fixture, got, score, extra in rows:
        total += score
        print(
            f"{fixture.name:<{NAME_WIDTH}} "
            f"{_fmt(fixture.baseline)} {_fmt(score)}{_delta(score, fixture.baseline)} "
            f"{got or '(nothing)'}{extra}"
        )
        if score > 0:
            print(f"{'':<{NAME_WIDTH}} {'':>6} {'want:':>6}      {fixture.text}")

    mean = total / len(rows) if rows else 0.0
    print("─" * 78)
    print(f"{'mean':<{NAME_WIDTH}} {'':>6} {mean:.6f}")
    return mean


def run_ppocr(args) -> None:
    from rapidocr import ModelType, OCRVersion

    from core.ocr.ppocr import PPOCR

    # PP-OCRv6 ships tiny/small/medium (multi-language); PP-OCRv5 ships mobile/server per script.
    # Asking v6 for a "mobile" model is a hard error, not a fallback, so the two families cannot
    # share a size list.
    configs = [("PP-OCRv6 small, cpu  [shipped]", {})]
    if args.sweep and args.language == "ja":
        raise SystemExit("Japanese benchmark currently supports the shipped small model only.")
    if args.sweep:
        configs += [
            ("PP-OCRv6 tiny, cpu", {"model_type": ModelType.TINY}),
            ("PP-OCRv6 medium, cpu", {"model_type": ModelType.MEDIUM}),
            ("PP-OCRv5 mobile, cpu", {"model_type": ModelType.MOBILE, "ocr_version": OCRVersion.PPOCRV5}),
            ("PP-OCRv5 server, cpu", {"model_type": ModelType.SERVER, "ocr_version": OCRVersion.PPOCRV5}),
            # The setting the shipped configuration exists to reject. Keep it in the sweep so the
            # 0.038-vs-0.000 gap stays visible rather than becoming folklore.
            ("PP-OCRv6 small, upscaled (min736)", {"limit_type": "min", "limit_side": 736}),
        ]

    fixtures = load(Path(__file__).parent / "japanese") if args.language == "ja" else load()
    if args.only:
        fixtures = [f for f in fixtures if args.only in f.name]

    for title, overrides in configs:
        # One engine per script, because the recognition model differs. Built lazily and reused
        # across fixtures -- construction is most of the cost and would swamp the timings.
        engines: dict[str, PPOCR] = {}
        rows = []
        for fixture in fixtures:
            script = fixture.script if args.script == "auto" else args.script
            if script not in engines:
                engines[script] = PPOCR(script=script, use_cuda=args.cuda, **overrides)

            reading = engines[script].read(
                str(fixture.path),
                orientation=None if args.auto_orientation else fixture.orientation,
            )
            notes = [f"{reading.elapsed_ms:.0f}ms"]
            if reading.undetected:
                notes.append("whole-crop")
            if args.auto_orientation:
                hit = "✓" if reading.orientation == fixture.orientation else "✗"
                notes.append(f"{reading.orientation}{hit}")
            rows.append((fixture, reading.text, cer(reading.text, fixture.text), f"   [{', '.join(notes)}]"))

        report(rows, title)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=["ppocr"], default="ppocr")
    parser.add_argument("--language", choices=["zh", "ja"], default="zh")
    parser.add_argument("--sweep", action="store_true", help="try several configurations")
    parser.add_argument("--only", help="substring match on fixture name")
    parser.add_argument("--cuda", action="store_true", help="run tier 1 on the GPU")
    parser.add_argument(
        "--script",
        default="auto",
        choices=["auto", "simplified", "traditional"],
        help="auto uses each fixture's declared script",
    )
    parser.add_argument(
        "--auto-orientation",
        action="store_true",
        help="detect columns-vs-rows from box geometry instead of trusting the fixture",
    )
    args = parser.parse_args()

    run_ppocr(args)


if __name__ == "__main__":
    main()
