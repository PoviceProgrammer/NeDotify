"""Routing regressions in core/proxy.py: unknown paths, HEAD, cover roots.

* P0-2 - only /, /api/cover, /api/avatar and /api/stream are served; anything
  else must be a 404 and must NOT reach engine.resolve_stream_url().
* P2-10 - do_HEAD exists, mirrors GET's headers with no body, and goes through
  the same authentication gate.
* P2-1 - _cover_roots() only offers roots that actually exist.
"""
import os
import sys

from tests.test_proxy_harness import (
    PROXY_TOKEN, nedotify_home, app_core, proxy_factory, proxy, qs, write_bytes,
)
from core import proxy as proxy_module


JPG = b'\xff\xd8\xff\xe0' + b'cover-bytes' * 8
MP3 = b'ID3\x00\x01' + b'audio-bytes' * 64


# --- P0-2: unknown paths --------------------------------------------------

def test_unknown_path_is_404_without_touching_the_resolver(proxy, nedotify_home, app_core):
    """The catch-all branch resolved with empty metadata.

    do_GET's final else passed source_id=''/title=''/artist='' to
    engine.resolve_stream_url(), which for SoundCloud builds sc_target='' and
    performs a real request while blocking the thread on event.wait(15).
    """
    for path in ('/favicon.ico', '/api/unknown', '/api/streamX', '/nope/deep/path'):
        resp = proxy.get('/{}'.format(path) + '?' + qs(k=PROXY_TOKEN))
        assert resp.status == 404, (path, resp.status)
        assert app_core.engine.calls == [], (path, app_core.engine.calls)


def test_unknown_path_with_stream_params_is_still_404(proxy, app_core):
    """Even a request that looks stream-ish must not reach the resolver."""
    resp = proxy.get('/whatever?' + qs(k=PROXY_TOKEN, url='https://example.invalid/x', source='soundcloud'))
    assert resp.status == 404
    assert app_core.engine.calls == []


def test_root_path_still_proxies(proxy, app_core):
    """'/' is the generic proxy endpoint emitted by get_proxy_url() and
    engine._notify_track_changed() - it must keep working.

    It must be given real track metadata, exactly like engine.py does when it
    builds `http://127.0.0.1:<port>/?url=...&source=...&source_id=...`. A request
    carrying no metadata at all is refused with 400 before the resolver runs -
    see test_root_path_without_metadata_does_not_reach_resolver.
    """
    assert '/' in proxy_module.KNOWN_PROXY_PATHS
    resp = proxy.get('/?' + qs(k=PROXY_TOKEN, source='soundcloud', source_id='12345'))
    assert resp.status != 404
    # The stub resolver answered '' -> do_GET reports "could not resolve".
    assert resp.status == 400
    assert app_core.engine.calls, "the '/' branch must still reach the resolver"
    # ...and it must be reached with the metadata we supplied, not blanks.
    assert app_core.engine.calls[0].get('source_id') == '12345'


def test_root_path_without_metadata_does_not_reach_resolver(proxy, app_core):
    """Regression: '/' with no url and no metadata must not hit the network.

    Falling through to engine.resolve_stream_url with empty source/source_id
    made the SoundCloud branch perform a real round trip on a blank id and block
    the request thread for up to 15s.
    """
    app_core.engine.calls.clear()
    resp = proxy.get('/?' + qs(k=PROXY_TOKEN))
    assert app_core.engine.calls == [], (
        "empty '/' request reached the resolver: "
        f"{app_core.engine.calls!r}"
    )
    assert resp.status == 400


def test_known_endpoints_still_served(proxy, nedotify_home, app_core):
    cover = write_bytes(os.path.join(nedotify_home, 'covers', 'c.jpg'), JPG)
    avatar = write_bytes(os.path.join(nedotify_home, 'avatars', 'a.png'), JPG)
    audio = write_bytes(os.path.join(nedotify_home, 'streams', 'managed.mp3'), MP3)

    assert proxy.get('/api/cover?' + qs(path=cover, k=PROXY_TOKEN)).body == JPG
    assert proxy.get('/api/avatar?' + qs(path=avatar, k=PROXY_TOKEN)).body == JPG
    # A managed-root audio file needs no library row.
    resp = proxy.get('/api/stream?' + qs(url=audio, k=PROXY_TOKEN))
    assert resp.status == 200 and resp.body == MP3
    assert app_core.engine.calls == []


