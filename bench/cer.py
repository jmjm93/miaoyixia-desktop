"""Character error rate, and the folding that has to happen before it.

Ported from the Chrome extension's tools/bench-ocr.mjs (lines 42-70) so the numbers here are
directly comparable to the Tesseract baselines recorded in fixtures/expected.json. Do not
"improve" the metric without re-deriving those baselines -- a changed metric silently invalidates
every number we are measuring against.
"""

import unicodedata


def normalise(text: str | None) -> str:
    """Fold differences that are not recognition mistakes.

    NFKC maps fullwidth forms onto their ASCII equivalents, so an engine answering "!" where the
    truth says "！" stops counting as an error. The extension measured what leaving this out
    costs: a phantom 0.1 CER on every row of every sweep -- enough to reorder them and to make a
    perfect read look imperfect.
    """
    return unicodedata.normalize("NFKC", text or "")


def cer(got: str | None, want: str | None) -> float:
    """Edits per character of the truth. 0 is perfect, 1 is hopeless.

    Unbounded above: an engine that invents fifty characters where the truth has ten scores 5.0.
    That is deliberate and it is the point of the noisy-background fixture, where over-detection
    rather than misrecognition is the failure.
    """
    a = list(normalise(got))
    b = list(normalise(want))
    if not b:
        return 1.0 if a else 0.0

    prev = list(range(len(a) + 1))
    for j in range(1, len(b) + 1):
        row = [j]
        for i in range(1, len(a) + 1):
            row.append(
                min(
                    prev[i] + 1,
                    row[i - 1] + 1,
                    prev[i - 1] + (0 if a[i - 1] == b[j - 1] else 1),
                )
            )
        prev = row
    return prev[len(a)] / len(b)
