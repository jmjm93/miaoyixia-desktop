"""The seven real captures, and what they actually say.

Copied wholesale from the extension's test/fixtures/ocr/. Its expected.json carries both the
truth for each image and a long note on what was tried against it -- read those notes before
reaching for a preprocessing idea, because most of the obvious ones are already recorded as
measured failures.
"""

import json
from dataclasses import dataclass
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures"

# What Tesseract scored, per the extension's own measurements. The column we have to beat.
#
# Sources: expected.json's per-fixture notes, and README.md's "what it reads well" section.
# A value of None means the extension recorded no number for it.
TESSERACT_BASELINE = {
    "vertical-handletter-two-column": 0.30,  # "Best so far: cer 0.30 at 2x"
    "light-on-dark-banner": 1.00,  # "Reads nothing at all rather than reading it wrong"
    "horizontal-printed-clean": 0.00,  # control
    "vertical-printed-clean": 0.00,  # control
    "traditional-vertical-two-column": 0.00,  # "Reads exactly now (cer 0.00)" after column split
    "traditional-vertical-three-column": 0.00,  # control for column splitting
    "noisy-background-bubble": None,  # over-detection; no single number recorded
}


@dataclass(frozen=True)
class Fixture:
    name: str
    path: Path
    text: str
    script: str  # "simplified" | "traditional"
    orientation: str  # "horizontal" | "vertical"
    columns: int
    note: str

    @property
    def baseline(self) -> float | None:
        return TESSERACT_BASELINE.get(self.name)


def load(directory: Path = FIXTURE_DIR) -> list[Fixture]:
    """Every fixture that has both an image and a recorded truth.

    Entries with an empty `text` are placeholders the extension left for images it never
    collected; they are skipped rather than scored as total failures.
    """
    raw = json.loads((directory / "expected.json").read_text(encoding="utf-8"))

    out = []
    for name, spec in raw.items():
        if name.startswith("_"):
            continue
        path = directory / f"{name}.png"
        if not path.exists() or not spec.get("text"):
            continue
        out.append(
            Fixture(
                name=name,
                path=path,
                text=spec["text"],
                script=spec.get("script", "simplified"),
                orientation=spec.get("orientation", "horizontal"),
                columns=spec.get("columns", 1),
                note=spec.get("note", ""),
            )
        )
    return sorted(out, key=lambda f: f.name)
