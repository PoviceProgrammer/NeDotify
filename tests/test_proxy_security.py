"""Security regressions in core/proxy.py (P2-11).

(a) /api/stream served ANY absolute path it could open - no extension
    allow-list, no root. A holder of the proxy token could read any file on
    disk (.env, .txt, keys). A local library may live in any folder, so the
    gate is "managed app root OR referenced by a tracks row", never a fixed
    folder list.
(b) _authorized() returned True when no token was configured - fail open.
"""
import os

from tests.test_proxy_harness import (
    PROXY_TOKEN, nedotify_home, app_core, proxy_factory, proxy, qs, write_bytes,
)
from core import proxy as proxy_module


SECRET = b'DB_PASSWORD=hunter2\n'
MP3 = b'ID3\x00\x01' + b'audio-bytes' * 32


def _register(db, file_path, title='Local Song', source='local'):
    return db.add_track(
        title=title, artist='A', file_path=file_path, source=source, source_id=f'loc:{title}'
    )


# --- (a) the local-file gate ----------------------------------------------

def test_track_file_path_outside_the_app_root_is_served(proxy, nedotify_home, app_core, tmp_path):
    """An imported library lives wherever the user put it."""
    library = write_bytes(str(tmp_path / 'Music' / 'my song.mp3'), MP3)
    track_id = _register(app_core.db, library)
    assert track_id

    resp = proxy.get('/api/stream?' + qs(url=library, source='local', k=PROXY_TOKEN))
    assert resp.status == 200
    assert resp.body == MP3

    # ... and through the bare ?url= branch the frontend actually uses.
    resp = proxy.get('/api/stream?' + qs(url=library, track_id=track_id, k=PROXY_TOKEN))
    assert resp.status == 200 and resp.body == MP3


def test_file_inside_the_managed_root_is_served_without_a_db_row(proxy, nedotify_home):
    """Stream cache and downloads live under ~/.nedotify and have no row."""
    cached = write_bytes(os.path.join(nedotify_home, 'streams', 'youtube_abc.m4a'), MP3)
    download = write_bytes(os.path.join(nedotify_home, 'downloads', 'x.mp3'), MP3)

    assert proxy.get('/api/stream?' + qs(url=cached, k=PROXY_TOKEN)).body == MP3
    assert proxy.get('/api/stream?' + qs(url=download, k=PROXY_TOKEN)).body == MP3


def test_foreign_text_file_is_refused(proxy, nedotify_home, tmp_path):
    secret = write_bytes(str(tmp_path / 'notes.txt'), SECRET)
    resp = proxy.get('/api/stream?' + qs(url=secret, source='local', k=PROXY_TOKEN))
    assert resp.status in (403, 404)
    assert b'hunter2' not in resp.body


def test_foreign_dotenv_is_refused(proxy, nedotify_home, tmp_path):
    secret = write_bytes(str(tmp_path / '.env'), SECRET)
    for query in (
        qs(url=secret, source='local', k=PROXY_TOKEN),
        qs(file_path=secret, source='local', k=PROXY_TOKEN),
        # Without source=local the request falls through to the stream branch,
        # where the SSRF gate is the backstop - either way, no file content.
        qs(url=secret, k=PROXY_TOKEN),
    ):
        resp = proxy.get('/api/stream?' + query)
        assert resp.status in (400, 403, 404), resp.status
        assert b'hunter2' not in resp.body


def test_foreign_audio_file_is_refused(proxy, nedotify_home, tmp_path):
    """The extension allow-list alone is not enough - any mp3 on the disk
    would still be readable."""
    intruder = write_bytes(str(tmp_path / 'private' / 'other.mp3'), MP3)
    resp = proxy.get('/api/stream?' + qs(url=intruder, source='local', k=PROXY_TOKEN))
    assert resp.status in (403, 404)
    assert MP3 not in resp.body


def test_generic_root_path_refuses_a_foreign_file(proxy, nedotify_home, tmp_path):
    """'/?url=<abs path>' had the same hole and must be closed too."""
    secret = write_bytes(str(tmp_path / 'id_rsa.txt'), SECRET)
    resp = proxy.get('/?' + qs(url=secret, k=PROXY_TOKEN))
    assert resp.status in (400, 403, 404)
    assert b'hunter2' not in resp.body


def test_resolver_returning_a_foreign_path_is_refused(proxy, nedotify_home, app_core, tmp_path):
    """A poisoned resolver result must not reopen the hole."""
    intruder = write_bytes(str(tmp_path / 'injected.mp3'), MP3)
    app_core.engine.result = intruder
    resp = proxy.get('/api/stream?' + qs(source='youtube', source_id='vid1', k=PROXY_TOKEN))
    assert resp.status in (400, 403, 404)
    assert MP3 not in resp.body


