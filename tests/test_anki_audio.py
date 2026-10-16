import base64
import json
from dataclasses import replace

import pytest

from core.anki import audio, export
from core.config import load
from core.lang.dict_store import Entry
from core.reading import build_card
from core.anki.client import AnkiClient


@pytest.fixture(autouse=True)
def clear_cache():
    audio.resolve.cache_clear()
    yield
    audio.resolve.cache_clear()


def test_filters_language_word_and_reading():
    assert audio.matches_word("LL-Q9192—Speaker—你好.wav", "你好", "nǐ hǎo")
    assert not audio.matches_word("LL-Q9186 (yue)-Speaker-你好.wav", "你好", "nǐ hǎo")
    assert not audio.matches_word("Zh-你好朋友.ogg", "你好", "nǐ hǎo")
    assert not audio.matches_word("Zh-dá.ogg", "打", "dǎ")


def test_tries_simplified_and_uses_recording(monkeypatch):
    calls = []
    def get(url, referer=""):
        calls.append(url)
        if "Special:FilePath" in url:
            return b"RIFF" + b"x" * 100
        hits = [] if len(calls) == 1 else [{"title": "File:LL-Q9192 (cmn)-Speaker-个.wav"}]
        return json.dumps({"query": {"search": hits}}).encode()
    monkeypatch.setattr(audio, "download", get)
    result = audio.resolve("個", "个", "個", "gè")
    assert result.source == "commons"
    assert len(calls) == 3


def test_commons_failure_falls_back_to_google_with_referer(monkeypatch):
    def get(url, referer=""):
        if "commons" in url:
            raise OSError("429")
        assert "translate_tts" in url
        assert referer == "https://translate.google.com/"
        return b"ID3" + b"x" * 600
    monkeypatch.setattr(audio, "download", get)
    assert audio.resolve("你好", "你好", "你好", "nǐ hǎo").source == "google"


def test_invalid_synthesis_not_cached(monkeypatch):
    monkeypatch.setattr(audio, "download", lambda *args: b"<html>" + b"x" * 600)
    for _ in range(2):
        with pytest.raises(ValueError, match="invalid audio"):
            audio.resolve("你好", "你好", "你好", "nǐ hǎo", "voice")
    assert audio.resolve.cache_info().currsize == 0


@pytest.mark.parametrize("failure", [False, True])
def test_export_stores_media_before_note_or_reports_failure(monkeypatch, tmp_path, failure):
    config = load(tmp_path / "absent.json").anki
    card = build_card("你好", Entry("你好", "你好", "ni3 hao3", "hello"))
    calls = []
    def transport(action, params):
        calls.append((action, params))
        return {"deckNames": [config.deck], "modelNames": [config.model],
                "modelFieldNames": list(config.fields), "storeMediaFile": "actual.mp3", "addNote": 123}[action]
    def resolve(*args):
        if failure:
            raise ValueError("speech unavailable")
        return audio.Audio(b"ID3" + b"x" * 600, ".mp3", "google")
    monkeypatch.setattr(export, "resolve", resolve)
    result = export.add_card(AnkiClient(transport=transport), config, card)
    note = calls[-1][1]["note"]
    if failure:
        assert note["fields"]["Sound"] == ""
        assert result["audioError"] == "speech unavailable"
    else:
        assert calls[-2][0] == "storeMediaFile"
        assert base64.b64decode(calls[-2][1]["data"]).startswith(b"ID3")
        assert note["fields"]["Sound"] == "[sound:actual.mp3]"
        assert result["audioSource"] == "google"


def test_no_audio_mapping_does_not_fetch(monkeypatch, tmp_path):
    config = replace(load(tmp_path / "absent.json").anki, fields={"Hanzi": "headword"})
    monkeypatch.setattr(export, "resolve", lambda *args: pytest.fail("unexpected audio fetch"))
    client = AnkiClient(transport=lambda action, params: {
        "deckNames": [config.deck], "modelNames": [config.model],
        "modelFieldNames": ["Hanzi"], "addNote": 123}[action])
    card = build_card("你好", Entry("你好", "你好", "ni3 hao3", "hello"))
    assert not export.add_card(client, config, card)["audio"]
