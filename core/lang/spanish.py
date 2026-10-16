"""Spanish CEDICT gloss overlay; segmentation always uses the complete English dictionary."""
import json
import hashlib
from pathlib import Path
from functools import lru_cache
from core.paths import DATA


@lru_cache(maxsize=1)
def dictionary():
    path = DATA / "spanish" / "gloss-es.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def gloss(entry):
    pinyin = entry.pinyin.replace("u :", "u:").replace("U :", "U:")
    defs = "/".join(s for s in entry.gloss.split("/") if s)
    text = f"{entry.simplified}\t{pinyin}\t{defs}"
    key = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return dictionary().get(key)
