"""The privileged UI origin binds before publishing and rejects foreign sites."""
import json
import io
from pathlib import Path
import socket
import urllib.error
import urllib.request
import urllib.parse

import pytest

from core.ui_server import LocalUiServer


@pytest.fixture
def ui_server(tmp_path, monkeypatch):
    from core.ui_assets import install_library_artwork
    monkeypatch.setattr(LocalUiServer, 'route_installer', install_library_artwork)
    page = tmp_path / 'index.html'
    page.write_text('local interface', encoding='utf-8')
    # An occupied requested port must never become the WebView origin.
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1', 0))
        occupied.listen()
        address, root, server = LocalUiServer.start_server([str(page)], occupied.getsockname()[1])
        assert server.port != occupied.getsockname()[1]
        try:
            yield server
        finally:
            server.stop()


def request(url, *, headers=None, data=None):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(urllib.request.Request(url, headers=headers or {}, data=data), timeout=2)


def test_local_ui_is_available_when_start_returns(ui_server):
    with request(ui_server.address) as response:
        assert response.read() == b'local interface'
        assert response.headers['Cache-Control'].startswith('no-store')
        assert response.headers['X-Content-Type-Options'] == 'nosniff'
        assert 'Access-Control-Allow-Origin' not in response.headers


def test_managed_artwork_uses_ui_origin_without_media_bearer(ui_server, tmp_path):
    root = Path.home() / '.nedotify' / 'covers'
    root.mkdir(parents=True, exist_ok=True)
    art = root / 'cover_1.png'
    art.write_bytes(b'\x89PNG\r\n\x1a\nmanaged-image')
    url = ui_server.address + 'api/cover?' + urllib.parse.urlencode({'path': str(art)})
    with request(url) as response:
        assert response.read() == art.read_bytes()
        assert response.headers['Content-Type'].startswith('image/png')
    with pytest.raises(urllib.error.HTTPError) as error:
        request(url, headers={'Sec-Fetch-Site': 'cross-site'})
    assert error.value.code == 403
    external = tmp_path / 'outside.png'
    external.write_bytes(art.read_bytes())
    outside_url = ui_server.address + 'api/cover?' + urllib.parse.urlencode({'path': str(external)})
    with pytest.raises(urllib.error.HTTPError) as error:
        request(outside_url)
    assert error.value.code == 404


@pytest.mark.parametrize('headers', [
    {'Origin': 'https://foreign.example'},
    {'Host': 'foreign.example'},
    {'Sec-Fetch-Site': 'cross-site'},
    {'Sec-Fetch-Site': 'same-site'},  # another loopback port is still a foreign origin
])
def test_foreign_origin_cannot_access_ui_or_bridge(ui_server, headers):
    for url, data in [(ui_server.address, None), (ui_server.js_api_endpoint, b'{}')]:
        with pytest.raises(urllib.error.HTTPError) as error:
            request(url, headers=headers, data=data)
        assert error.value.code == 403


def test_same_origin_bridge_callback_is_available(ui_server):
    calls = []
    ui_server.js_callback['window'] = lambda body: calls.append(body) or {'ok': True}
    payload = {'uid': 'window', 'funcName': 'get_queue'}
    with request(ui_server.js_api_endpoint,
                 headers={'Origin': ui_server.address.rstrip('/'), 'Content-Type': 'application/json'},
                 data=json.dumps(payload).encode()) as response:
        assert json.loads(response.read()) == {'ok': True}
        assert 'Access-Control-Allow-Origin' not in response.headers
    assert calls == [payload]


def test_bridge_rejects_malformed_json(ui_server):
    with pytest.raises(urllib.error.HTTPError) as error:
        request(ui_server.js_api_endpoint, data=b'[]')
    assert error.value.code == 400


def test_bridge_rejects_unknown_callback(ui_server):
    with pytest.raises(urllib.error.HTTPError) as error:
        request(ui_server.js_api_endpoint,
                headers={'Content-Type': 'application/json'},
                data=json.dumps({'uid': 'unknown', 'funcName': 'get_queue'}).encode())
    assert error.value.code == 404


def test_oversized_bridge_request_is_rejected_before_dispatch(ui_server):
    called = []
    ui_server.js_callback['window'] = lambda body: called.append(body)
    statuses = []
    environ = {
        'REQUEST_METHOD': 'POST',
        'PATH_INFO': f'/js_api/{ui_server.uid}',
        'HTTP_HOST': f'127.0.0.1:{ui_server.port}',
        'CONTENT_LENGTH': '1048577',
        'wsgi.input': io.BytesIO(b'{}'),
    }

    result = ui_server._httpd.get_app()(environ, lambda status, _headers: statuses.append(status))

    assert statuses == ['413 Payload Too Large']
    assert result == [b'']
    assert called == []
