"""Hermetic Linux adapter contracts; no desktop/native-success claim."""
import base64
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tarfile

import pytest


def test_xdg_autostart_preserves_other_entries(tmp_path, monkeypatch):
    from core import linux_integration as linux
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    monkeypatch.setattr(linux, 'application_command', lambda: ['/opt/Music Player/NeDotify', 'arg%with$quote"'])
    directory = tmp_path / 'autostart'
    directory.mkdir()
    unrelated = directory / 'other.desktop'
    unrelated.write_text('keep')
    assert linux.update_autostart(True)
    text = (directory / 'nedotify.desktop').read_text()
    assert '"/opt/Music Player/NeDotify"' in text
    assert 'arg%%with\\$quote\\"' in text
    assert linux.update_autostart(False)
    assert not (directory / 'nedotify.desktop').exists()
    assert unrelated.read_text() == 'keep'


def test_frozen_autostart_uses_stable_installed_launcher(tmp_path, monkeypatch):
    from core import linux_integration as linux
    data = tmp_path / 'data'
    app = data / 'nedotify-app'
    executable = app / 'releases' / 'version1' / 'NeDotify'
    executable.parent.mkdir(parents=True)
    executable.touch()
    (app / '.managed').write_text('nedotify.linux.install.v1')
    launcher = tmp_path / '.local' / 'bin' / 'nedotify'
    launcher.parent.mkdir(parents=True)
    launcher.touch()
    monkeypatch.setattr(linux.Path, 'home', lambda: tmp_path)
    monkeypatch.setenv('XDG_DATA_HOME', str(data))
    monkeypatch.setattr(linux.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(linux.sys, 'executable', str(executable))
    assert linux.application_command() == [str(launcher)]


def test_file_secret_fallback_is_authenticated_and_survives_restart(tmp_path, monkeypatch):
    pytest.importorskip('cryptography')
    from core import secret_store
    monkeypatch.setattr(secret_store.Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(secret_store, '_keyring', lambda: (_ for _ in ()).throw(RuntimeError('locked')))
    secret = 'token-Яндекс-123'
    encrypted = secret_store.encrypt(secret)
    assert encrypted.startswith(secret_store.FILE_PREFIX)
    assert secret not in encrypted
    assert secret_store.decrypt(encrypted) == secret
    assert secret_store.encrypt(encrypted) == encrypted
    payload = encrypted[len(secret_store.FILE_PREFIX):]
    decoded = bytearray(base64.urlsafe_b64decode(payload))
    decoded[-1] ^= 1
    corrupt = secret_store.FILE_PREFIX + base64.urlsafe_b64encode(decoded).decode()
    assert secret_store.decrypt(corrupt) == ''
    assert secret_store.decrypt(encrypted) == secret


def test_secret_service_sqlite_value_contains_only_reference(monkeypatch):
    from core import secret_store
    values = {}
    backend = SimpleNamespace(set_password=lambda service, key, value: values.update({(service, key): value}),
                              get_password=lambda service, key: values.get((service, key)))
    monkeypatch.setattr(secret_store, '_keyring', lambda: backend)
    encrypted = secret_store.encrypt('private-token')
    assert encrypted.startswith(secret_store.KEYRING_PREFIX)
    assert 'private-token' not in encrypted
    assert secret_store.decrypt(encrypted) == 'private-token'
    assert len(values) == 1


def test_locked_keyring_does_not_replace_database_ciphertext(tmp_path, monkeypatch):
    from core import secret_store
    from core.database import DatabaseManager
    encrypted = secret_store.KEYRING_PREFIX + 'a' * 64
    monkeypatch.setattr(secret_store, '_keyring', lambda: (_ for _ in ()).throw(RuntimeError('locked')))
    db = DatabaseManager(str(tmp_path / 'test.db'))
    try:
        db.conn.execute("INSERT OR REPLACE INTO settings(key,value,category) VALUES ('auth.yandex_token',?,'auth')", (encrypted,))
        db.conn.commit()
        assert db.get_setting('auth.yandex_token') == ''
        assert db.conn.execute("SELECT value FROM settings WHERE key='auth.yandex_token'").fetchone()[0] == encrypted
    finally:
        db.close()


@pytest.mark.parametrize('architecture,expected', [('x86_64', 'linux64'), ('aarch64', 'linuxarm64')])
def test_setup_selects_linux_native_assets(monkeypatch, architecture, expected):
    from core import setup_engine
    monkeypatch.setattr(setup_engine.sys, 'platform', 'linux')
    monkeypatch.setattr(setup_engine.platform, 'machine', lambda: architecture)
    assert setup_engine.SetupEngine._asset_name('ffmpeg') == f'ffmpeg-master-latest-{expected}-gpl.tar.xz'
    assert not setup_engine.SetupEngine._asset_name('yt_dlp').endswith('.exe')


def test_unsupported_linux_architecture_is_actionable(monkeypatch):
    from core import setup_engine
    monkeypatch.setattr(setup_engine.sys, 'platform', 'linux')
    monkeypatch.setattr(setup_engine.platform, 'machine', lambda: 'riscv64')
    with pytest.raises(setup_engine.SetupDependencyError) as error:
        setup_engine.SetupEngine._asset_name('ffmpeg')
    assert error.value.code == 'unsupported_architecture'


def test_native_linux_mini_player_never_imports_winforms(monkeypatch):
    from core import api
    monkeypatch.setattr(api.sys, 'platform', 'linux')
    class Native:
        def isMaximized(self): return False
        def setMinimumSize(self, *size): self.minimum = size
    calls = []
    window = SimpleNamespace(native=Native(), restore=lambda: calls.append('restore'),
        resize=lambda *size: calls.append(size), on_top=False, width=1280, height=800, x=10, y=20)
    instance = api.AppApi.__new__(api.AppApi)
    import threading
    instance._window_op_lock = threading.RLock()
    instance._window = window
    instance._mini_window = None
    instance._is_mini_active = False
    instance._saved_mini_pos = 'bottom-right'
    instance._on_window_ui_thread = lambda target, fn: fn()
    instance._emit = lambda *args: None
    instance._native_window_geometry = lambda target: (1280, 800, 10, 20)
    instance._apply_window_pos = lambda *args: None
    instance._native_move_window = lambda *args: None
    assert instance.toggle_mini_player(True)['success']
    assert instance._is_mini_active
    assert window.native.minimum == (1, 1)
    assert instance.toggle_mini_player(False)['success']
    assert not instance._is_mini_active
    assert window.native.minimum == api.MAIN_WINDOW_MIN_SIZE
    assert (1280, 800) in calls


def test_system_transport_dispatches_to_frontend_without_tray():
    from core.linux_integration import LinuxDesktopIntegration
    code = []
    api = SimpleNamespace(_window=SimpleNamespace(evaluate_js=code.append))
    desktop = LinuxDesktopIntegration(api)
    try:
        desktop._system_event('seek', 1234)
        assert 'nedotify:system_media' in code[0]
        assert '1234' in code[0]
        assert '"action": "seek"' in code[0]
    finally:
        desktop.stop()


def test_mpris_interfaces_export_correct_units_and_transport():
    pytest.importorskip('dbus_next')
    from core.mpris import create_interfaces
    commands = []
    values = {'track': {'title': 'Song', 'artist': 'Artist'}, 'track_id': '/track/one',
              'duration': 60_000_000, 'position': 5_000_000, 'state': 'Playing', 'shuffle': False,
              'repeat': 'all', 'volume': .7}
    desktop = SimpleNamespace(snapshot=lambda: values, dispatch=lambda *args: commands.append(args))
    root, player = create_interfaces(desktop)
    assert root.introspect().name == 'org.mpris.MediaPlayer2'
    assert player.Position == 5_000_000
    assert player.Metadata['mpris:length'].value == 60_000_000
    assert player.LoopStatus == 'Playlist'
    # dbus-next decorated wrappers publish a signal but preserve the method
    # implementation in __wrapped__ for local service dispatch tests.
    player.Seek.__wrapped__(player, 2_000_000)
    assert commands[-1] == ('seek', 7000.0)
    player.Volume = .42
    assert commands[-1] == ('volume', 42)
    player.SetPosition.__wrapped__(player, '/track/stale', 3_000_000)
    assert commands[-1] == ('volume', 42)


def test_linux_zapret_rejects_windows_arguments_without_launch(tmp_path):
    from services.linux_zapret import LinuxZapretService
    service = LinuxZapretService()
    service.app_dir = str(tmp_path)
    success, message = service.start(custom_args='--dpi-desync=fake --wf-tcp=443')
    assert not success
    assert 'tpws' in message
    assert service.process is None


def test_linux_zapret_stop_owns_only_its_child():
    from services.linux_zapret import LinuxZapretService
    from utils.linux_proxy import endpoint, set_endpoint
    calls = []
    process = SimpleNamespace(poll=lambda: None, terminate=lambda: calls.append('terminate'), wait=lambda timeout: calls.append('wait'))
    service = LinuxZapretService()
    service.process = process
    set_endpoint(12345)
    assert service.stop()[0]
    assert calls == ['terminate', 'wait']
    assert endpoint() is None
    assert service.process is None


def test_zapret_runtime_proxy_does_not_overwrite_user_proxy():
    from services.base_service import normalize_proxy_url
    from utils.linux_proxy import set_endpoint
    try:
        set_endpoint(12345)
        assert normalize_proxy_url('') == 'socks5h://127.0.0.1:12345'
        assert normalize_proxy_url('http://user.example:8080') == 'http://user.example:8080'
    finally:
        set_endpoint(None)
