r"""Download a verified JMdict English release and build the local Japanese lookup database.

    .venv\Scripts\python.exe tools/setup_japanese.py
    .venv\Scripts\python.exe tools/setup_japanese.py --update
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import urllib.request
import zipfile
from contextlib import closing

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "japanese"
RELEASE = "3.6.2+20261005200550"
SHA256 = "4601650cb900865cb9b388d6a045835120b90fbe451048d319bb8999635d596f"
PROJECT = "https://github.com/scriptin/jmdict-simplified"


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "MiaoyixiaDesktop/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read(64 * 1024 * 1024)


def build(words, path):
    """Publish atomically; interruption must not replace an existing usable dictionary."""
    temporary = path.with_suffix(".building")
    if temporary.exists():
        temporary.unlink()
    try:
        with closing(sqlite3.connect(temporary)) as db, db:
            db.executescript("""
                CREATE TABLE word (id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE form (text TEXT NOT NULL, word_id INTEGER NOT NULL,
                                   PRIMARY KEY (text, word_id)) WITHOUT ROWID;
            """)
            for word in words:
                word_id = int(word["id"])
                db.execute("INSERT INTO word VALUES (?, ?)",
                           (word_id, json.dumps(word, ensure_ascii=False, separators=(",", ":"))))
                forms = {entry["text"] for kind in ("kanji", "kana") for entry in word[kind]}
                db.executemany("INSERT INTO form VALUES (?, ?)", ((form, word_id) for form in forms))
            db.execute("PRAGMA user_version = 1")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="use the latest upstream release")
    args = parser.parse_args()
    release, digest = RELEASE, SHA256
    name = f"jmdict-eng-{release}.json.zip"
    url = f"{PROJECT}/releases/download/{release}/{name}"
    if args.update:
        metadata = json.loads(fetch("https://api.github.com/repos/scriptin/jmdict-simplified/releases/latest"))
        asset = next(a for a in metadata["assets"] if a["name"].startswith("jmdict-eng-")
                     and not a["name"].startswith("jmdict-eng-common-") and a["name"].endswith(".json.zip"))
        release, url = metadata["tag_name"], asset["browser_download_url"]
        digest = asset.get("digest", "").removeprefix("sha256:")
        if len(digest) != 64:
            raise ValueError("The upstream release has no SHA-256 digest; refusing an unverified download")
    print(f"Downloading JMdict English {release}", flush=True)
    raw = fetch(url)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("Dictionary download failed its SHA-256 check")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        member = next(name for name in archive.namelist() if name.endswith(".json"))
        if archive.getinfo(member).file_size > 256 * 1024 * 1024:
            raise ValueError("Dictionary archive is unexpectedly large")
        dictionary = json.loads(archive.read(member))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Indexing {len(dictionary['words']):,} entries", flush=True)
    build(dictionary["words"], DATA_DIR / "jmdict.sqlite3")
    metadata = {key: value for key, value in dictionary.items() if key != "words"}
    metadata.update(release=release, source=url, sha256=digest,
                    entries=len(dictionary["words"]), license="CC BY-SA 4.0")
    (DATA_DIR / "meta.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (DATA_DIR / "licence.html").write_bytes(fetch("https://www.edrdg.org/edrdg/licence.html"))
    print(f"Ready: {DATA_DIR / 'jmdict.sqlite3'}", flush=True)


if __name__ == "__main__":
    main()
