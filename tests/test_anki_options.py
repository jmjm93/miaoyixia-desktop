import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtWidgets import QApplication
from core.config import load
from app.options import OptionsDialog


@pytest.fixture(scope='session')
def qt():
    return QApplication.instance() or QApplication([])


def dialog_for(path):
    return OptionsDialog(config=load(path))


def test_save_updates_both_anki_profiles_preserving_other_settings(qt, tmp_path):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'watch': {'mode': 'manual'}, 'translation': {'enabled': False},
                                'anki': {'audio': 'off'}}))
    dialog = dialog_for(path)
    try:
        dialog.anki_chinese.inputs['deck'].setText('Chinese::Custom')
        dialog.anki_japanese.enabled.setChecked(True)
        dialog.anki_japanese.inputs['model'].setText('My Yomi')
        dialog.anki_japanese.fields.item(0, 0).setText('Term')
        dialog.accept()
        assert dialog.result() == dialog.DialogCode.Accepted
        config = load(path)
        assert config.anki.deck == 'Chinese::Custom'
        assert config.anki.audio == 'off'
        assert config.anki_japanese.enabled and config.anki_japanese.model == 'My Yomi'
        assert config.anki_japanese.fields['Term'] == 'headword'
        assert 'Expression' not in config.anki_japanese.fields
        assert config.watch.mode == 'manual' and not config.translation.enabled
    finally:
        dialog.deleteLater()
        qt.processEvents()


def test_cancel_and_invalid_fields_never_write_settings(qt, tmp_path):
    path = tmp_path / 'config.json'
    path.write_text('{}')
    dialog = dialog_for(path)
    try:
        dialog.anki_chinese.inputs['deck'].clear()
        dialog.accept()
        assert dialog.result() != dialog.DialogCode.Accepted
        assert dialog.error.text()
        assert path.read_text() == '{}'
        dialog.reject()
        assert path.read_text() == '{}'
    finally:
        dialog.deleteLater()
        qt.processEvents()


def test_external_unrelated_edits_are_preserved(qt, tmp_path):
    path = tmp_path / 'config.json'
    dialog = dialog_for(path)
    try:
        path.write_text('{"watch":{"rescan_hotkey":"alt+r"}}')
        dialog.accept()
        assert load(path).watch.rescan_hotkey == 'alt+r'
    finally:
        dialog.deleteLater()
        qt.processEvents()
