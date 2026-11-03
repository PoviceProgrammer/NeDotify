"""Durable atmosphere settings, explicit opt-ins and lossless legacy migration."""
import pytest

from core.settings import SettingsManager


def test_new_profiles_do_not_enable_weather_thunder_or_discord(tmp_db):
    manager = SettingsManager(tmp_db)
    try:
        assert manager.get('atmosphere', 'enabled') is False
        assert manager.get('atmosphere', 'storm')['thunder'] is False
        assert manager.get('app', 'discord_rpc_enabled') is False
        assert manager.get('general', 'minimize_to_tray') is False
    finally:
        manager.close()


@pytest.mark.parametrize('enabled,resource,expected', [(True,True,True), (True,False,False), (False,True,False)])
def test_particle_profile_migrates_once_and_retains_unknown_values(tmp_db, enabled, resource, expected):
    for key, value in {'ui.particles_enabled':enabled, 'optimization.resource_particles':resource,
                       'ui.particles_count':64, 'ui.particles_shape':'snow', 'ui.extension_value':{'keep':1},
                       'app.discord_rpc_enabled':True}.items():
        tmp_db.set_setting(key,value)
    manager = SettingsManager(tmp_db)
    try:
        assert manager.get('atmosphere', 'enabled') is expected
        assert manager.get('optimization','resource_particles') is expected
        assert manager.get('atmosphere', 'effects')['snow'] is True
        assert manager.get('atmosphere', 'intensity') == .8
        assert manager.get('ui','extension_value') == {'keep':1}
        assert manager.get('app','discord_rpc_enabled') is True
        manager.set('atmosphere','intensity',.23)
        assert manager.sync_flush_now()
    finally:
        manager.close()
    restored = SettingsManager(tmp_db)
    try:
        assert restored.get('atmosphere','intensity') == .23
        assert restored.get('ui','particles_count') == 64
        assert restored.get('ui','extension_value') == {'keep':1}
    finally:
        restored.close()


def test_atmosphere_bridge_persists_effects_and_syncs_legacy_resource_aliases(api, core_ns, tmp_db):
    manager = SettingsManager(tmp_db); core_ns.settings=manager
    try:
        assert api.save_setting('enabled',True,'atmosphere')
        assert api.save_setting('effects',{'rain':True,'fog':True,'snow':False,'thunderstorm':True},'atmosphere')
        assert manager.get('ui','particles_enabled') is True
        assert manager.get('optimization','resource_particles') is True
        assert tmp_db.get_setting('atmosphere.enabled') is True
        assert tmp_db.get_setting('atmosphere.effects')['fog'] is True
        assert api.save_setting('intensity',float('nan'),'atmosphere') is False
        assert api.save_setting('enabled','false','atmosphere') is False
        assert api.save_setting('quality','unlimited','atmosphere') is False
        assert api.save_setting('storm',{'interval':0},'atmosphere') is False
        assert api.save_setting('fog',{'tint':'url(secret)'},'atmosphere') is False
        assert api.save_setting('fog',{'speed':.1},'atmosphere')
        assert manager.get('atmosphere','fog')['density'] == .35
        manager.set('atmosphere','rain',{'speed':1,'future_extension':{'keep':1}})
        assert api.save_setting('rain',{'speed':2,'future_extension':{'keep':1}},'atmosphere')
        assert manager.get('atmosphere','rain')['future_extension']=={'keep':1}
    finally:
        manager.close()
