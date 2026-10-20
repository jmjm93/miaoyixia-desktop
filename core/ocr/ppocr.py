"""Tier 1: PP-OCR detection + recognition, with the reading order the detector does not give.

RapidOCR hands back a bag of boxes in no particular order. For horizontal text that is nearly
harmless; for vertical Chinese it is the whole problem. Measured on the fixtures, the characters
inside each box are almost always right and the ordering is what decides the score -- the
three-column fixture returns eight fragments that assemble into the correct sentence only if the
columns are found first.

This replaces the ink-profile column splitter in the extension's lib/ocr.js. That code existed
because Tesseract's layout analysis silently merged adjacent columns; a learned detector emits
them as separate boxes already, so the job here is grouping and sorting rather than cutting.
"""

from dataclasses import dataclass
from statistics import median

import numpy as np
from rapidocr import EngineType, LangRec, ModelType, OCRVersion, RapidOCR

# Boxes whose x-centres are closer than this fraction of the median box width belong to the same
# column. Measured across the four vertical fixtures: real column gaps are 27, 45, 46 and 70 px
# against median widths of 28, 72, 60 and 91, while within-column gaps never exceed 4px. Every
# fixture separates cleanly at 0.5, with the tightest margin (hand-lettered, gap 45 vs threshold
# 36) still a comfortable 25%.
COLUMN_GAP = 0.5

# Median box height/width above which a block is read as columns rather than rows. The vertical
# fixtures sit at 1.45, 3.0, 3.75 and 4.45; the horizontal one at 0.1. Nothing lands near 1.2,
# which is why this is only ever a default the caller may override.
VERTICAL_ABOVE = 1.2

# Never upscale the crop. Feed the detector the pixels the user actually framed.
#
# This is the single highest-value setting found, and it is the opposite of what the extension
# needed. RapidOCR ships `limit_type: min, limit_side_len: 736`, which scales the *shortest* side
# up to 736 -- on the 162x473 three-column fixture that is a 4.5x fractional resample, and it
# costs 0.26 CER and 5x the latency. Swept across the fixtures, every `max` bound from 480 to
# 2000 scores a clean 0.000 while every `min` bound degrades:
#
#   max/480 … max/2000   cer 0.000    174-304ms median
#   min/320              cer 0.000    468ms
#   min/240, min/400     cer 0.012
#   min/480              cer 0.032
#   min/736 (shipped)    cer 0.038    1193ms
#
# A plateau rather than a tuned point, which is what makes it trustworthy. 2000 matches
# Global.max_side_len and means "native resolution unless the crop is absurd".
#
# Worth contrasting with the extension's recogniserScale, which *doubled* small captures and
# insisted on integer factors because "anything else resamples onto a grid that does not line up,
# and smears the glyph edges". Same physics, opposite conclusion: a learned detector does not
# need the extra pixels, so the cheapest resample is none at all.
DETECTOR_LIMIT_TYPE = "max"
DETECTOR_LIMIT_SIDE = 2000

# PP-OCRv6 ships one `multi` recognition model covering both scripts -- verified against the
# catalogue, where the only traditional-specific model is a PP-OCRv3 relic. Both traditional
# fixtures read exactly through it. So on v6 this mapping is inert, and the extension's "Script in
# images" setting has nothing to select. Kept only because PP-OCRv5 does still split the two.
_REC_LANG = {
    "simplified": LangRec.CH,
    "traditional": LangRec.CHINESE_CHT,
    "japanese": LangRec.JAPAN,
}


@dataclass(frozen=True)
class Line:
    """One detected box, with the text found inside it."""

    text: str
    score: float
    box: np.ndarray  # 4x2, clockwise from top-left

    @property
    def x0(self) -> float:
        return float(self.box[:, 0].min())

    @property
    def x1(self) -> float:
        return float(self.box[:, 0].max())

    @property
    def y0(self) -> float:
        return float(self.box[:, 1].min())

    @property
    def y1(self) -> float:
        return float(self.box[:, 1].max())

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass(frozen=True)
class Reading:
    """What tier 1 makes of a capture."""

    text: str
    lines: tuple[Line, ...]
    orientation: str  # the one actually used to order the lines
    undetected: bool  # detection found nothing; this came from the whole-crop fallback
    elapsed_ms: float

    @property
    def scores(self) -> tuple[float, ...]:
        return tuple(line.score for line in self.lines)


def detect_orientation(lines: list[Line]) -> str:
    """Columns or rows, from box geometry alone.

    The extension refused to guess this, and was right to: Tesseract offered no signal, and its
    README records reading vertical text with the horizontal model returning 76% confidence while
    quietly dropping three characters of seven. Box aspect ratio is a different kind of evidence
    -- it comes from the detector rather than the recogniser, so it is not the thing being graded.
    """
    if not lines:
        return "horizontal"
    ratio = median(line.height / max(line.width, 1e-6) for line in lines)
    return "vertical" if ratio > VERTICAL_ABOVE else "horizontal"


