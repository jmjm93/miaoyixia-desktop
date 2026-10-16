"""Local Japanese morphology and JMdict lookup. Imported only by Japanese sessions."""
from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
import sqlite3
import threading
import unicodedata

from core.lang.script import is_han, is_kana
from core.reading import Candidate, Card, Token

from core.paths import DATA
DB_PATH = DATA / "japanese" / "jmdict.sqlite3"
SPANISH_DB_PATH = DB_PATH.with_name("jmdict-es.sqlite3")
if SPANISH_DB_PATH.exists():
    DB_PATH = SPANISH_DB_PATH


def hiragana(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return "".join(chr(ord(char) - 0x60) if 0x30A1 <= ord(char) <= 0x30F6 else char for char in text)


def applies(restrictions, value: str) -> bool:
    return "*" in restrictions or value in restrictions


@dataclass(frozen=True)
class Entry:
    headword: str
    reading: str
    senses: tuple[str, ...]
    common: bool = False


class Dictionary:
    def __init__(self, path: Path = DB_PATH):
        if not path.is_file():
            raise FileNotFoundError("Japanese dictionary missing. Run .venv\\Scripts\\python.exe tools/setup_japanese.py")
        self._db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, check_same_thread=False)
        self._lock = threading.RLock()
        with self._lock:
            if self._db.execute("PRAGMA user_version").fetchone()[0] != 1:
                self._db.close()
                raise ValueError("Japanese dictionary needs rebuilding: run tools/setup_japanese.py")

    @lru_cache(maxsize=2048)
    def lookup(self, form: str, hint: str = "", pos: str = "", user_language: str = "en") -> tuple[Entry, ...]:
        with self._lock:
            rows = self._db.execute("SELECT payload FROM word JOIN form ON word.id=form.word_id WHERE form.text=?",
                                    (form,)).fetchall()
        out = []
        for row in rows:
            word = json.loads(row[0])
            written = {entry["text"] for entry in word["kanji"]}
            for kana in word["kana"]:
                if form in written:
                    headword = form
                    if not applies(kana["appliesToKanji"], form):
                        continue
                else:
                    if kana["text"] != form:
                        continue
                    headword = form  # preserve a kana lookup rather than impose a kanji spelling
                senses = []
                spanish_senses = []
                for sense in word["sense"]:
                    if form in written and not applies(sense["appliesToKanji"], form):
                        continue
                    if not applies(sense["appliesToKana"], kana["text"]):
                        continue
                    tags = sense["partOfSpeech"]
                    if pos == "助詞" and "prt" not in tags:
                        continue
                    if pos == "動詞" and not any(tag.startswith("v") for tag in tags):
                        continue
                    if pos == "助動詞" and not any(tag in ("aux", "aux-v", "aux-adj", "cop") for tag in tags):
                        continue
                    glosses = [gloss["text"] for gloss in sense["gloss"] if gloss["lang"] == "eng"]
                    if user_language == "es":
                        spanish = [g["text"] for g in sense["gloss"] if g["lang"] == "spa"]
                        if spanish:
                            spanish_senses.append("; ".join(spanish))
                    if glosses:
                        senses.append("; ".join(glosses))
                senses = spanish_senses or senses
                if senses:
                    out.append(Entry(headword, kana["text"], tuple(senses), kana["common"]))
        return tuple(sorted(dict.fromkeys(out), key=lambda entry: (hiragana(entry.reading) != hiragana(hint),
                                                        not entry.common, entry.headword, entry.reading)))

    def close(self):
        self._db.close()
        self.lookup.cache_clear()


def card(entry: Entry, surface: str, sentence: str) -> Card:
    return Card(entry.headword, "", "", False, "", "", (), entry.senses,
                sentence=sentence, as_read=surface, language="ja", reading=entry.reading)


