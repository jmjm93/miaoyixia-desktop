"""CC-CEDICT, held whole in memory.

The extension shards the dictionary across 128 files and loads them on demand behind an LRU,
because a service worker is killed every thirty seconds and cannot afford to parse 19MB to answer
one hover. None of that applies to a resident process with 32GB behind it, so this loads the lot
once at startup and never thinks about it again -- the shard files are kept only as the on-disk
format, not as a caching strategy.

Entries are CC-CEDICT rows as the extension's build step left them:

    [simplified, traditional, numbered-pinyin, gloss]

with `traditional` blank when the two scripts agree. Both forms are indexed as keys, which is what
lets a reader of traditional manhua keep simplified on their Anki cards.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from core.paths import DATA
DATA_DIR = DATA / "dict"

# CC-CEDICT's longest headword is 19 characters, but scanning that far at every position of every
# line costs more than it finds. meta.json carries the real number; this is only the fallback,
# and matches the extension's.
DEFAULT_MAX_WORD_LENGTH = 8


@dataclass(frozen=True)
class Entry:
    simplified: str
    traditional: str
    pinyin: str  # numbered, as CC-CEDICT stores it; see lang.pinyin to render it
    gloss: str

    @classmethod
    def from_row(cls, row: list[str]) -> "Entry":
        simplified, traditional, pinyin, gloss = row
        # The build step blanks `traditional` when it equals `simplified`. Filling it back in here
        # means nothing downstream has to know about that compaction.
        return cls(simplified, traditional or simplified, pinyin, gloss)


@dataclass(frozen=True)
class Match:
    headword: str
    length: int
    entries: tuple[Entry, ...]


class Dictionary:
    """Every headword, in one dict. Build once and share it."""

    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        meta_path = data_dir / "meta.json"
        self.meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        self.max_word_length = int(self.meta.get("maxWordLength", DEFAULT_MAX_WORD_LENGTH))

        self._words: dict[str, tuple[Entry, ...]] = {}
        for shard in sorted((data_dir / "shards").glob("*.json")):
            for headword, rows in json.loads(shard.read_text(encoding="utf-8")).items():
                self._words[headword] = tuple(Entry.from_row(row) for row in rows)

    def __len__(self) -> int:
        return len(self._words)

    def __contains__(self, headword: str) -> bool:
        return headword in self._words

    def get(self, headword: str) -> tuple[Entry, ...]:
        return self._words.get(headword, ())

    def matches_from(self, chars: list[str], start: int) -> list[Match]:
        """Every dictionary word beginning at `start`, longest first.

        All lengths are returned rather than just the winner. That is what lets the UI offer one
        tab per candidate, so a wrong split costs a click instead of a re-snip -- and it is free,
        because segmentation needs these same matches anyway.
        """
        limit = min(len(chars) - start, self.max_word_length)
        matches = []
        for length in range(limit, 0, -1):
            headword = "".join(chars[start : start + length])
            entries = self._words.get(headword)
            if entries:
                matches.append(Match(headword=headword, length=length, entries=entries))
        return matches

    def matches_by_position(self, text: str) -> list[list[Match]]:
        """Matches beginning at every character position. Indexed by position."""
        chars = list(text)
        return [self.matches_from(chars, i) for i in range(len(chars))]

    def lookup_candidates(self, text: str) -> list[Match]:
        """Matches beginning at the start of `text`, longest first."""
        chars = list(text)
        return self.matches_from(chars, 0) if chars else []


@lru_cache(maxsize=1)
def dictionary() -> Dictionary:
    """The shared instance. First call pays the load; every later one is free."""
    return Dictionary()
