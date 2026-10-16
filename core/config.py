"""Settings, read from config.json beside the app.

The defaults are the extension's, lifted from its lib/settings.js so a deck mined by one is a
deck mined by the other. Every name here is a *default*, not an assumption: the deck, the note
type and each field name are whatever the collection actually has, and anything configured that
does not exist yet is created on first use.

There is no settings window on purpose. The file is the interface: it is written out with the
defaults the first time the app runs, so there is something to edit rather than a format to
guess at.
"""

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

#: Beside run.cmd, not in %APPDATA%: this app is run out of its own folder, and a settings file
#: you can see next to the thing it configures is one you can find again.
from core.paths import user_dir
CONFIG_PATH = user_dir() / "config.json"

DEFAULTS = {
    "session": {"language": "zh", "user_language": "en"},
    "anki": {
        # Off until asked for. An add button that cannot work is worse than no button, and
        # nothing should be talking to a local HTTP port on the user's behalf unprompted.
        "enabled": False,
        "origin": "http://127.0.0.1:8765",
        "deck": "Mandarin::Chinese Mining",
        "model": "Chinese (Basic)",
        # Which script a note's headword is written in: 'as-read', 'simplified' or 'traditional'.
        # Independent of what the window shows. Someone studying simplified while reading
        # Taiwanese material wants both: 個 on screen, 个 on the card.
        "script": "as-read",
        # field name -> token id. See core/anki/fields.py TOKENS for every id.
        "fields": {
            "Hanzi": "headword",
            "Color": "colourHanzi",
            "Pinyin": "colourPinyin",
            "English": "senses",
            "Sound": "audio",
        },
        # Space-separated, applied to every note this adds.
        "tags": "miao-yixia",
        "audio": "auto",
        "tts_service": "google",
    },
    "watch": {
        # How much of a re-read has to be Han before it counts as a new line.
        #
        # A watched region re-reads whenever its pixels settle, and until this existed the only
        # gate was "is the text different from last time" -- so an English subtitle, a clock, or
        # a textured panel the whole-crop fallback guessed at each replaced a perfectly good
        # reading. Measured on the benchmark fixtures, real Chinese runs 0.714 to 1.000 and a
        # noisy hand-lettered panel 0.538; English and UI text are 0.000. See core/lang/script.py.
        #
        # 0 turns the gate off entirely and restores the old behaviour.
        "min_han_fraction": 0.35,
        "ignored_suffixes": [],
        "mode": "automatic",
        "rescan_hotkey": "ctrl+shift+r",
    },
    "diagnostics": {
        # Seconds between health lines in miaoyixia.log: memory, GDI and USER objects, kernel
        # handles, thread and object counts. The log is line-buffered, so the last one written
        # is always on disk -- which is what gives a crash something in front of it. Turn it
        # down while hunting something; 60s costs nothing.
        "health_seconds": 60,
    },
    "translation": {
        "enabled": True,
        "target_lang": "en",
    },
}

DEFAULTS["anki_japanese"] = {**DEFAULTS["anki"],
    "deck": "Japanese::Japanese Mining", "model": "Yomi", "tts_service": "edge",
    "tts_voice": "ja-JP-NanamiNeural",
    "fields": {"Expression": "headword", "Meaning": "senses", "Reading": "reading",
               "Furigana": "furigana", "Audio": "audio"}}


@dataclass(frozen=True)
class AnkiConfig:
    enabled: bool
    origin: str
    deck: str
    model: str
    script: str
    fields: dict[str, str]
    tags: str
    audio: str = "auto"
    tts_service: str = "google"
    tts_voice: str = "ja-JP-NanamiNeural"

    @property
    def tag_list(self) -> list[str]:
        return self.tags.split()


@dataclass(frozen=True)
class WatchConfig:
    min_han_fraction: float
    ignored_suffixes: tuple[str, ...] = ()
    mode: str = "automatic"
    rescan_hotkey: str = "ctrl+shift+r"

    def accepts(self, line: str, language: str = "zh") -> bool:
        """Whether a watched region's re-read is Chinese enough to replace what is on screen.

        A snip is not put through this. Dragging a box over English is a question the user asked
        on purpose and deserves an answer, even a disappointing one; a watch fires on its own and
        has to earn the interruption.
        """
        from core.lang.script import language_fraction

        if self.min_han_fraction <= 0:
            return True
        return language_fraction(line, language) >= self.min_han_fraction