def _cluster(centres: list[float], threshold: float) -> list[int]:
    """Group sorted positions into runs separated by gaps wider than `threshold`.

    Returns a cluster index per input position, in the input's own order.
    """
    order = sorted(range(len(centres)), key=lambda i: centres[i])
    cluster_of = [0] * len(centres)
    current = 0
    for rank, i in enumerate(order):
        if rank and centres[i] - centres[order[rank - 1]] > threshold:
            current += 1
        cluster_of[i] = current
    return cluster_of


def order_lines(lines: list[Line], orientation: str) -> list[Line]:
    """Put the boxes into the order a human reads them.

    Vertical Chinese reads the rightmost column top-to-bottom, then the next column left. So the
    boxes are grouped into columns by x-centre, the columns sorted right to left, and each
    column's contents sorted top to bottom. Horizontal is the same logic transposed: rows by
    y-centre, top to bottom, each row read left to right.
    """
    if len(lines) < 2:
        return list(lines)

    if orientation == "vertical":
        span = median(line.width for line in lines)
        groups = _cluster([line.cx for line in lines], span * COLUMN_GAP)
        # Negated, so the rightmost column sorts first.
        return _assemble(lines, groups, group_key=lambda box: -box.cx, within=lambda box: box.cy)

    span = median(line.height for line in lines)
    groups = _cluster([line.cy for line in lines], span * COLUMN_GAP)
    return _assemble(lines, groups, group_key=lambda box: box.cy, within=lambda box: box.cx)


def _assemble(lines, groups, group_key, within):
    """Sort groups by their median position, then sort within each group.

    Median rather than any single member's: a box that straddles two columns (the 半 in the
    three-column fixture is 82px wide in a 60px column) would otherwise drag its whole group.
    """
    buckets: dict[int, list[Line]] = {}
    for line, group in zip(lines, groups):
        buckets.setdefault(group, []).append(line)
    ordered = sorted(buckets.values(), key=lambda bucket: median(map(group_key, bucket)))
    return [line for bucket in ordered for line in sorted(bucket, key=within)]


def tidy(text: str) -> str:
    """Chinese has no inter-word spaces; anything the engine emits is a layout artefact.

    The same rule as the extension's offscreen.js -- a lookup of "中 国 菜" matches nothing.
    """
    return "".join(text.split())


