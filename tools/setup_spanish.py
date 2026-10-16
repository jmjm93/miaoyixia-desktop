r"""Install Spanish definitions: tools/setup_spanish.py. No paid services or keys."""
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.setup_japanese import fetch, build, RELEASE

ROOT = Path(__file__).resolve().parents[1]


def main():
    repo = "jmjm93/cedict-translations"
    commit = json.loads(fetch(f"https://api.github.com/repos/{repo}/commits/main"))["sha"]
    base = f"https://raw.githubusercontent.com/{repo}/{commit}"
    raw = fetch(base + "/languages/es/cedict_es.u8")
    entries = {}
    for line in raw.decode("utf-8-sig").splitlines():
        match = re.match(r"^(\S+) (\S+) \[([^]]+)\] /(.+)/$", line)
        if match:
            traditional, simplified, pinyin, gloss = match.groups()
            key = simplified + "\t" + "".join(pinyin.split()).lower()
            entries.setdefault(key, []).append([traditional, gloss])
    directory = ROOT / "data" / "spanish"
    directory.mkdir(exist_ok=True)
    (directory / "cedict.json").write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    cache = fetch(base + "/languages/es/gloss-es.json")
    (directory / "gloss-es.json").write_bytes(cache)
    (directory / "LICENSE-CEDICT").write_bytes(fetch(base + "/LICENSE"))
    metadata = {"cedict_source": base, "cedict_sha256": hashlib.sha256(raw).hexdigest(), "entries": len(entries)}
    release = json.loads(fetch("https://api.github.com/repos/scriptin/jmdict-simplified/releases/tags/" + RELEASE))
    name = f"jmdict-all-{RELEASE}.json.zip"
    asset = next(a for a in release["assets"] if a["name"] == name)
    data = fetch(asset["browser_download_url"])
    digest = asset.get("digest", "").removeprefix("sha256:")
    if len(digest) != 64 or hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("JMdict SHA-256 verification failed")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        member = next(n for n in archive.namelist() if n.endswith(".json"))
        if archive.getinfo(member).file_size > 256 * 1024 * 1024:
            raise ValueError("JMdict archive unexpectedly large")
        words = json.loads(archive.read(member))["words"]
    for word in words:
        for sense in word["sense"]:
            sense["gloss"] = [g for g in sense["gloss"] if g["lang"] in ("eng", "spa")]
    build(words, ROOT / "data" / "japanese" / "jmdict-es.sqlite3")
    metadata.update(jmdict_source=asset["browser_download_url"], jmdict_sha256=digest)
    (directory / "meta.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Installed Spanish CEDICT ({len(entries):,} keys) and bilingual JMdict ({len(words):,} entries).")


if __name__ == "__main__":
    main()