@dataclass(frozen=True)
class DiagnosticsConfig:
    health_seconds: int


@dataclass(frozen=True)
class TranslationConfig:
    enabled: bool = True
    target_lang: str = "en"


@dataclass(frozen=True)
class SessionConfig:
    language: str = "zh"
    user_language: str = "en"


@dataclass(frozen=True)
class Config:
    anki: AnkiConfig
    watch: WatchConfig
    diagnostics: DiagnosticsConfig
    translation: TranslationConfig = field(default_factory=TranslationConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    anki_japanese: AnkiConfig = field(default_factory=lambda: AnkiConfig(**DEFAULTS["anki_japanese"]))

    def anki_for(self, language: str) -> AnkiConfig:
        return self.anki_japanese if language == "ja" else self.anki
    #: Empty when the file was read cleanly. A malformed config must not stop the app from
    #: starting -- it falls back to the defaults and says so where the user will see it.
    error: str = ""
    path: Path = field(default=CONFIG_PATH)


def _merge(defaults: dict, override) -> dict:
    """Defaults, with anything the file names replacing it, one level at a time.

    A merge rather than a replacement because a user who only wants a different deck should not
    have to restate the whole field mapping -- and because a key added by a later version has to
    keep working against a config file written before it existed.

    `fields` is the deliberate exception: it is a whole mapping, not a bag of independent keys,
    so naming it replaces it. Merging there would silently reinstate a default field that the
    user had removed, and AnkiConnect rejects the entire note for one field the note type lacks.
    """
    if not isinstance(override, dict):
        return dict(defaults)
    merged = dict(defaults)
    for key, value in override.items():
        if key != "fields" and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load(path: Path | None = None) -> Config:
    """Read the config, falling back to the defaults for anything it does not say."""
    path = path or CONFIG_PATH
    error = ""
    raw = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            _validate(raw)
        except (OSError, ValueError) as exc:
            error = f"{path.name}: {exc}"
            raw = {}

    merged = _merge(DEFAULTS, raw)
    anki = merged["anki"]
    watch = merged["watch"]
    diagnostics = merged["diagnostics"]
    return Config(
        session=SessionConfig(language=merged["session"]["language"], user_language=merged["session"]["user_language"]),
        anki_japanese=AnkiConfig(**merged["anki_japanese"]),
        watch=WatchConfig(min_han_fraction=float(watch["min_han_fraction"]),
                          ignored_suffixes=tuple(watch["ignored_suffixes"]),
                          mode=watch["mode"], rescan_hotkey=watch["rescan_hotkey"]),
        diagnostics=DiagnosticsConfig(health_seconds=int(diagnostics["health_seconds"])),
        translation=TranslationConfig(enabled=merged["translation"]["enabled"],
                                      target_lang=merged["translation"]["target_lang"]),
        anki=AnkiConfig(
            enabled=bool(anki["enabled"]),
            origin=str(anki["origin"]),
            deck=str(anki["deck"]),
            model=str(anki["model"]),
            script=str(anki["script"]),
            fields={str(k): str(v) for k, v in dict(anki["fields"]).items()},
            tags=str(anki["tags"]),
            audio=str(anki["audio"]),
            tts_service=str(anki["tts_service"]),
        ),
        error=error,
        path=path,
    )


def _validate(raw) -> None:
    """Reject invalid values before coercion; a string 'false' must never enable Anki."""
    if not isinstance(raw, dict):
        raise ValueError("settings must be a JSON object")
    for section in DEFAULTS:
        if section in raw and not isinstance(raw[section], dict):
            raise ValueError(f"{section} must be an object")
    if raw.get("session", {}).get("language", "zh") not in ("zh", "ja"):
        raise ValueError("session.language must be zh or ja")
    if raw.get("session", {}).get("user_language", "en") not in ("en", "es"):
        raise ValueError("session.user_language must be en or es")
    anki = raw.get("anki", {})
    for key, value in anki.items():
        if key == "enabled" and not isinstance(value, bool):
            raise ValueError("anki.enabled must be a boolean")
        if key == "fields":
            if not isinstance(value, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in value.items()
            ):
                raise ValueError("anki.fields must map field names to strings")
        elif key in DEFAULTS["anki"] and key != "enabled" and not isinstance(value, str):
            raise ValueError(f"anki.{key} must be a string")
    for key, choices in {
        "script": ("as-read", "simplified", "traditional"),
        "audio": ("auto", "recording", "voice", "off"),
        "tts_service": ("google", "baidu", "edge", "off"),
    }.items():
        if key in anki and anki[key] not in choices:
            raise ValueError(f"anki.{key} must be one of {', '.join(choices)}")
    if "anki_japanese" in raw:
        japanese = raw["anki_japanese"]
        for key in japanese:
            if key not in DEFAULTS["anki_japanese"]:
                raise ValueError(f"unknown anki_japanese setting: {key}")
        if "tts_voice" in japanese and (not isinstance(japanese["tts_voice"], str) or not japanese["tts_voice"].startswith("ja-JP-")):
            raise ValueError("anki_japanese.tts_voice must be a Japanese voice such as ja-JP-NanamiNeural")
        if japanese.get("tts_service", "edge") not in ("edge", "google", "off"):
            raise ValueError("anki_japanese.tts_service must be edge, google or off")
        _validate({"anki": {k: v for k, v in japanese.items() if k != "tts_voice"}})
    fraction = raw.get("watch", {}).get("min_han_fraction", 0.35)
    watch = raw.get("watch", {})
    if watch.get("mode", "automatic") not in ("automatic", "manual"):
        raise ValueError("watch.mode must be automatic or manual")
    chord = watch.get("rescan_hotkey", "ctrl+shift+r")
    if not isinstance(chord, str) or not chord.strip() or "+" not in chord:
        raise ValueError("watch.rescan_hotkey must be a hotkey with a modifier, e.g. ctrl+shift+r")
    suffixes = raw.get("watch", {}).get("ignored_suffixes", [])
    if not isinstance(suffixes, list) or any(not isinstance(s, str) or not s.strip() or len(s) > 16 for s in suffixes):
        raise ValueError("watch.ignored_suffixes must be a list of nonempty strings up to 16 characters")
    if (isinstance(fraction, bool) or not isinstance(fraction, (int, float))
            or not math.isfinite(fraction) or not 0 <= fraction <= 1):
        raise ValueError("watch.min_han_fraction must be a number between 0 and 1")
    seconds = raw.get("diagnostics", {}).get("health_seconds", 60)
    if isinstance(seconds, bool) or not isinstance(seconds, int) or not 1 <= seconds <= 86400:
        raise ValueError("diagnostics.health_seconds must be an integer between 1 and 86400")
    translation = raw.get("translation", {})
    if "enabled" in translation and not isinstance(translation["enabled"], bool):
        raise ValueError("translation.enabled must be a boolean")
    target = translation.get("target_lang", "en")
    if not isinstance(target, str) or not re.fullmatch(r"[a-zA-Z]{2,3}(?:-[a-zA-Z]{2,4})?", target):
        raise ValueError("translation.target_lang must be a language code such as en or es")


def write_defaults(path: Path | None = None) -> bool:
    """Write the default config, if there isn't one. Returns whether it wrote.

    Never overwrites: this runs on every start, and a file the user has edited is the last thing
    that should be reset by launching the app.
    """
    path = path or CONFIG_PATH
    if path.exists():
        return False
    try:
        path.write_text(json.dumps(DEFAULTS, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError:
        # A read-only install directory is not a reason to refuse to start; the defaults are
        # already in force, the user just has nothing to edit.
        return False
    return True


def remember_language(language: str, path: Path | None = None, user_language: str | None = None) -> bool:
    """Remember the picker selection without replacing any other user settings."""
    path = path or CONFIG_PATH
    if language not in ("zh", "ja"):
        raise ValueError("language must be zh or ja")
    if load(path).error:
        return False
    try:
        raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        raw.setdefault("session", {})["language"] = language
        if user_language is not None:
            if user_language not in ("en", "es"):
                raise ValueError("invalid user language")
            raw["session"]["user_language"] = user_language
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    except (OSError, ValueError):
        return False
    return True
