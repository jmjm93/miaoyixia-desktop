import json
import os
import threading
import urllib.parse
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PySide6.QtCore import QEventLoop, QObject, QThread, QTimer, Slot
from PySide6.QtWidgets import QApplication

from app.region_area import RegionArea
from app.result import ResultWindow
from app.translation import TranslationThread
from app.worker import Reading
from core.config import load
from core.translation import TranslationError, Translator, segments


@pytest.fixture(scope="session")
def qt():
    return QApplication.instance() or QApplication([])


def answer(text="Hello &amp; welcome"):
    return {"responseStatus": 200, "responseData": {"translatedText": text}}


def test_region_mode_and_rescan_buttons(qt):
    window = ResultWindow()
    modes, rescans = [], []
    window.mode_changed.connect(modes.append)
    window.rescan_requested.connect(lambda: rescans.append(True))
    try:
        assert not window._rescan_button.isEnabled()
        window._mode_button.click()
        assert modes == ["manual"]
        window.set_region_mode("manual", True, "alt+r")
        assert window._mode_button.text() == "M"
        assert "alt+r" in window._rescan_button.toolTip()
        window._rescan_button.click()
        assert rescans == [True]
        window._mode_button.click()
        assert modes[-1] == "automatic"
        window.set_region_mode("automatic", False, "alt+r")
        assert not window._rescan_button.isEnabled()
    finally:
        window.deleteLater()
        qt.processEvents()


def test_region_toggle_stops_requests_and_reenables_current_line(qt):
    window = ResultWindow()
    requested, cancelled = [], []
    window.translation_requested.connect(lambda *args: requested.append(args))
    window.translation_cancelled.connect(lambda: cancelled.append(True))
    def reading(text):
        return Reading(text, [], "horizontal", False, (), 1, 1)
    try:
        window.set_translation_enabled(True)
        window.show_reading(reading("你好。"))
        old_ticket = requested[-1][0]
        window._translation_toggle.click()
        assert not window._translation_enabled
        assert not window._translation_toggle.isChecked()
        assert window._translation_host.isHidden()
        assert cancelled
        window.apply_translation(old_ticket, "late reply", "")
        assert not window._translation.toPlainText()
        window.show_reading(reading("再见。"), append=True)
        window.set_translation_enabled(True, "es")  # reload must preserve the session choice
        assert len(requested) == 1
        window._translation_toggle.click()
        assert window._translation_enabled and window._translation_toggle.isChecked()
        assert requested[-1][1] == "再见。"
        assert window._translation_target == "es"
    finally:
        window.close()
        window.deleteLater()
        qt.processEvents()


def test_region_toggle_can_enable_translation_when_config_default_is_off(qt):
    from app.main import App
    from types import SimpleNamespace
    from unittest.mock import Mock
    window = ResultWindow()
    app = SimpleNamespace(result=window, translation=Mock(), config=SimpleNamespace(
        translation=SimpleNamespace(enabled=False, target_lang="en")))
    window.translation_requested.connect(lambda ticket, text: App._on_translation_requested(app, ticket, text))
    try:
        window.show_reading(Reading("你好", [], "horizontal", False, (), 1, 1))
        app.translation.translate.assert_not_called()
        window._translation_toggle.click()
        app.translation.translate.assert_called_once_with(window._translation_ticket, "你好", "en")
    finally:
        window.close()
        window.deleteLater()
        qt.processEvents()