class PPOCR:
    """A resident PP-OCR pipeline. Construction downloads and loads models; keep one."""

    def __init__(
        self,
        script: str = "simplified",
        model_type: ModelType = ModelType.SMALL,
        ocr_version: OCRVersion = OCRVersion.PPOCRV6,
        use_cuda: bool = False,
        text_score: float = 0.5,
        limit_type: str = DETECTOR_LIMIT_TYPE,
        limit_side: int = DETECTOR_LIMIT_SIDE,
    ):
        self.script = script
        self.model_type = model_type
        self.ocr_version = ocr_version
        self._rec_only = None
        self._engine = RapidOCR(
            params={
                "Global.text_score": text_score,
                "Global.log_level": "error",
                "Det.engine_type": EngineType.ONNXRUNTIME,
                "Det.model_type": model_type,
                "Det.ocr_version": ocr_version,
                "Det.limit_type": limit_type,
                "Det.limit_side_len": limit_side,
                "Rec.engine_type": EngineType.ONNXRUNTIME,
                "Rec.lang_type": _REC_LANG[script],
                "Rec.model_type": model_type,
                "Rec.ocr_version": ocr_version,
                "EngineConfig.onnxruntime.use_cuda": use_cuda,
            }
        )

    def _raw(self, image) -> list[Line]:
        result = self._engine(image)
        lines = [] if result is None or result.boxes is None else [
            Line(text=text, score=float(score), box=np.asarray(box, dtype=float))
            for box, text, score in zip(result.boxes, result.txts, result.scores)
        ]
        # RapidOCR filters empty recognitions out of its output. A vertical column
        # containing an upright number can disappear even though detection succeeded.
        use_rec, use_cls = self._engine.use_rec, self._engine.use_cls
        try:
            detected = self._engine(image, use_rec=False, use_cls=False)
        finally:
            self._engine.use_rec, self._engine.use_cls = use_rec, use_cls
        boxes = [] if detected.boxes is None else detected.boxes
        pixels = None
        for box in boxes:
            candidate = Line("", 0.0, np.asarray(box, dtype=float))
            if candidate.height / max(candidate.width, 1) < 3:
                continue
            if any(abs(line.cx - candidate.cx) < candidate.width * .5
                   and abs(line.cy - candidate.cy) < candidate.height * .5 for line in lines):
                continue
            if pixels is None:
                pixels = _as_array(image)
            left, right = candidate.x0, candidate.x1
            for other in boxes:
                cx = float(np.mean(other[:, 0]))
                if cx < candidate.cx:
                    left = max(left, (cx + candidate.cx) / 2)
                elif cx > candidate.cx:
                    right = min(right, (cx + candidate.cx) / 2)
            strip = _reflow_vertical(pixels[int(candidate.y0):int(candidate.y1),
                                             int(left):int(right)])
            if strip is not None:
                recovered = self._whole_crop()(strip)
                if recovered.txts and recovered.scores[0] >= self._engine.text_score:
                    lines.append(Line(recovered.txts[0], float(recovered.scores[0]), candidate.box))
        return lines

    def _whole_crop(self):
        """A second pipeline with the detector switched off. Built on first need."""
        if self._rec_only is None:
            self._rec_only = RapidOCR(
                params={
                    "Global.use_det": False,
                    "Global.use_cls": False,
                    "Global.log_level": "error",
                    "Rec.engine_type": EngineType.ONNXRUNTIME,
                    "Rec.lang_type": _REC_LANG[self.script],
                    "Rec.model_type": self.model_type,
                    "Rec.ocr_version": self.ocr_version,
                }
            )
        return self._rec_only

    def _read_undetected(self, image) -> list[Line]:
        """Read the whole crop as one text line, both polarities, better score wins.

        This is the light-on-dark rescue, and it works because the failure was never
        recognition. The extension diagnosed it exactly -- "Tesseract expects dark on light, and
        its layout analysis finds no text regions to hand the recogniser" -- and the same is true
        of DBNet on a textured banner: ten preprocessing variants (invert, greyscale,
        autocontrast, 2x, 4x, and their combinations) all detect nothing, while handing the
        recogniser that same untouched crop reads it exactly.

        So this does not try to fix detection. It skips it, which the snip path has earned the
        right to do: the user has already drawn a box around the text.

        Only ever a fallback. Horizontal crops are what a recognition model expects, and a
        vertical column handed to one whole comes back as noise -- measured at CER 1.00 on all
        four vertical fixtures ("虽然偶而也是会失败…" reads as "新验限").
        """
        engine = self._whole_crop()
        pixels = _as_array(image)

        best: list[Line] = []
        best_score = -1.0
        height, width = pixels.shape[:2]
        for candidate in (pixels, 255 - pixels):
            result = engine(candidate)
            texts = list(result.txts or [])
            if not texts:
                continue
            score = float(np.mean(result.scores)) if len(result.scores) else 0.0
            if score > best_score:
                best_score = score
                # One synthetic box covering the crop: there was no detection, so the only
                # honest geometry is "all of it".
                box = np.array([[0, 0], [width, 0], [width, height], [0, height]], dtype=float)
                best = [Line(text="".join(texts), score=score, box=box)]
        return best

    def read(
        self,
        image,
        orientation: str | None = None,
        whole_crop_fallback: bool = True,
    ) -> Reading:
        """Read a capture.

        `orientation` forces column or row ordering; None detects it from box geometry.

        `whole_crop_fallback` handles detection finding nothing at all. That is a different
        failure from detection finding the wrong thing, and it is the only case where a second
        attempt cannot make an existing answer worse -- because there is no existing answer.
        """
        import time

        started = time.perf_counter()

        lines = self._raw(image)
        undetected = False
        if not lines and whole_crop_fallback:
            lines = self._read_undetected(image)
            undetected = bool(lines)

        chosen = orientation or detect_orientation(lines)
        ordered = order_lines(lines, chosen)

        return Reading(
            text=tidy("".join(line.text for line in ordered)),
            lines=tuple(ordered),
            orientation=chosen,
            undetected=undetected,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )


def _as_array(image):
    """Accept a path, a PIL image or an array, and give back RGB pixels."""
    if isinstance(image, np.ndarray):
        return image
    from PIL import Image

    if isinstance(image, Image.Image):
        return np.asarray(image.convert("RGB"))
    return np.asarray(Image.open(image).convert("RGB"))


def _reflow_vertical(pixels):
    """Lay upright ink bands left-to-right, keeping inline numbers together."""
    import cv2

    if not pixels.size:
        return None
    rows = np.flatnonzero((pixels.min(axis=2) < 100).any(axis=1))
    bands = list(np.split(rows, np.where(np.diff(rows) > 1)[0] + 1))
    if not rows.size or len(bands) < 3:
        return None
    height = median(b[-1] - b[0] + 1 for b in bands)
    merged = []
    i = 0
    while i < len(bands):
        band = bands[i]
        # Keep disconnected strokes of a single glyph (e.g. 示) together.
        while (band[-1] - band[0] + 1 < height * .65 and i + 1 < len(bands)
               and bands[i + 1][-1] - band[0] + 1 <= height * 1.25):
            i += 1
            band = np.concatenate((band, bands[i]))
        merged.append(band)
        i += 1
    parts = []
    for band in merged:
        part = pixels[band[0]:band[-1] + 1]
        cols = np.flatnonzero((part.min(axis=2) < 100).any(axis=0))
        part = part[:, cols[0]:cols[-1] + 1]
        parts.append(cv2.resize(part, (max(1, round(part.shape[1] * 40 / part.shape[0])), 40)))
    return np.concatenate(parts, axis=1)
