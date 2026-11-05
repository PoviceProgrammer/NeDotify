"""Persisted legacy settings and live controls address the same preference."""
import pytest

from core.settings import SettingsManager
from tests.test_settings_manager import _FakeDb, _manager


@pytest.mark.parametrize('stored', [
    {'audio.crossfade_duration': 8},
    {'audio.crossfade_duration_sec': 8},
    {'audio.crossfade_duration': 3, 'audio.crossfade_duration_sec': 8},
])
def test_crossfade_ui_and_backend_restore_the_same_duration(stored):
    manager = _manager(stored)
    assert manager.get('audio', 'crossfade_duration') == 8
    assert manager.get('audio', 'crossfade_duration_sec') == 8


@pytest.mark.parametrize('category,key,value,other_category,other_key', [
    ('audio', 'crossfade_duration_sec', 9, 'audio', 'crossfade_duration'),
    ('theme', 'font_family', 'Inter', 'interface', 'font_family'),
    ('interface', 'accent_color', '#112233', 'theme', 'accent_color'),
    ('theme', 'theme_mode', 'light', 'theme', 'mode'),
])
def test_live_changes_persist_both_compatible_names(category, key, value, other_category, other_key):
    db = _FakeDb()
    manager = _manager(db=db)
    manager.set(category, key, value)
    assert manager.get(other_category, other_key) == value
    assert manager.sync_flush_now()
    restored = SettingsManager(db)
    assert restored.get(category, key) == value
    assert restored.get(other_category, other_key) == value


def test_legacy_font_migrates_even_when_interface_has_a_schema_default():
    manager = _manager({'theme.font_family': 'Inter'})
    assert manager.font_family == 'Inter'
    assert manager.get('interface', 'macos_font_family') == 'system'


def test_theme_values_win_when_old_categories_conflict():
    manager = _manager({'theme.accent_color': '#112233', 'interface.accent_color': '#445566'})
    assert manager.get('theme', 'accent_color') == '#112233'
    assert manager.get('interface', 'accent_color') == '#112233'
