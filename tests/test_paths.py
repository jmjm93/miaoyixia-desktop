from pathlib import Path
import sys
from core import paths


def test_source_settings_are_beside_project(monkeypatch):
    monkeypatch.delattr(sys, 'frozen', raising=False)
    assert paths.user_dir() == paths.ROOT


def test_frozen_settings_use_writable_user_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    assert paths.user_dir() == tmp_path / 'Miaoyixia'
    assert paths.user_dir().is_dir()
