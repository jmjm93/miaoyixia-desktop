import json
import urllib.parse

import pytest

@pytest.fixture(scope="session")
def qt():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])

from core.config import load, remember_language
from core.lang.japanese import DB_PATH, Dictionary, hiragana, reader
from core.lang.script import language_fraction
from core.reading import read_line
from core.translation import Translator
from tools.setup_japanese import build


def selected(token):
    return token.candidates[token.default].cards[0]


@pytest.mark.skipif(not DB_PATH.exists(), reason="Run tools/setup_japanese.py for Japanese integration tests")
@pytest.mark.parametrize("sentence,surface,headword,kana", [
    ("昨日ご飯を食べました。", "食べました", "食べる", "たべる"),
    ("今日は学校に行きません。", "行きません", "行く", "いく"),
    ("美しかった。", "美しかった", "美しい", "うつくしい"),
    ("日本語を勉強しています。", "日本語", "日本語", "にほんご"),
])
def test_morphology_preserves_surface_and_returns_dictionary_form(sentence, surface, headword, kana):
    tokens = read_line(sentence, "ja")
    assert "".join(t.text for t in tokens) == sentence
    token = next(t for t in tokens if t.text == surface)
    entry = selected(token)
    assert (entry.headword, entry.pronunciation, entry.as_read) == (headword, kana, surface)
    assert entry.language == "ja" and entry.senses and not entry.pinyin


@pytest.mark.skipif(not DB_PATH.exists(), reason="Japanese dictionary unavailable")
def test_particles_are_not_swallowed_into_homophone_compounds():
    tokens = reader().read("  今日は学校です。  ")
    assert "".join(t.text for t in tokens) == "  今日は学校です。  "
    assert tokens[1].text == "今日" and tokens[2].text == "は"
    assert selected(tokens[1]).reading == "きょう"


def test_kana_watch_gate_and_normalization():
    assert language_fraction("ありがとう！", "ja") > 0.8
    assert language_fraction("ありがとう！", "zh") == 0
    assert language_fraction("English only", "ja") == 0
    assert hiragana("タベマシタ ｶﾀｶﾅ") == "たべました かたかな"


def test_startup_preference_preserves_other_config(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"translation": {"target_lang": "es"}}))
    assert remember_language("ja", path)
    assert load(path).session.language == "ja"
    assert load(path).translation.target_lang == "es"


def test_japanese_translation_uses_selected_source():
    calls = []
    def transport(request, timeout):
        calls.append(urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query))
        return {"responseStatus": 200, "responseData": {"translatedText": "Thank you"}}
    assert Translator(transport, source_lang="ja").translate("ありがとう") == "Thank you"
    assert calls[0]["langpair"] == ["ja|en"]


def test_dictionary_respects_reading_and_sense_restrictions(tmp_path):
    word = {"id": "1", "kanji": [{"text": "生"}], "kana": [
        {"text": "なま", "appliesToKanji": ["*"], "common": True},
        {"text": "せい", "appliesToKanji": ["*"], "common": False}], "sense": [
        {"appliesToKanji": ["*"], "appliesToKana": ["なま"], "partOfSpeech": ["n"],
         "gloss": [{"lang": "eng", "text": "raw"}]},
        {"appliesToKanji": ["*"], "appliesToKana": ["せい"], "partOfSpeech": ["n"],
         "gloss": [{"lang": "eng", "text": "life"}]}]}
    path = tmp_path / "dictionary.sqlite3"
    build([word], path)
    dictionary = Dictionary(path)
    try:
        assert dictionary.lookup("生", "せい")[0].senses == ("life",)
        assert dictionary.lookup("なま")[0].senses == ("raw",)
        assert not dictionary.lookup("生", pos="助詞")
    finally:
        dictionary.close()


def test_japanese_picker_and_anki_enabled(qt):
    from app.options import OptionsDialog
    from app.result import ResultWindow
    picker = OptionsDialog("ja")
    window = ResultWindow("ja")
    try:
        assert picker.language == "ja"
        picker.language_choice.setCurrentIndex(0)
        assert picker.language == "zh"
        window.set_anki_enabled(True)
        assert window._anki_enabled
    finally:
        picker.deleteLater()
        window.deleteLater()
        qt.processEvents()
