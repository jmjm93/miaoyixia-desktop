from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.watch_text import dialogue_key


@pytest.mark.parametrize("suffix", ["", " ▷", "▶", " >", " ＞", "▸▸", " →", "\n"])
def test_animated_cursor_variants_are_equivalent(suffix):
    assert dialogue_key("している。" + suffix) == "している。"


@pytest.mark.parametrize("first,second", [
    ("待って。", "待って！"), ("猫です。", "犬です。"),
    ("一", "一人"), ("している。", "している。あ"),
    ("x", "x>"), ("猫です。", "犬です。▷"),
])
def test_real_small_changes_are_not_discarded(first, second):
    assert dialogue_key(first) != dialogue_key(second)


def test_cursor_rescans_do_not_touch_selected_definition_or_translation():
    from app.main import App
    from app.worker import Reading
    from core.config import WatchConfig
    app = SimpleNamespace(language="ja", _counts={"watch": 0}, _watch_active=True,
        _watch_session=1, _watched_line="猫です。", config=SimpleNamespace(watch=WatchConfig(0.35)),
        result=Mock(), window=Mock())
    for line in ("猫です。 ▷", "猫です。 >", "猫です。", "猫です。▶"):
        App._on_reading(app, Reading(line, [], "horizontal", False, (), 1, 1, source="watch", session=1))
    app.result.show_capture.assert_not_called()
    app.result.show_reading.assert_not_called()
    app.window.set_reading.assert_not_called()
    App._on_reading(app, Reading("犬です。", [], "horizontal", False, (), 1, 1, source="watch", session=1))
    app.result.show_reading.assert_called_once()


def test_initial_capture_sets_baseline_before_first_watch_rescan():
    from app.main import App
    from app.worker import Reading
    app = SimpleNamespace(_counts={"snip": 0}, _watch_active=True,
        _watched_line=None, result=Mock(), window=Mock(), region=None)
    App._on_reading(app, Reading("猫です。▷", [], "horizontal", False, (), 1, 1))
    assert app._watched_line == "猫です。▷"


def test_configured_kanji_artifact_is_removed_only_after_sentence_end():
    assert dialogue_key("している。大王", ("大王",)) == "している。"
    assert dialogue_key("大王", ("大王",)) == "大王"
    assert dialogue_key("彼は大王", ("大王",)) == "彼は大王"
    assert dialogue_key("している。大王") == "している。大王"


def test_worker_cleans_ocr_before_lookup_but_leaves_manual_text(monkeypatch):
    from app.worker import Engine
    import app.worker as module
    from PIL import Image
    engine = Engine("ja")
    engine.set_ignored_suffixes(("大王",))
    engine._ocr = SimpleNamespace(read=lambda *a, **k: SimpleNamespace(
        text="猫です。大王", orientation="horizontal", undetected=False, scores=(), elapsed_ms=1))
    calls, readings = [], []
    monkeypatch.setattr(module, "read_line", lambda text, language: calls.append(text) or [])
    engine.read_done.connect(readings.append)
    engine.read(Image.new("RGB", (8, 8)))
    assert calls == ["猫です。"]
    assert readings[0].line == "猫です。"
    engine.lookup("猫です。大王")
    assert calls[-1] == "猫です。大王"
