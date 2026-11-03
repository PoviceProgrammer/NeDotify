"""Real AppApi -> SettingsManager -> SQLite durability; no settings DB doubles."""
import pytest

from core.database import DatabaseManager
from core.settings import DEFAULT_SETTINGS, SettingsManager


RANGES = [
    ('theme', 'font_size', 12, 22), ('interface', 'macos_font_size', 12, 22),
    ('theme', 'glass_blur', 0, 40), ('interface', 'macos_blur', 0, 40),
    ('theme', 'transparency_level', 10, 100), ('interface', 'border_radius', 0, 24),
    ('player', 'progress_transparency', 0, 80), ('theme', 'bg_blur', 0, 16),
    ('theme', 'bg_dim', 0, 90), ('audio', 'crossfade_duration_sec', 1, 12),
    ('efficiency', 'unfocus_fps_limit', 5, 30), ('optimization', 'fps_particles', 5, 30),
    ('optimization', 'fps_visualizer', 10, 60), ('optimization', 'fps_ui', 15, 60),
]


@pytest.mark.parametrize('category,key,low,high', RANGES)
def test_range_extremes_survive_independent_sqlite_reopen(api, core_ns, tmp_path, category, key, low, high):
    filename = tmp_path / 'range-persistence.db'
    db = DatabaseManager(str(filename))
    manager = SettingsManager(db)
    core_ns.settings = manager
    try:
        for value in (low, high, low):
            assert api.save_setting(key, value, category) is True
            # Open another connection before closing/flushing the writer: acknowledgement is durable.
            reader_db = DatabaseManager(str(filename))
            reader = SettingsManager(reader_db)
            try:
                assert reader.get(category, key) == value
                assert api.get_settings(category)[key] == value
            finally:
                reader.close(); reader_db.close()
    finally:
        manager.close(); db.close()


def test_all_atmosphere_numeric_settings_survive_sqlite_reopen(api, core_ns, tmp_path):
    filename = tmp_path / 'atmosphere-persistence.db'
    db = DatabaseManager(str(filename)); manager = SettingsManager(db); core_ns.settings = manager
    config = DEFAULT_SETTINGS['atmosphere']
    writes = 0
    try:
        for key, initial in config.items():
            if isinstance(initial, bool):
                continue
            if isinstance(initial, (int, float)):
                value = initial * .9
            elif isinstance(initial, dict):
                value = {name: child * .9 if isinstance(child, (int, float)) and not isinstance(child, bool) and name != 'depth' else child for name, child in initial.items()}
            else:
                continue
            assert api.save_setting(key, value, 'atmosphere') is True
            reader_db = DatabaseManager(str(filename)); reader = SettingsManager(reader_db)
            try:
                assert reader.get('atmosphere', key) == api.get_settings('atmosphere')[key]
                writes += 1
            finally:
                reader.close(); reader_db.close()
        assert writes >= 10
    finally:
        manager.close(); db.close()


def test_equalizer_gains_and_six_band_layout_are_durable_on_acknowledgement(api, core_ns, tmp_path, monkeypatch):
    filename = tmp_path / 'equalizer-persistence.db'
    db = DatabaseManager(str(filename)); manager = SettingsManager(db); core_ns.settings = manager
    try:
        bands = [-20, -12.5, -8, -2.5, 0, .5, 2.5, 8, 12.5, 20]
        assert api.set_equalizer(2.5, bands, 6) is True
        reader_db = DatabaseManager(str(filename)); reader = SettingsManager(reader_db)
        try:
            assert reader.get('equalizer', 'preamp') == 2.5
            assert reader.get('equalizer', 'bands') == bands
            assert reader.get('equalizer', 'mode') == '6'
        finally:
            reader.close(); reader_db.close()
        before = api.get_equalizer()
        with monkeypatch.context() as failure:
            failure.setattr(manager, 'sync_flush_now', lambda: False)
            assert api.set_equalizer(10, [0] * 10, 3) is False
            assert api.get_equalizer() == before
    finally:
        manager.close(); db.close()
