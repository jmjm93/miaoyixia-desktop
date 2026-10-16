"""MyMemory's public translation API, with bounded requests and a resident success cache."""
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict

ENDPOINT = "https://api.mymemory.translated.net/get"
MAX_SEGMENT_BYTES = 500
MAX_TEXT_CHARS = 5000
MAX_RESPONSE_BYTES = 1024 * 1024
REQUEST_TIMEOUT = 8
TOTAL_TIMEOUT = 20


class TranslationError(Exception):
    pass


def segments(text: str) -> list[str]:
    """Split at sentence boundaries where possible, never inside a UTF-8 character."""
    result = []
    while text:
        size, end, boundary = 0, 0, 0
        for i, char in enumerate(text):
            size += len(char.encode("utf-8"))
            if size > MAX_SEGMENT_BYTES:
                break
            end = i + 1
            if char in "。！？；.!?;\n":
                boundary = end
        if end == len(text):
            result.append(text)
            break
        end = boundary or end
        result.append(text[:end])
        text = text[end:]
    return result


class Translator:
    def __init__(self, transport=None, cancelled=None, source_lang: str = "zh-CN"):
        self._transport = transport or self._fetch
        self._cancelled = cancelled or (lambda: False)
        if source_lang not in ("zh-CN", "ja"):
            raise ValueError("source_lang must be zh-CN or ja")
        self.source_lang = source_lang
        self._cache = OrderedDict()

    @staticmethod
    def _fetch(request, timeout):
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise TranslationError("Translation service returned too much data")
        return json.loads(raw)

    def translate(self, text: str, target_lang: str = "en") -> str:
        text = text.strip()
        if not text:
            return ""
        if len(text) > MAX_TEXT_CHARS:
            raise TranslationError("Text exceeds the 5,000-character translation limit; frame a smaller region")
        if not re.fullmatch(r"[a-zA-Z]{2,3}(?:-[a-zA-Z]{2,4})?", target_lang):
            raise TranslationError("Invalid target language code")
        key = (self.source_lang, text, target_lang.lower())
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        deadline = time.monotonic() + TOTAL_TIMEOUT
        translated = []
        for part in segments(text):
            if self._cancelled():
                raise TranslationError("Translation cancelled")
            if not part.strip():
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TranslationError("Translation timed out; try again")
            query = urllib.parse.urlencode({"q": part, "langpair": self.source_lang + "|" + target_lang.lower(), "mt": "1"})
            request = urllib.request.Request(ENDPOINT + "?" + query,
                                            headers={"User-Agent": "MiaoyixiaDesktop/1.0"})
            try:
                response = self._transport(request, min(REQUEST_TIMEOUT, remaining))
                status = int(response.get("responseStatus", 0))
                if status != 200 or response.get("quotaFinished"):
                    detail = response.get("responseDetails") or "Daily allowance reached or service unavailable"
                    raise TranslationError(str(detail))
                value = response["responseData"]["translatedText"]
                if not isinstance(value, str) or not value.strip():
                    raise TranslationError("Translation service returned no text")
                translated.append(html.unescape(value).strip())
            except urllib.error.HTTPError as exc:
                raise TranslationError(f"Translation service returned HTTP {exc.code}") from exc
            except (OSError, TimeoutError) as exc:
                raise TranslationError("Cannot reach MyMemory; check your connection and try again") from exc
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                raise TranslationError("Translation service returned an invalid response") from exc
        result = " ".join(translated)
        self._cache[key] = result
        if len(self._cache) > 128:
            self._cache.popitem(last=False)
        return result