def test_watch_tail_noise_preserves_selected_word_and_candidate(qt):
    from core.reading import read_line
    window = ResultWindow()
    sentence = "今天我们一起去学校学习中文。"
    image = Image.new("RGB", (100, 50), "white")
    def reading(text):
        return Reading(text, read_line(text), "horizontal", False, (), 1, 1, source="watch")
    try:
        window.show_reading(reading(sentence))
        index = next(i for i, t in enumerate(window._tokens) if t.text == "学校")
        window.select_token(index)
        candidate = len(window._tokens[index].candidates) - 1
        window._show_candidates(window._tokens[index], candidate)
        headword = window._tokens[index].candidates[candidate].headword
        window.show_capture(image, RegionArea(0, 0, 100, 50), activate=False, reposition=False)
        window.show_reading(reading(sentence + "X"), append=True)
        assert window._tokens[window._active].text == "学校"
        assert window._tokens[window._active].candidates[window._candidate].headword == headword
        window.show_reading(reading("明天她要在家读书。"), append=True)
        assert window._active == 0
    finally:
        window.close()
        window.deleteLater()
        qt.processEvents()


def test_unicode_segmentation_preserves_every_character_and_prefers_sentences():
    text = "你好。" + "𠀀中文" * 100 + "！" + "世界" * 100
    parts = segments(text)
    assert "".join(parts) == text
    assert all(len(part.encode("utf-8")) <= 500 for part in parts)
    assert parts[0] == "你好。"


def test_requests_translate_every_segment_and_cache_successes_per_language():
    calls = []
    def transport(request, timeout):
        calls.append(urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query))
        assert 0 < timeout <= 8
        return answer()
    translator = Translator(transport)
    text = "中文" * 200
    result = translator.translate(text)
    assert result == " ".join(["Hello & welcome"] * len(segments(text)))
    assert "".join(call["q"][0] for call in calls) == text
    assert all(call["langpair"] == ["zh-CN|en"] for call in calls)
    count = len(calls)
    assert translator.translate(text) == result
    assert len(calls) == count
    translator.translate(text, "es")
    assert len(calls) == count * 2


@pytest.mark.parametrize("response", [None, {}, {"responseStatus": "bad"},
    {"responseStatus": 200, "responseData": {}}, answer(""), answer(None),
    {"responseStatus": 403, "responseDetails": "Daily limit reached"},
    {**answer(), "quotaFinished": True},
])
def test_provider_failures_are_errors_and_are_not_cached(response):
    calls = []
    def transport(request, timeout):
        calls.append(1)
        return response
    translator = Translator(transport)
    for _ in range(2):
        with pytest.raises(TranslationError):
            translator.translate("中文")
    assert len(calls) == 2


def test_timeout_is_reported_without_echoing_the_text_or_url():
    def transport(request, timeout):
        raise TimeoutError(request.full_url)
    with pytest.raises(TranslationError) as error:
        Translator(transport).translate("private text")
    assert "private" not in str(error.value)
    assert "http" not in str(error.value)


def test_empty_and_oversized_text_do_not_make_requests():
    def transport(*args):
        pytest.fail("unexpected network request")
    translator = Translator(transport)
    assert translator.translate("   ") == ""
    with pytest.raises(TranslationError):
        translator.translate("中" * 5001)


def test_cache_has_a_fixed_size():
    translator = Translator(lambda *args: answer())
    for i in range(150):
        translator.translate(f"中文{i}")
    assert len(translator._cache) == 128


def test_cancellation_stops_long_text_before_another_network_request():
    calls = []
    def transport(*args):
        calls.append(1)
        return answer()
    translator = Translator(transport, cancelled=lambda: bool(calls))
    with pytest.raises(TranslationError, match="cancelled"):
        translator.translate("中文" * 200)
    assert len(calls) == 1
    assert not translator._cache


def test_total_deadline_rejects_partial_results(monkeypatch):
    clock = [0.0]
    calls = []
    monkeypatch.setattr("core.translation.time.monotonic", lambda: clock[0])
    def transport(*args):
        calls.append(1)
        clock[0] = 21.0
        return answer()
    translator = Translator(transport)
    with pytest.raises(TranslationError, match="timed out"):
        translator.translate("中文" * 200)
    assert len(calls) == 1
    assert not translator._cache


def reading(text):
    return Reading(text, [], "horizontal", False, (), 1, 1)


