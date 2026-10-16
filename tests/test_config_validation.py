import json

import pytest

from core.config import DEFAULTS, load


@pytest.mark.parametrize("raw", [
    [], None, {"anki": None}, {"watch": []}, {"diagnostics": "bad"},
    {"anki": {"enabled": "false"}}, {"anki": {"fields": []}},
    {"anki": {"fields": {"Hanzi": None}}}, {"anki": {"deck": 4}},
    {"anki": {"script": "other"}}, {"anki": {"audio": "other"}},
    {"anki": {"tts_service": "other"}},
    {"watch": {"min_han_fraction": "bad"}},
    {"watch": {"min_han_fraction": True}},
    {"watch": {"min_han_fraction": -1}},
    {"watch": {"min_han_fraction": 2}},
    {"watch": {"min_han_fraction": float("nan")}},
    {"watch": {"min_han_fraction": float("inf")}},
    {"diagnostics": {"health_seconds": None}},
    {"diagnostics": {"health_seconds": 1.5}},
    {"diagnostics": {"health_seconds": 0}},
    {"diagnostics": {"health_seconds": 2147483647}},
    {"translation": None}, {"translation": {"enabled": "false"}},
    {"translation": {"target_lang": None}}, {"translation": {"target_lang": "invalid language"}},
])
def test_invalid_settings_report_an_error_and_use_safe_defaults(tmp_path, raw):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    config = load(path)
    assert config.error.startswith("config.json:")
    assert config.anki.enabled is False
    assert config.anki.fields == DEFAULTS["anki"]["fields"]
    assert config.watch.min_han_fraction == 0.35
    assert config.diagnostics.health_seconds == 60


def test_valid_settings_and_unknown_future_keys_are_preserved(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"anki": {"enabled": True, "fields": {}},
                               "watch": {"min_han_fraction": 0}, "future": 1}), encoding="utf-8")
    config = load(path)
    assert not config.error
    assert config.anki.enabled
    assert config.anki.fields == {}
    assert config.watch.accepts("English")