def test_traversal_out_of_a_managed_root_is_refused(proxy, nedotify_home, tmp_path):
    """A `..`-laden path that lands outside ~/.nedotify but on a real,
    audio-extension file must not be served."""
    outside = write_bytes(str(tmp_path / 'outside.mp3'), MP3)
    sneaky = os.path.join(nedotify_home, 'streams', '..', '..', '..', 'outside.mp3')
    assert os.path.realpath(sneaky) == os.path.realpath(outside)
    assert os.path.isfile(sneaky), 'the crafted path must exist for this to mean anything'

    resp = proxy.get('/api/stream?' + qs(url=sneaky, source='local', k=PROXY_TOKEN))
    assert resp.status in (403, 404), resp.status
    assert MP3 not in resp.body


def test_safe_stream_local_path_gate(app_core, nedotify_home, tmp_path):
    """Unit view of the gate itself."""
    db = app_core.db
    inside = write_bytes(os.path.join(nedotify_home, 'streams', 'ok.mp3'), MP3)
    listed = write_bytes(str(tmp_path / 'listed.mp3'), MP3)
    unlisted = write_bytes(str(tmp_path / 'unlisted.mp3'), MP3)
    text = write_bytes(str(tmp_path / 'secret.txt'), SECRET)
    wma = write_bytes(str(tmp_path / 'library.wma'), MP3)
    _register(db, listed)
    _register(db, wma, title='WMA Song')

    assert proxy_module._safe_stream_local_path(inside, db) == os.path.realpath(inside)
    assert proxy_module._safe_stream_local_path(listed, db) == os.path.realpath(listed)
    assert proxy_module._safe_stream_local_path(unlisted, db) == ''
    assert proxy_module._safe_stream_local_path(text, db) == ''
    assert proxy_module._safe_stream_local_path('', db) == ''
    assert proxy_module._safe_stream_local_path(os.path.join(nedotify_home, 'streams', 'gone.mp3'), db) == ''


def test_every_format_the_scanner_imports_stays_playable(app_core, nedotify_home, tmp_path):
    """The allow-list must not be narrower than the library itself."""
    from utils.file_scanner import AUDIO_EXTENSIONS as SCANNER_EXTENSIONS

    assert SCANNER_EXTENSIONS <= proxy_module.AUDIO_EXTENSIONS, (
        sorted(SCANNER_EXTENSIONS - proxy_module.AUDIO_EXTENSIONS)
    )
    db = app_core.db
    for ext in sorted(SCANNER_EXTENSIONS):
        path = write_bytes(str(tmp_path / 'lib' / ('song' + ext)), MP3)
        _register(db, path, title=f'Song{ext}')
        assert proxy_module._safe_stream_local_path(path, db) == os.path.realpath(path)


# --- (b) fail-closed authentication ---------------------------------------

def test_configured_token_is_required(proxy, nedotify_home):
    cover = write_bytes(os.path.join(nedotify_home, 'covers', 'c.jpg'), b'jpg-bytes')

    assert proxy.get('/api/cover?' + qs(path=cover, k=PROXY_TOKEN)).status == 200
    assert proxy.get('/api/cover?' + qs(path=cover)).status == 403
    assert proxy.get('/api/cover?' + qs(path=cover, k='nope')).status == 403
    # Legacy alias still honoured.
    assert proxy.get('/api/cover?' + qs(path=cover, auth_token=PROXY_TOKEN)).status == 200


def test_missing_token_fails_closed(proxy_factory, nedotify_home, caplog):
    """`_authorized` used to `return True` when no token was configured,
    turning the loopback port into an unauthenticated reader."""
    tokenless = proxy_factory(token='')
    cover = write_bytes(os.path.join(nedotify_home, 'covers', 'c.jpg'), b'jpg-bytes')

    for path in ('/api/cover?' + qs(path=cover), '/api/avatar?' + qs(path=cover),
                 '/api/stream?' + qs(url=cover), '/?' + qs(url=cover)):
        resp = tokenless.get(path)
        assert resp.status == 403, (path, resp.status)
        assert b'jpg-bytes' not in resp.body

    assert any(record.levelname == 'ERROR' for record in caplog.records)


def test_unknown_path_is_refused_before_authentication_survives(proxy_factory, nedotify_home):
    """A 404 for an unknown path must not leak the token state."""
    tokenless = proxy_factory(token='')
    assert tokenless.get('/favicon.ico').status == 403


def test_local_proxy_manager_always_mints_a_token(monkeypatch):
    """LocalProxyManager.start() generates one before the port is announced,
    so fail-closed cannot break normal playback."""
    import secrets as secrets_module

    seen = {}

    class FakeServer:
        def __init__(self, address, handler, app_core, auth_token=''):
            seen['token'] = auth_token
            seen['address'] = address
            self.server_port = 12345

        def serve_forever(self):
            pass

    monkeypatch.setattr(proxy_module, 'ThreadingHTTPServer', FakeServer)
    monkeypatch.setattr(secrets_module, 'token_urlsafe', lambda n=24: 'minted-token')

    manager = proxy_module.LocalProxyManager(object())
    manager.start()
    assert seen['token'] == 'minted-token'
    assert manager.token == 'minted-token'
    assert manager.auth_query() == '&k=minted-token'
    manager.stop()