import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from core.config import load, remember_language
from core.reading import read_line, build_card
from core.lang.dict_store import Entry
from core.anki.fields import build_fields


def test_chinese_spanish_preserves_segmentation_and_exports_definitions():
    english, spanish = read_line("你好中国", "zh"), read_line("你好中国", "zh", "es")
    assert [t.text for t in english] == [t.text for t in spanish]
    card = spanish[0].candidates[spanish[0].default].cards[0]
    assert "hola" in card.senses
    assert build_fields({"Meaning": "senses"}, card)["Meaning"] == "hola"


def test_missing_spanish_entry_retains_english(monkeypatch):
    monkeypatch.setattr("core.lang.spanish.dictionary", lambda: {})
    entry = Entry("字", "字", "zi4", "character/word")
    assert build_card("字", entry, user_language="es").senses == ("character", "word")


def test_japanese_spanish_and_missing_sense_fallback(tmp_path):
    from core.lang.japanese import Dictionary
    from tools.setup_japanese import build
    word = {"id": "1", "kanji": [{"text": "猫"}], "kana": [{"text": "ねこ", "common": True, "appliesToKanji": ["*"]}],
        "sense": [{"appliesToKanji": ["*"], "appliesToKana": ["*"], "partOfSpeech": ["n"],
                   "gloss": [{"lang": "eng", "text": "cat"}, {"lang": "spa", "text": "gato"}]},
                  {"appliesToKanji": ["*"], "appliesToKana": ["*"], "partOfSpeech": ["n"],
                   "gloss": [{"lang": "eng", "text": "untranslated sense"}]}]}
    path = tmp_path / "dict.sqlite3"
    build([word], path)
    dictionary = Dictionary(path)
    try:
        assert dictionary.lookup("猫", user_language="es")[0].senses == ("gato",)
        assert dictionary.lookup("猫")[0].senses == ("cat", "untranslated sense")
    finally:
        dictionary.close()


def test_user_language_saved_independently(tmp_path):
    path = tmp_path / "config.json"
    assert remember_language("ja", path, "es")
    assert load(path).session.user_language == "es"
    assert remember_language("zh", path)
    assert load(path).session.user_language == "es"


def test_spanish_translation_target():
    from app.main import App
    app = SimpleNamespace(user_language="es", result=SimpleNamespace(_translation_enabled=True), translation=Mock())
    App._on_translation_requested(app, 1, "你好")
    app.translation.translate.assert_called_once_with(1, "你好", "es")


def test_ui_can_switch_back_to_english():
    from app.i18n import set_language, tr
    try:
        set_language("es")
        assert tr("Options") == "Opciones"
        translated = tr("Translation · ES · MyMemory")
        set_language("en")
        assert tr("Opciones") == "Options"
        assert tr(translated) == "Translation · ES · MyMemory"
    finally:
        set_language("en")


def test_user_language_change_keeps_capture_language_and_refreshes_definitions(monkeypatch, tmp_path):
    from app.main import App
    from app.i18n import set_language
    monkeypatch.setattr("app.main.localize", Mock())
    path = tmp_path / "config.json"
    app = SimpleNamespace(user_language="en", language="ja", _next_language="zh", config=load(path),
        window=Mock(), result=Mock(), engine=Mock(), _translate_tray=Mock())
    app.result._translation_line = "食べました。"
    app._translation_target = lambda: App._translation_target(app)
    try:
        App.set_user_language(app, "es")
        assert app.language == "ja" and app._next_language == "zh"
        app.engine.set_user_language.assert_called_once_with("es")
        app.engine.refresh_locale.assert_called_once_with("食べました。")
        assert load(path).session.user_language == "es"
    finally:
        set_language("en")
