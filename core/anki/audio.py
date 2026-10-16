"""Commons recordings followed by downloadable speech, matching the browser extension."""

import json
import logging
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from functools import lru_cache

log = logging.getLogger(__name__)
COMMONS = "https://commons.wikimedia.org/w/api.php"
MAX_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class Audio:
    data: bytes
    extension: str
    source: str


def download(url, referer=""):
    headers = {"User-Agent": "MiaoyixiaDesktop/1.0"}
    if referer:
        headers["Referer"] = referer
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=8) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("audio response exceeds size limit")
    return data


def matches_word(filename, word, pinyin):
    name = re.sub(r"[‐‑‒–—―−]", "-", filename.removeprefix("File:"))
    if not re.search(r"\.(ogg|oga|opus|wav|mp3|flac)$", name, re.I):
        return False
    if re.search(r"zh[-_]yue|\((yue|nan|hak|wuu|cdo|cjy|hsn|gan|lzh)\)|LL-Q9186|LL-Q7850", name, re.I):
        return False
    if not re.search(r"^zh[-_ ]|\(cmn\)|^LL-Q(?:9192|727694)(?!\d)", name, re.I):
        return False
    base = name.rsplit(".", 1)[0]
    spoken = (base.rsplit("-", 1)[-1] if base.startswith("LL-Q") else
              re.sub(r"^zh(?:[-_ ](?:tw|cn|hans|hant))?[-_ ]", "", base, flags=re.I)).strip()
    normalize = lambda text: re.sub(r"[.,!?;:'\"]+$", "", " ".join(text.lower().split())).strip()
    return spoken == word or bool(pinyin and normalize(spoken) == normalize(pinyin))


def checked(data):
    if len(data) < 64 or not data.startswith((b"OggS", b"RIFF", b"fLaC", b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")):
        raise ValueError("provider returned invalid audio")
    return data


@lru_cache(maxsize=24)
def resolve(word, simplified, traditional, pinyin, mode="auto", service="google"):
    """Cache successes only. Failures propagate so the UI can report missing audio."""
    if mode == "off":
        return None
    error = "No Mandarin recording found"
    if mode != "voice":
        try:
            for form in dict.fromkeys(filter(None, (word, simplified, traditional))):
                query = urllib.parse.urlencode(dict(action="query", list="search",
                    srsearch=f'intitle:{form} filetype:audio', srnamespace=6, srlimit=50, format="json"))
                result = json.loads(download(COMMONS + "?" + query))
                if "error" in result:
                    raise ValueError(str(result["error"]))
                names = [hit["title"].removeprefix("File:") for hit in result.get("query", {}).get("search", [])]
                names = sorted((n for n in names if matches_word(n, form, pinyin)),
                               key=lambda n: (not n.startswith("LL-Q"), n))
                if names:
                    name = names[0]
                    url = "https://commons.wikimedia.org/wiki/Special:FilePath/" + urllib.parse.quote(name.replace(" ", "_"))
                    return Audio(checked(download(url)), "." + name.rsplit(".", 1)[1].lower(), "commons")
        except (OSError, ValueError, KeyError) as exc:
            error = str(exc)
            log.warning("Commons audio failed for %s: %s", word, exc)
    if mode == "recording" or service == "off":
        raise ValueError(error)
    if not word or len(word) > 100:
        raise ValueError("Speech requires between 1 and 100 characters")
    if service == "google":
        origin = "https://translate.google.com/"
        query = urllib.parse.urlencode(dict(ie="UTF-8", q=word, tl="zh-CN", client="tw-ob",
                                            ttsspeed="1", total="1", idx="0", textlen=len(word)))
        url = origin + "translate_tts?" + query
    elif service == "baidu":
        origin = "https://fanyi.baidu.com/"
        url = origin + "gettts?" + urllib.parse.urlencode(dict(lan="zh", ie="UTF-8", text=word, spd=5, source="web"))
    else:
        raise ValueError("Unknown speech service: " + service)
    return Audio(checked(download(url, origin)), ".mp3", service)
