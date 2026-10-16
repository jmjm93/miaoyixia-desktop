import json
from dataclasses import replace
from unittest.mock import Mock
import pytest

from core.anki.japanese import furigana, resolve
from core.anki.fields import build_fields
from core.anki.export import add_card, inspect_cards
from core.anki.audio import Audio
from core.config import load
from core.reading import Card


def card():
    return Card("食べる", "", "", False, "", "", (), ("to eat",),
                language="ja", reading="たべる", as_read="食べました", sentence="ご飯を食べました。")


@pytest.mark.parametrize("word,reading,expected", [
    ("食べる", "たべる", "<ruby>食<rt>た</rt></ruby>べる"),
    ("日本語", "にほんご", "<ruby>日本語<rt>にほんご</rt></ruby>"),
    ("ありがとう", "ありがとう", "ありがとう"),
    ("取り扱う", "とりあつかう", "<ruby>取<rt>と</rt></ruby>り<ruby>扱<rt>あつか</rt></ruby>う"),
])
def test_ruby_alignment(word, reading, expected):
    assert furigana(word, reading) == expected


def test_separate_japanese_defaults_and_custom_mapping(tmp_path):
    path = tmp_path / "config.json"
    config = load(path)
    japanese = config.anki_for("ja")
    assert japanese.deck == "Japanese::Japanese Mining" and japanese.model == "Yomi"
    fields = build_fields(japanese.fields, card(), {"audioFilename": "test.mp3"})
    assert fields["Expression"] == "食べる" and fields["Reading"] == "たべる"
    assert fields["Meaning"] == "to eat" and fields["Audio"] == "[sound:test.mp3]"
    path.write_text(json.dumps({"anki_japanese": {"model": "Custom", "deck": "Japanese", "fields": {"Term": "headword"}}}))
    custom = load(path)
    assert custom.anki_japanese.fields == {"Term": "headword"}
    assert custom.anki.model == "Chinese (Basic)"


def test_japanese_export_stores_audio_and_leaves_extra_yomi_fields_empty(monkeypatch, tmp_path):
    config = load(tmp_path / "config.json").anki_japanese
    client = Mock()
    client.deck_names.return_value = [config.deck]
    client.model_names.return_value = ["Yomi"]
    client.model_field_names.return_value = [*config.fields, "Manual examples", "Examples", "asdf"]
    client.store_media.return_value = "stored.mp3"
    client.add_note.return_value = 123
    audio = Mock(return_value=Audio(b"ID3" + b"a"*100, ".mp3", "jpod101"))
    monkeypatch.setattr("core.anki.japanese.resolve", audio)
    result = add_card(client, config, card())
    note = client.add_note.call_args.args[0]
    assert result["audioSource"] == "jpod101" and result["noteId"] == 123
    assert note["fields"]["Expression"] == "食べる"
    assert note["fields"]["Audio"] == "[sound:stored.mp3]"
    assert note["fields"]["asdf"] == ""
    audio.assert_called_once_with("食べる", "たべる", "auto", "edge", "ja-JP-NanamiNeural")
    client.create_model.assert_not_called()


def test_recording_failure_falls_back_to_selected_kana_and_voice(monkeypatch):
    import core.anki.japanese as module
    resolve.cache_clear()
    monkeypatch.setattr(module, "download", Mock(side_effect=ValueError("missing")))
    calls = []
    async def voice(text, voice):
        calls.append((text, voice))
        return b"ID3" + b"a"*100
    monkeypatch.setattr(module, "_synthesize", voice)
    assert resolve("食べる", "たべる").source == "edge"
    assert calls == [("たべる", "ja-JP-NanamiNeural")]
    with pytest.raises(ValueError):
        resolve("食べる", "たべる", "recording")
    assert len(calls) == 1
    resolve.cache_clear()


def test_audio_failure_does_not_lose_note(monkeypatch, tmp_path):
    config = load(tmp_path / "config.json").anki_japanese
    client = Mock()
    client.deck_names.return_value = [config.deck]
    client.model_names.return_value = [config.model]
    client.model_field_names.return_value = list(config.fields)
    monkeypatch.setattr("core.anki.japanese.resolve", Mock(side_effect=ValueError("unavailable")))
    result = add_card(client, config, card())
    assert result["audioError"] == "unavailable" and not result["audio"]
    assert client.add_note.call_args.args[0]["fields"]["Audio"] == ""


def test_inspection_does_not_download_audio_or_mutate_collection(monkeypatch, tmp_path):
    config = load(tmp_path / "config.json").anki_japanese
    client = Mock()
    client.deck_names.return_value = [config.deck]
    client.model_names.return_value = [config.model]
    client.model_field_names.return_value = list(config.fields)
    audio = Mock()
    monkeypatch.setattr("core.anki.japanese.resolve", audio)
    inspect_cards(client, config, [card()])
    audio.assert_not_called()
    client.create_deck.assert_not_called()
    client.add_note.assert_not_called()


@pytest.mark.parametrize("override", [{"enabled": "false"}, {"fields": []},
    {"tts_voice": "en-US-AriaNeural"}, {"tts_service": "baidu"}, {"audio": "invalid"}])
def test_invalid_japanese_settings_are_reported(tmp_path, override):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"anki_japanese": override}))
    assert load(path).error


def test_recording_placeholder_is_rejected(monkeypatch):
    import core.anki.japanese as module
    resolve.cache_clear()
    monkeypatch.setattr(module, "download", lambda *args: b"ID3" + b"a"*100)
    digest = Mock()
    digest.hexdigest.return_value = "ae6398b5a27bc8c0a771df6c907ade794be15518174773c58c7c7ddd17098906"
    monkeypatch.setattr(module.hashlib, "sha256", lambda data: digest)
    with pytest.raises(ValueError, match="No Japanese recording"):
        resolve("未知", "みち", "recording")
    resolve.cache_clear()
