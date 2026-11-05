"""First-launch choices are durable before the completion flag is acknowledged."""
import copy
from types import SimpleNamespace

import pytest

from core.api import AppApi
from core.settings import SettingsManager


@pytest.mark.parametrize('preset,values', [
    ('low', (10,15,30,'off','off',0,False)),
    ('balanced', (18,30,45,'lq','subtle',6,True)),
    ('high', (24,60,60,'hq','full',14,True)),
])
def test_profiles_apply_every_related_parameter(api, settings_stub, preset, values):
    result = api.complete_onboarding({'theme':'mint','performance_preset':preset,'audio_device':'headphones',
                                      'crossfade_enabled':True,'volume_normalization':True,'minimize_to_tray':False})
    assert result['success'] is True
    settings = result['settings']
    particles,viz,ui,blur,glow,glass,enabled = values
    assert settings['optimization']['fps_particles'] == particles
    assert settings['optimization']['fps_visualizer'] == viz
    assert settings['optimization']['fps_ui'] == ui
    assert settings['optimization']['blur_quality'] == blur
    assert settings['optimization']['glow_quality'] == glow
    assert settings['optimization']['resource_blur'] is enabled
    assert settings['optimization']['resource_particles'] is enabled
    assert settings['ui']['particles_enabled'] is enabled
    assert settings['theme']['glass_blur'] == glass
    assert settings['theme']['theme'] == 'mint'
    assert settings['theme']['theme_mode'] == 'dark'
    assert settings['theme']['custom_palette_enabled'] is False
    assert settings['audio']['output_device'] == 'headphones'
    assert settings['audio']['crossfade_enabled'] is True
    assert settings['audio']['volume_normalization'] is True
    assert settings['general']['minimize_to_tray'] is False
    assert settings['general']['first_launch_done'] is True
    assert settings['personalization']['onboarding_completed'] is True


def test_skip_preserves_preferences(api, settings_stub):
    for category,key,value in [('theme','theme','ocean'),('ui','particles_enabled',False),
                               ('optimization','performance_preset','low'),('audio','crossfade_enabled',True),
                               ('general','autostart',True),('theme','custom_palette_enabled',True)]:
        settings_stub.set(category,key,value)
    previous = copy.deepcopy(settings_stub._d)
    assert api.complete_onboarding({})['success'] is True
    for key,value in previous.items():
        assert settings_stub._d[key] == value
    assert len(settings_stub._d) == len(previous)+2


@pytest.mark.parametrize('payload', [None, [], {'theme':'missing'}, {'theme_mode':'invalid'},
    {'performance_preset':'turbo'}, {'crossfade_enabled':'false'}, {'autostart':1},
    {'audio_device':''}, {'audio_device':[]}, {'accent_color':'red'}])
def test_invalid_choices_do_not_complete_or_write_settings(api, settings_stub, payload):
    assert api.complete_onboarding(payload)['success'] is False
    assert settings_stub._d == {}


@pytest.mark.parametrize('mode', ['dark','light','system'])
def test_legacy_mode_uses_canonical_theme_mode_key(api, mode):
    result=api.complete_onboarding({'theme_mode':mode})
    assert result['success'] is True
    assert result['settings']['theme']['theme_mode'] == mode
    assert result['settings']['theme']['mode'] == mode


def test_storage_failure_never_marks_done(api, settings_stub):
    settings_stub.sync_flush_now = lambda: False
    result = api.complete_onboarding({'performance_preset':'balanced'})
    assert result['success'] is False
    assert settings_stub.get('general','first_launch_done',False) is False
    assert settings_stub.get('personalization','onboarding_completed',False) is False


def test_completion_flush_failure_restores_flags(api, settings_stub):
    results=iter([True,False])
    settings_stub.sync_flush_now=lambda:next(results)
    assert api.complete_onboarding({})['success'] is False
    assert settings_stub.get('general','first_launch_done') is False
    assert settings_stub.get('personalization','onboarding_completed') is False


def test_autostart_failure_is_visible_and_can_be_retried(api, settings_stub, monkeypatch):
    monkeypatch.setattr(api,'update_autostart',lambda enabled:False)
    assert api.complete_onboarding({'autostart':True})['success'] is False
    assert settings_stub.get('general','first_launch_done',False) is False
    assert api.complete_onboarding({'autostart':False})['success'] is True


def test_onboarding_is_on_disk_before_success(tmp_db, redirect_home):
    manager=SettingsManager(tmp_db)
    api=AppApi(SimpleNamespace(settings=manager))
    try:
        assert api.complete_onboarding({'theme':'light','performance_preset':'balanced'})['success'] is True
        restored=SettingsManager(tmp_db)
        try:
            assert restored.get('general','first_launch_done') is True
            assert restored.get('personalization','onboarding_completed') is True
            assert restored.get('theme','theme') == 'light'
            assert restored.get('theme','theme_mode') == 'light'
            assert restored.get('optimization','fps_ui') == 45
        finally:
            restored.sync_flush_now()
    finally:
        manager.sync_flush_now()


def test_source_interface_and_download_choices_survive_restart(tmp_db, redirect_home):
    manager = SettingsManager(tmp_db)
    api = AppApi(SimpleNamespace(settings=manager))
    result = api.complete_onboarding({'ui_style': 'macos', 'theme': 'light',
        'sources': {'youtube': False, 'soundcloud': True},
        'download_format': 'mp3', 'download_quality': '192'})
    assert result['success'] is True
    restored = SettingsManager(tmp_db)
    assert restored.get('interface', 'ui_style') == 'macos'
    assert restored.get('interface', 'macos_mode') == 'light'
    assert restored.get('services', 'youtube_enabled') is False
    assert restored.get('services', 'soundcloud_enabled') is True
    assert restored.get('downloads', 'format') == 'mp3'
    assert restored.get('downloads', 'quality') == '192'
    assert restored.get('general', 'first_launch_done') is True


@pytest.mark.parametrize('payload', [
    {'ui_style': 'other'}, {'ui_style': []}, {'sources': []},
    {'sources': {'youtube': 'false'}}, {'sources': {'unexpected': True}},
    {'download_format': 'exe'}, {'download_quality': 320}, {'download_quality': 'unlimited'},
])
def test_invalid_extended_preferences_never_write_or_complete(api, settings_stub, payload):
    assert api.complete_onboarding(payload)['success'] is False
    assert settings_stub._d == {}


def test_local_only_sources_are_a_supported_choice(api, settings_stub):
    result = api.complete_onboarding({'sources': {'youtube': False, 'soundcloud': False}})
    assert result['success'] is True
    assert settings_stub.get('services', 'youtube_enabled') is False
    assert settings_stub.get('services', 'soundcloud_enabled') is False