# --- P2-10: do_HEAD -------------------------------------------------------

def test_head_returns_get_headers_without_a_body(proxy, nedotify_home):
    cover = write_bytes(os.path.join(nedotify_home, 'covers', 'c.jpg'), JPG)
    path = '/api/cover?' + qs(path=cover, k=PROXY_TOKEN)

    head = proxy.head(path)
    get = proxy.get(path)
    assert head.status == get.status == 200
    assert head.body == b''
    assert head.header('Content-Length') == str(len(JPG))
    assert head.header('Accept-Ranges') == 'bytes'
    assert head.header('Content-Type') == get.header('Content-Type')


def test_head_honours_range_headers(proxy, nedotify_home):
    audio = write_bytes(os.path.join(nedotify_home, 'streams', 'managed.mp3'), MP3)
    path = '/api/stream?' + qs(url=audio, k=PROXY_TOKEN)

    head = proxy.head(path, headers={'Range': 'bytes=10-19'})
    assert head.status == 206
    assert head.header('Content-Range') == 'bytes 10-19/{}'.format(len(MP3))
    assert head.header('Content-Length') == '10'
    assert head.body == b''


def test_head_is_not_the_501_default_anymore(proxy, nedotify_home):
    """CORS advertises HEAD, but the handler had no do_HEAD."""
    avatar = write_bytes(os.path.join(nedotify_home, 'avatars', 'a.png'), JPG)
    resp = proxy.head('/api/avatar?' + qs(path=avatar, k=PROXY_TOKEN))
    assert resp.status != 501


def test_head_enforces_authentication(proxy, nedotify_home, proxy_factory):
    cover = write_bytes(os.path.join(nedotify_home, 'covers', 'c.jpg'), JPG)

    assert proxy.head('/api/cover?' + qs(path=cover)).status == 403
    assert proxy.head('/api/cover?' + qs(path=cover, k='wrong-token')).status == 403
    assert proxy.head('/api/cover?' + qs(path=cover, k=PROXY_TOKEN)).status == 200

    tokenless = proxy_factory(token='')
    assert tokenless.head('/api/cover?' + qs(path=cover)).status == 403
    assert tokenless.head('/api/cover?' + qs(path=cover, k='')).status == 403


def test_head_on_unknown_path_is_404(proxy):
    assert proxy.head('/favicon.ico?' + qs(k=PROXY_TOKEN)).status == 404


def test_head_on_missing_local_file_is_404(proxy, nedotify_home):
    resp = proxy.head('/api/stream?' + qs(url=os.path.join(nedotify_home, 'streams', 'gone.mp3'), k=PROXY_TOKEN))
    assert resp.status == 404


# --- P2-1: cover roots ----------------------------------------------------

def test_cover_roots_only_offer_existing_directories(nedotify_home, monkeypatch, tmp_path):
    """ui/web_new*/covers do not exist in the repo.

    They were appended unconditionally, so every cover request paid two extra
    realpath() calls for roots that can never match a file.
    """
    bundle = tmp_path / 'bundle'
    monkeypatch.setattr(sys, '_MEIPASS', str(bundle), raising=False)
    monkeypatch.delattr(sys, '_MEIPASS')

    roots = proxy_module._cover_roots()
    assert roots, 'the nedotify roots must survive'
    assert all(os.path.isdir(r) for r in roots), roots
    assert not any(r.endswith(os.path.join('web_new', 'covers')) for r in roots)
    assert not any(r.endswith(os.path.join('web_new_v2', 'covers')) for r in roots)


def test_cover_roots_include_a_bundled_covers_dir_when_present(nedotify_home, monkeypatch, tmp_path):
    bundled = tmp_path / 'bundle' / 'ui' / 'web_new' / 'covers'
    os.makedirs(bundled)
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path / 'bundle'), raising=False)

    roots = proxy_module._cover_roots()
    assert os.path.realpath(str(bundled)) in [os.path.realpath(r) for r in roots]
    assert all(os.path.isdir(r) for r in roots)


def test_cover_roots_keep_the_nedotify_tree(nedotify_home):
    roots = [os.path.realpath(r) for r in proxy_module._cover_roots()]
    assert os.path.realpath(os.path.join(nedotify_home, 'covers')) in roots
    assert os.path.realpath(os.path.join(nedotify_home, 'avatars')) in roots