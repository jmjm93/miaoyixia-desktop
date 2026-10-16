"""An optional headless HTTP face for the same pipeline the app uses.

NOT how the desktop app talks to the recogniser. The app is a single PySide6 process and calls
`core.reading` and `core.ocr` directly on a worker thread -- an HTTP hop between two halves of one
process would be pure overhead.

This is kept because it is genuinely useful for three things the GUI cannot do: exercising the
pipeline from a script or a test without spinning up Qt, debugging a bad reading by POSTing the
exact PNG that produced it, and leaving a door open for a different frontend later.

    python -m core.server --port 8731

Nothing here listens on anything but 127.0.0.1.
"""

import argparse
import asyncio
import base64
import binascii
import io
import sys
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, is_dataclass

import uvicorn
from fastapi import FastAPI, HTTPException
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from .lang.dict_store import dictionary
from .languages import warm as warm_language
from .ocr.ppocr import PPOCR
from .reading import Token, read_line

# One recogniser per script, built on first use and kept. PP-OCRv6 uses a single multi-language
# model, so in practice this holds exactly one entry -- but PP-OCRv5 does split the two, and the
# fallback path may yet want it.
_engines: dict[str, PPOCR] = {}
_language = "zh"


def recogniser(script: str) -> PPOCR:
    if script not in _engines:
        _engines[script] = PPOCR(script=script)
    return _engines[script]


@asynccontextmanager
async def lifespan(_: FastAPI):
    # The dictionary is ~1.2s of JSON parsing. Doing it off the event loop means the port is
    # answering /health immediately and the shell can show its window, rather than the first snip
    # of the session paying for it.
    loop = asyncio.get_running_loop()
    warm = loop.run_in_executor(None, _warm_up)
    yield
    warm.cancel()


def _warm_up() -> None:
    started = time.perf_counter()
    warm_language(_language)
    print(f"dictionary ready in {(time.perf_counter() - started) * 1000:.0f}ms", flush=True)

    started = time.perf_counter()
    engine = recogniser("japanese" if _language == "ja" else "simplified")
    # A real inference, not just construction: ONNX Runtime defers graph setup to the first call,
    # and that cost would otherwise land on the user's first snip.
    engine.read(Image.new("RGB", (64, 64), "white"))
    print(f"recogniser ready in {(time.perf_counter() - started) * 1000:.0f}ms", flush=True)


app = FastAPI(title="miaoyixia headless", lifespan=lifespan)


def _plain(value):
    """Dataclasses to JSON-able dicts, recursively."""
    if is_dataclass(value):
        return {k: _plain(v) for k, v in asdict(value).items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


def _tokens(tokens: list[Token]) -> list[dict]:
    return [_plain(t) for t in tokens]


class ReadRequest(BaseModel):
    """A capture to recognise and look up."""

    image: str = Field(description="PNG bytes, base64. No data: prefix.")
    orientation: str | None = Field(
        default=None,
        description="'horizontal' | 'vertical'. Omit to detect from box geometry, which measured "
        "7/7 correct on the fixtures.",
    )
    script: str = Field(default="simplified", description="Inert on PP-OCRv6, which is multi-script.")


class LineRequest(BaseModel):
    """A line of text to look up, with no image involved.

    This is what the editable recognised line posts back. Correcting a glyph by eye and
    re-segmenting is, per the extension, worth more than any engine change -- and it must not
    require a re-snip.
    """

    line: str


@app.get("/health")
def health() -> dict:
    from .lang.dict_store import dictionary as _dict

    ready = _dict.cache_info().currsize > 0
    if _language == "ja":
        from .lang.japanese import reader
        ready = reader.cache_info().currsize > 0
    return {
        "ok": True,
        "language": _language,
        "dictionary": ready,
        "recognisers": sorted(_engines),
    }


@app.post("/read")
def read(request: ReadRequest) -> dict:
    try:
        raw = base64.b64decode(request.image, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"image is not valid base64: {exc}") from exc

    try:
        image = Image.open(io.BytesIO(raw)).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=400, detail=f"image could not be decoded: {exc}") from exc

    started = time.perf_counter()
    script = "japanese" if _language == "ja" else request.script
    if script not in ("simplified", "traditional", "japanese") or (_language == "zh" and script == "japanese"):
        raise HTTPException(status_code=400, detail="script does not match the server session language")
    reading = recogniser(script).read(image, orientation=request.orientation)

    # An empty reading is a normal outcome on a textured panel, not a failure -- the extension is
    # explicit that it "does not throw" here. The window shows the capture and says nothing was
    # legible, which is information the user can act on.
    return {
        "line": reading.text,
        "orientation": reading.orientation,
        "undetected": reading.undetected,
        "scores": list(reading.scores),
        "tokens": _tokens(read_line(reading.text, _language)),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
    }


@app.post("/lookup")
def lookup(request: LineRequest) -> dict:
    started = time.perf_counter()
    return {
        "line": request.line,
        "tokens": _tokens(read_line(request.line, _language)),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
    }


def main() -> None:
    global _language
    parser = argparse.ArgumentParser(description=__doc__)
    # Port 0 lets the OS pick a free one: two copies of the app must not fight over a fixed port,
    # and the shell reads the real one off stdout anyway.
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--language", choices=("zh", "ja"), default="zh")
    args = parser.parse_args()
    _language = args.language

    config = uvicorn.Config(app, host=args.host, port=args.port, log_level="warning")
    server = uvicorn.Server(config)

    # Bind before serving, so the port is known and printable before anything can ask for it.
    server.config.load()
    server.lifespan = server.config.lifespan_class(server.config)
    sockets = [config.bind_socket()]
    print(f"MIAOYIXIA_PORT={sockets[0].getsockname()[1]}", flush=True)

    try:
        asyncio.run(server.serve(sockets=sockets))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.exit(main())