def test_panel_requests_whole_text_and_ignores_stale_replies(qt):
    window = ResultWindow()
    requests = []
    window.translation_requested.connect(lambda *args: requests.append(args))
    window.set_translation_enabled(True)
    window.show_capture(Image.new("RGB", (300, 80)), RegionArea(10, 10, 300, 80))
    window.show_reading(reading("你好世界"))
    ticket = requests[-1][0]
    assert requests[-1][1] == "你好世界"
    window.apply_translation(ticket, "Hello world", "")
    assert window._translation.toPlainText() == "Hello world"
    assert window._translation.isReadOnly()
    window.show_reading(reading("另一句话"), append=True)
    assert requests[-1][1] == "另一句话", "watch history must not be resent every update"
    window.apply_translation(ticket, "old answer", "")
    assert window._translation.toPlainText() == "Translating…"
    current = requests[-1][0]
    window.apply_translation(current, "", "Daily limit reached")
    assert "Daily limit" in window._translation.toPlainText()
    assert not window._translation_retry.isHidden()
    window._translation_retry.click()
    assert requests[-1][0] != current
    window.dismiss()
    window.apply_translation(requests[-1][0] - 1, "late", "")
    assert window._translation.toPlainText() != "late"
    window.set_translation_enabled(False)
    count = len(requests)
    window.show_reading(reading("不联网"))
    assert len(requests) == count
    assert window._translation_host.isHidden()
    window.close()
    window.deleteLater()
    qt.processEvents()


def test_corrected_text_and_word_selection_do_not_send_individual_words(qt):
    from core.reading import read_line
    window = ResultWindow()
    requests = []
    window.translation_requested.connect(lambda *args: requests.append(args))
    window.set_translation_enabled(True)
    value = reading("研究生命起源")
    value = replace(value, tokens=read_line(value.line))
    window.show_reading(value)
    window.select_token(1)
    assert len(requests) == 1
    window.show_reading(reading("我修改了整句话"))
    assert requests[-1][1] == "我修改了整句话"
    assert not window.grab().isNull()
    window.close()
    window.deleteLater()
    qt.processEvents()


def test_slow_translation_coalesces_requests_and_replies_on_gui_thread(qt):
    entered, release = threading.Event(), threading.Event()
    calls, replies = [], []
    gui = QThread.currentThread()

    class Client:
        def translate(self, text, target):
            calls.append(text)
            if len(calls) == 1:
                entered.set()
                assert release.wait(3)
                raise TranslationError("first request failed")
            return "translated " + text

    class Receiver(QObject):
        @Slot(int, str, str)
        def received(self, ticket, text, error):
            assert QThread.currentThread() is gui
            replies.append((ticket, text, error))

    worker = TranslationThread()
    receiver = Receiver()
    worker.worker.client = Client()
    worker.worker.completed.connect(receiver.received)
    try:
        worker.translate(1, "first", "en")
        assert entered.wait(2)
        for i in range(2, 20):
            worker.translate(i, str(i), "en")
        release.set()
        loop = QEventLoop()
        poll = QTimer()
        poll.timeout.connect(lambda: len(replies) == 2 and loop.quit())
        poll.start(10)
        deadline = QTimer()
        deadline.setSingleShot(True)
        deadline.timeout.connect(loop.quit)
        deadline.start(3000)
        loop.exec()
        deadline.stop()
        poll.stop()
        assert calls == ["first", "19"]
        assert replies[0][2] == "first request failed"
        assert replies[-1] == (19, "translated 19", "")
    finally:
        release.set()
        worker.stop()
        qt.processEvents()


def test_translation_settings_apply_without_requiring_other_sections(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"translation": {"target_lang": "es", "future": True}}), encoding="utf-8")
    config = load(path)
    assert not config.error
    assert config.translation.enabled
    assert config.translation.target_lang == "es"