class Reader:
    def __init__(self, dictionary: Dictionary | None = None):
        from fugashi import Tagger
        self.dictionary = dictionary or Dictionary()
        self._tagger = Tagger()
        # The reader can also serve the headless endpoint; serialize MeCab across callers.
        self._lock = threading.RLock()

    def read(self, line: str, user_language: str = "en") -> list[Token]:
        with self._lock:
            return self._read(line, user_language)

    def _read(self, line: str, user_language: str = "en") -> list[Token]:
        def lookup(form, hint="", pos=""):
            return self.dictionary.lookup(form, hint, pos, user_language)
        words = list(self._tagger(line))
        positions, cursor = [], 0
        for word in words:
            start = line.find(word.surface, cursor)
            if start < 0:
                raise ValueError("Japanese tokenizer returned a span outside the input")
            positions.append(start)
            cursor = start + len(word.surface)
        result, i, cursor = [], 0, 0
        while i < len(words):
            word, start = words[i], positions[i]
            if cursor < start:
                result.append(Token(line[cursor:start], cursor, start - cursor))
            end = start + len(word.surface)
            next_i = i + 1
            pos = word.feature.pos1
            hint = hiragana(word.feature.kanaBase or "")
            lemma = (word.feature.lemma or "").split("-")[0]
            forms = list(dict.fromkeys(filter(lambda value: value and value != "*", (
                lemma, word.feature.orthBase, word.surface,
            ))))
            # Inflected verbs/adjectives stay as one readable chip, including their auxiliaries.
            if pos in ("動詞", "形容詞"):
                while next_i < len(words) and positions[next_i] == end:
                    following = words[next_i]
                    negative = following.feature.pos1 == "形容詞" and following.feature.pos2 == "非自立可能"
                    if following.feature.pos1 != "助動詞" and not negative:
                        break
                    end += len(following.surface)
                    next_i += 1
            # Recover dictionary compounds split by the tokenizer, only at real token boundaries.
            compounds = []
            for j in range(i, min(len(words), i + 8)):
                # Never swallow particles or auxiliaries into a coincidental dictionary word:
                # 今日 + は is a topic phrase, not necessarily the greeting 今日は.
                if j > i and (pos not in ("名詞", "接頭辞", "接尾辞")
                              or words[j].feature.pos1 not in ("名詞", "接頭辞", "接尾辞")):
                    break
                boundary = positions[j] + len(words[j].surface)
                surface = line[start:boundary]
                if len(surface) > 32 or any(not (is_han(c) or is_kana(c)) for c in surface):
                    break
                entries = lookup(surface, hint, pos if j == i else "")
                if entries:
                    compounds.append((boundary, j + 1, surface, entries))
            if compounds and compounds[-1][0] > end:
                end, next_i = compounds[-1][:2]
            surface = line[start:end]
            candidates, seen = [], set()
            for boundary, _, form, entries in reversed(compounds):
                if boundary > end:
                    continue
                candidates.append(Candidate(form, boundary - start,
                                            tuple(card(entry, line[start:boundary], line) for entry in entries)))
                seen.add(form)
            for form in forms:
                if form in seen:
                    continue
                entries = lookup(form, hint, pos)
                if entries:
                    candidates.append(Candidate(form, end - start, tuple(card(entry, surface, line) for entry in entries)))
                    seen.add(form)
            default = next((index for index, candidate in enumerate(candidates) if candidate.length == end - start), 0)
            if pos in ("動詞", "形容詞") and word.surface != word.feature.orthBase:
                for preferred in (lemma, word.feature.orthBase):
                    chosen = next((index for index, candidate in enumerate(candidates)
                                   if candidate.headword == preferred), None)
                    if chosen is not None:
                        default = chosen
                        break
            if not candidates and any(is_han(c) or is_kana(c) for c in surface):
                reading = hiragana(word.feature.kana or "")
                fallback = Entry(surface, reading, ("No JMdict entry found",))
                candidates.append(Candidate(surface, len(surface), (card(fallback, surface, line),)))
            result.append(Token(surface, start, len(surface), tuple(candidates), default))
            cursor, i = end, next_i
        if cursor < len(line):
            result.append(Token(line[cursor:], cursor, len(line) - cursor))
        return result


@lru_cache(maxsize=1)
def reader() -> Reader:
    return Reader()
