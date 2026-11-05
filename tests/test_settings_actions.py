"""Settings actions acknowledge persistence before applying their live effect."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.bridge import BridgeApi
from core.settings import SettingsManager


def test_equalizer_accepts_six_band_layout_with_ten_filter_gains(api, core_ns):
    assert api.set_equalizer(2.5, [3.5] * 10, mode=6) is True
    restored = api.get_equalizer()
    assert restored == {'preamp': 2.5, 'bands': [3.5] * 10, 'mode': '6'}
    assert api.set_equalizer(0, [0] * 10, mode=7) is False
    assert api.get_equalizer() == restored


@pytest.fixture
def persistent_settings(core_ns, tmp_db):
    settings = SettingsManager(tmp_db)
    # Exercise rollback of a user's existing explicit consent. New profiles
    # now leave Discord sharing disabled until the user opts in.
    settings.set('app', 'discord_rpc_enabled', True)
    core_ns.settings = settings
    yield settings
    settings.flush()
    settings.close()


def test_cache_quota_is_durable_when_the_action_returns(api, persistent_settings, tmp_db):
    assert BridgeApi(api).set_cache_quota(2)['success']
    restored = SettingsManager(tmp_db)
    try:
        assert restored.get('storage', 'cache_quota_gb') == 2
        assert restored.get('storage', 'cache_size_mb') == 2048
    finally:
        restored.close()


def test_cache_quota_failure_keeps_previous_limit_and_does_not_purge(
        api, core_ns, persistent_settings, monkeypatch):
    core_ns.cache = SimpleNamespace(purge_stream_cache=Mock())
    monkeypatch.setattr(api, 'get_storage_details', lambda: {})
    before = persistent_settings.get_category('storage')
    monkeypatch.setattr(persistent_settings, 'sync_flush_now', lambda: False)
    assert api.set_cache_quota(2)['success'] is False
    assert persistent_settings.get_category('storage') == before
    core_ns.cache.purge_stream_cache.assert_not_called()


def test_discord_toggle_is_durable_and_stops_the_service(
        api, core_ns, persistent_settings, tmp_db):
    core_ns.discord_rpc = SimpleNamespace(start=Mock(), stop=Mock())
    assert BridgeApi(api).toggle_discord_rpc(False)['success']
    core_ns.discord_rpc.stop.assert_called_once_with()
    restored = SettingsManager(tmp_db)
    try:
        assert restored.get('app', 'discord_rpc_enabled') is False
    finally:
        restored.close()


def test_discord_persistence_failure_does_not_change_service(
        api, core_ns, persistent_settings, monkeypatch):
    core_ns.discord_rpc = SimpleNamespace(start=Mock(), stop=Mock())
    monkeypatch.setattr(persistent_settings, 'sync_flush_now', lambda: False)
    assert api.toggle_discord_rpc(False)['success'] is False
    assert persistent_settings.get('app', 'discord_rpc_enabled') is True
    core_ns.discord_rpc.stop.assert_not_called()


def test_discord_service_failure_restores_persisted_preference(
        api, core_ns, persistent_settings, tmp_db):
    core_ns.discord_rpc = SimpleNamespace(start=Mock(), stop=Mock(side_effect=RuntimeError('IPC failure')))
    assert api.toggle_discord_rpc(False)['success'] is False
    assert persistent_settings.get('app', 'discord_rpc_enabled') is True
    assert tmp_db.get_setting('app.discord_rpc_enabled') is True


@pytest.mark.parametrize('value', ['false', 0, None])
def test_discord_toggle_rejects_non_boolean_values(api, persistent_settings, value):
    assert api.toggle_discord_rpc(value)['success'] is False
    assert persistent_settings.get('app', 'discord_rpc_enabled') is True


def test_enabling_discord_keeps_paused_track_paused(api, core_ns, persistent_settings):
    core_ns.discord_rpc = SimpleNamespace(start=Mock(), stop=Mock(), update_presence=Mock())
    api._current_track = {'title': 'Paused song', 'artist': 'Artist', 'duration': 180}
    api._last_reported_state = 'paused'
    assert api.toggle_discord_rpc(True)['success']
    assert core_ns.discord_rpc.update_presence.call_args.kwargs['is_playing'] is False


@pytest.mark.parametrize('category', ['app', 'general'])
def test_legacy_autostart_restores_consistently_in_both_categories(tmp_db, category):
    tmp_db.set_setting(category + '.autostart', True, category)
    settings = SettingsManager(tmp_db)
    try:
        assert settings.get('general', 'autostart') is True
        assert settings.get('app', 'autostart') is True
    finally:
        settings.close()


@pytest.mark.parametrize('category,key,value,other_category,other_key', [
    ('ui', 'particles_enabled', False, 'optimization', 'resource_particles'),
    ('optimization', 'resource_particles', False, 'ui', 'particles_enabled'),
    ('ui', 'cover_visualizer', True, 'optimization', 'resource_visualizers'),
    ('optimization', 'resource_visualizers', True, 'ui', 'cover_visualizer'),
])
def test_shared_controls_restore_and_save_one_preference(
        tmp_db, category, key, value, other_category, other_key):
    tmp_db.set_setting(f'{category}.{key}', value, category)
    settings = SettingsManager(tmp_db)
    try:
        assert settings.get(other_category, other_key) == value
        settings.set(other_category, other_key, not value)
        assert settings.get(category, key) == (not value)
        assert settings.sync_flush_now()
        assert tmp_db.get_setting(f'{category}.{key}') == (not value)
    finally:
        settings.close()


def test_audio_panel_preferences_survive_a_settings_manager_restart(api, persistent_settings, tmp_db):
    preferences = {'speed': 1.25, 'linkedSpeed': 1, 'pitch': 0, 'volume': 1.5,
                   'hqEnabled': True, 'engine': 'glyphs-7B', 'echo': 20}
    assert BridgeApi(api).save_setting('audio_tools', preferences, 'audio') is True
    restored = SettingsManager(tmp_db)
    try:
        assert restored.get('audio', 'audio_tools') == preferences
    finally:
        restored.close()
