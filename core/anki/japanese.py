"""Japanese audio and Anki-ready ruby markup."""
import asyncio
import hashlib
import urllib.parse
from functools import lru_cache

from core.anki.audio import Audio, checked, download, MAX_BYTES
from core.lang.script import is_han
from core.anki.fields import escape_html


def furigana(word: str, reading: str) -> str:
    from core.lang.japanese import hiragana
    if not reading or not any(is_han(c) for c in word):
        return escape_html(word)
    # Kana anchors separate kanji runs; ambiguous alignment uses a whole-word ruby.
    runs = []
    for char in word:
        if runs and is_han(char) == is_han(runs[-1][0]):
            runs[-1] += char
        else:
            runs.append(char)
    solutions = []
    attempts = 0
    def align(index, offset, parts):
        nonlocal attempts
        attempts += 1
        if attempts > 4096:
            return
        if len(solutions) >= 2:
            return
        if index == len(runs):
            if offset == len(reading):
                solutions.append(parts)
            return
        run = runs[index]
        if not is_han(run[0]):
            kana = hiragana(run)
            if hiragana(reading[offset:offset+len(kana)]) == kana:
                align(index+1, offset+len(kana), parts+[(run, "")])
        else:
            for end in range(offset+1, len(reading)+1):
                align(index+1, end, parts+[(run, reading[offset:end])])
    if len(word) <= 64 and len(reading) <= 128:
        align(0, 0, [])
    parts = solutions[0] if len(solutions) == 1 and attempts <= 4096 else [(word, reading)]
    return "".join(f"<ruby>{escape_html(w)}<rt>{escape_html(r)}</rt></ruby>" if r else escape_html(w)
                   for w, r in parts)


async def _synthesize(text, voice):
    import edge_tts
    data = bytearray()
    async for chunk in edge_tts.Communicate(text, voice).stream():
        if chunk["type"] == "audio":
            data.extend(chunk["data"])
            if len(data) > MAX_BYTES:
                raise ValueError("Speech response exceeds size limit")
    return checked(bytes(data))


@lru_cache(maxsize=128)
def resolve(word, reading, mode="auto", service="edge", voice="ja-JP-NanamiNeural"):
    if mode == "off":
        return None
    if not word or not reading or len(word) > 100 or len(reading) > 100:
        raise ValueError("Japanese audio requires a word and kana reading of up to 100 characters")
    error = "No Japanese recording found"
    if mode != "voice":
        try:
            query = urllib.parse.urlencode({"kanji": word, "kana": reading})
            data = checked(download("https://assets.languagepod101.com/dictionary/japanese/audiomp3.php?" + query))
            # Provider returns a valid MP3 placeholder for absent recordings.
            if hashlib.sha256(data).hexdigest() == "ae6398b5a27bc8c0a771df6c907ade794be15518174773c58c7c7ddd17098906":
                raise ValueError(error)
            return Audio(data, ".mp3", "jpod101")
        except (OSError, ValueError) as exc:
            error = str(exc)
    if mode == "recording" or service == "off":
        raise ValueError(error)
    if service == "edge":
        if not voice.startswith("ja-JP-"):
            raise ValueError("Select a Japanese Edge voice")
        async def bounded():
            return await asyncio.wait_for(_synthesize(reading, voice), timeout=15)
        try:
            return Audio(asyncio.run(bounded()), ".mp3", "edge")
        except Exception as exc:
            raise ValueError(f"Japanese speech failed: {exc}") from exc
    if service == "google":
        query = urllib.parse.urlencode({"ie": "UTF-8", "q": reading, "tl": "ja", "client": "tw-ob"})
        return Audio(checked(download("https://translate.google.com/translate_tts?" + query,
                                      "https://translate.google.com/")), ".mp3", "google")
    raise ValueError("Japanese speech supports edge, google or off")
