"""Range handling in serve_local_file (P1-1).

The old parser read the field positionally:
``range_header.replace('bytes=','').split('-')``, then clamped
``start = max(0, min(start, end))``. Consequences:
``bytes=-500`` (what HTML5 audio sends for "give me the tail") was answered as
0-500, an unsatisfiable range was silently rewritten into a different one
instead of 416, and an unparsable range produced a 500.
"""
import os

from tests.test_proxy_harness import (
    PROXY_TOKEN, nedotify_home, app_core, proxy_factory, proxy,
    offline_handler, qs, write_bytes,
)
from core.proxy import _parse_byte_range


PAYLOAD = bytes(bytearray(range(256))) * 4  # 1024 deterministic bytes


def _stream_url(nedotify_home, name='managed.mp3'):
    return write_bytes(os.path.join(nedotify_home, 'streams', name), PAYLOAD)


# --- parser unit tests ----------------------------------------------------

def test_parse_byte_range_closed_and_open_ended():
    assert _parse_byte_range('bytes=0-99', 1024) == ('range', 0, 99)
    assert _parse_byte_range('bytes=100-', 1024) == ('range', 100, 1023)
    assert _parse_byte_range('bytes=0-', 1024) == ('range', 0, 1023)
    # end beyond EOF is clamped, which RFC 7233 allows.
    assert _parse_byte_range('bytes=1000-9999', 1024) == ('range', 1000, 1023)


def test_parse_byte_range_suffix_form():
    assert _parse_byte_range('bytes=-500', 1024) == ('range', 524, 1023)
    # A suffix larger than the entity yields the whole entity.
    assert _parse_byte_range('bytes=-99999', 1024) == ('range', 0, 1023)
    assert _parse_byte_range('bytes=-0', 1024) == ('invalid', None, None)


def test_parse_byte_range_rejects_unsatisfiable():
    assert _parse_byte_range('bytes=1024-', 1024) == ('invalid', None, None)
    assert _parse_byte_range('bytes=2048-3000', 1024) == ('invalid', None, None)
    assert _parse_byte_range('bytes=100-50', 1024) == ('invalid', None, None)
    assert _parse_byte_range('bytes=0-', 0) == ('invalid', None, None)


def test_parse_byte_range_ignores_unusable_headers():
    for header in (None, '', 'items=0-10', 'bytes=', 'bytes=abc-def', 'bytes=--5',
                   'bytes=0-100,200-300', 'bytes=-'):
        assert _parse_byte_range(header, 1024) == ('full', 0, 1023), header


# --- end-to-end over the socket -------------------------------------------

def test_suffix_range_returns_the_tail(proxy, nedotify_home):
    """HTML5 audio asks for the last N bytes; it used to get 0-N instead."""
    url = _stream_url(nedotify_home)
    resp = proxy.get('/api/stream?' + qs(url=url, k=PROXY_TOKEN),
                     headers={'Range': 'bytes=-500'})
    assert resp.status == 206
    assert resp.header('Content-Range') == 'bytes 524-1023/1024'
    assert resp.header('Content-Length') == '500'
    assert resp.body == PAYLOAD[524:]


def test_open_ended_range_returns_the_rest(proxy, nedotify_home):
    url = _stream_url(nedotify_home)
    resp = proxy.get('/api/stream?' + qs(url=url, k=PROXY_TOKEN),
                     headers={'Range': 'bytes=100-'})
    assert resp.status == 206
    assert resp.header('Content-Range') == 'bytes 100-1023/1024'
    assert resp.body == PAYLOAD[100:]


def test_closed_range_returns_the_slice(proxy, nedotify_home):
    url = _stream_url(nedotify_home)
    resp = proxy.get('/api/stream?' + qs(url=url, k=PROXY_TOKEN),
                     headers={'Range': 'bytes=0-9'})
    assert resp.status == 206
    assert resp.header('Content-Range') == 'bytes 0-9/1024'
    assert resp.body == PAYLOAD[:10]


def test_bytes_zero_dash_still_answers_206(proxy, nedotify_home):
    """The proxy frontend sends `bytes=0-`; stream caching depends on that
    request still being answered as a full-entity 206."""
    url = _stream_url(nedotify_home)
    resp = proxy.get('/api/stream?' + qs(url=url, k=PROXY_TOKEN),
                     headers={'Range': 'bytes=0-'})
    assert resp.status == 206
    assert resp.header('Content-Range') == 'bytes 0-1023/1024'
    assert resp.header('Accept-Ranges') == 'bytes'
    assert resp.body == PAYLOAD


def test_plain_get_is_unchanged(proxy, nedotify_home):
    url = _stream_url(nedotify_home)
    resp = proxy.get('/api/stream?' + qs(url=url, k=PROXY_TOKEN))
    assert resp.status == 200
    assert resp.header('Content-Length') == str(len(PAYLOAD))
    assert resp.header('Accept-Ranges') == 'bytes'
    assert resp.body == PAYLOAD


def test_unsatisfiable_range_answers_416(proxy, nedotify_home):
    url = _stream_url(nedotify_home)
    for header in ('bytes=100-50', 'bytes=1024-', 'bytes=99999-100000'):
        resp = proxy.get('/api/stream?' + qs(url=url, k=PROXY_TOKEN),
                         headers={'Range': header})
        assert resp.status == 416, (header, resp.status)
        assert resp.header('Content-Range') == 'bytes */1024', header


def test_multi_range_is_ignored_and_whole_file_served(proxy, nedotify_home):
    url = _stream_url(nedotify_home)
    resp = proxy.get('/api/stream?' + qs(url=url, k=PROXY_TOKEN),
                     headers={'Range': 'bytes=0-100,200-300'})
    assert resp.status == 200
    assert resp.body == PAYLOAD


def test_garbage_range_is_ignored_not_500(proxy, nedotify_home):
    url = _stream_url(nedotify_home)
    resp = proxy.get('/api/stream?' + qs(url=url, k=PROXY_TOKEN),
                     headers={'Range': 'bytes=abc-def'})
    assert resp.status == 200
    assert resp.body == PAYLOAD


# --- the unguarded os.path.getsize() --------------------------------------

def test_missing_file_answers_404(app_core, tmp_path):
    """A file can vanish between the caller's isfile() check and the open();
    unguarded, getsize() turned that race into a 500."""
    handler = offline_handler(app_core)
    handler.serve_local_file(str(tmp_path / 'vanished.mp3'))
    raw = handler.wfile.getvalue()
    assert raw.startswith(b'HTTP/1.'), raw[:80]
    assert b' 404 ' in raw.split(b'\r\n', 1)[0], raw.split(b'\r\n', 1)[0]


def test_missing_file_with_range_answers_404(app_core, tmp_path):
    handler = offline_handler(app_core, headers={'Range': 'bytes=0-10'})
    handler.serve_local_file(str(tmp_path / 'vanished.mp3'))
    assert b' 404 ' in handler.wfile.getvalue().split(b'\r\n', 1)[0]