"""A CDN IP can accept TCP but stall TLS while another IP works normally."""
from pathlib import Path
import socket
import select
import ssl
import threading
import time

import pytest

from utils import url_safety

FIXTURES = Path(__file__).parent / 'fixtures/tls'


@pytest.fixture
def tls_cdn(monkeypatch):
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(FIXTURES / 'localhost-test-cert.pem', FIXTURES / 'localhost-test-key.pem')
    ready = socket.socket()
    ready.bind(('127.0.0.1', 0))
    port = ready.getsockname()[1]
    ready.listen()
    stalled = socket.socket()
    stalled.bind(('127.0.0.2', port))
    stalled.listen()
    release = threading.Event()
    accepted = []
    control = {'payload': b'ready'}
    def serve(listener, context):
        listener.settimeout(2)
        try:
            while True:
                connection, _ = listener.accept()
                accepted.append(connection)
                if context and control.get('stall_first'):
                    control['stall_first'] = False
                    continue
                break
            if context:
                with context.wrap_socket(connection, server_side=True) as secured:
                    if control['payload'].startswith(b'HTTP/'):
                        secured.settimeout(1)
                        request = b''
                        while b'\r\n\r\n' not in request:
                            part = secured.recv(4096)
                            if not part:
                                break
                            request += part
                    secured.sendall(control['payload'])
            else:
                release.wait(2)
        except (OSError, ssl.SSLError):
            pass
    threads = [threading.Thread(target=serve, args=(stalled, None)),
               threading.Thread(target=serve, args=(ready, server_context))]
    for worker in threads:
        worker.start()
    addresses = tuple((socket.AF_INET, socket.SOCK_STREAM, 6, (host, port))
                      for host in ('127.0.0.2', '127.0.0.1'))
    monkeypatch.setattr(url_safety, '_public_addresses', lambda host, port: addresses)
    context = ssl.create_default_context(cafile=FIXTURES / 'localhost-test-cert.pem')
    yield port, context, accepted, control
    release.set()
    for connection in accepted:
        connection.close()
    ready.close()
    stalled.close()
    for worker in threads:
        worker.join(timeout=3)


def test_tls_stall_on_first_cdn_address_does_not_hold_up_playback(tls_cdn):
    port, context, _, _control = tls_cdn
    connection = url_safety._PublicHTTPSConnection('fixture.example', port, timeout=1.5, context=context)
    start = time.monotonic()
    try:
        connection.connect()
        assert connection.sock.recv(5) == b'ready'
        assert time.monotonic() - start < 1, 'Do not wait for the stalled TLS timeout'
    finally:
        connection.close()


def test_alternate_cdn_address_still_requires_matching_tls_certificate(tls_cdn):
    port, context, _, _control = tls_cdn
    connection = url_safety._PublicHTTPSConnection('wrong.example', port, timeout=1, context=context)
    try:
        with pytest.raises((ssl.SSLCertVerificationError, TimeoutError)):
            connection.connect()
        assert connection.sock is None
    finally:
        connection.close()


def test_requests_provider_client_uses_the_same_verified_tls_failover(tls_cdn):
    import requests
    from utils.requests_transport import PublicHTTPAdapter
    port, _context, _accepted, control = tls_cdn
    control['payload'] = b'HTTP/1.1 200 OK\r\nContent-Length: 5\r\nConnection: close\r\n\r\nready'
    start = time.monotonic()
    with requests.Session() as session:
        session.trust_env = False
        session.mount('https://', PublicHTTPAdapter())
        response = session.get(f'https://fixture.example:{port}/search', timeout=1.5,
                               verify=str(FIXTURES / 'localhost-test-cert.pem'))
    assert response.status_code == 200 and response.content == b'ready'
    assert time.monotonic() - start < 1


def test_requests_adapter_preserves_certificate_verification(tls_cdn):
    import requests
    from utils.requests_transport import PublicHTTPAdapter
    port, _context, _accepted, _control = tls_cdn
    with requests.Session() as session:
        session.trust_env = False
        session.mount('https://', PublicHTTPAdapter())
        with pytest.raises((requests.exceptions.SSLError, requests.exceptions.ConnectionError)):
            session.get(f'https://wrong.example:{port}/search', timeout=.7,
                        verify=str(FIXTURES / 'localhost-test-cert.pem'))


def test_single_address_cdn_stalled_tls_can_use_one_fresh_connection(tls_cdn, monkeypatch):
    port, context, _accepted, control = tls_cdn
    control['stall_first'] = True
    monkeypatch.setattr(url_safety, '_public_addresses', lambda *args:
                        ((socket.AF_INET, socket.SOCK_STREAM, 6, ('127.0.0.1', port)),))
    connection = url_safety._PublicHTTPSConnection('fixture.example', port, timeout=1.5, context=context)
    start = time.monotonic()
    try:
        connection.connect()
        assert connection.sock.recv(5) == b'ready'
        assert time.monotonic() - start < 1
    finally:
        connection.close()


def test_requests_adapter_retains_explicit_connect_proxy(tls_cdn):
    import requests
    from utils.requests_transport import PublicHTTPAdapter
    port, _context, _accepted, control = tls_cdn
    control['payload'] = b'HTTP/1.1 200 OK\r\nContent-Length: 5\r\nConnection: close\r\n\r\nready'
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    listener.settimeout(2)
    seen = []
    def tunnel():
        try:
            with listener.accept()[0] as client:
                client.settimeout(2)
                headers = b''
                while b'\r\n\r\n' not in headers:
                    part = client.recv(4096)
                    if not part or len(headers) > 65536:
                        return
                    headers += part
                seen.append(headers.split(b'\r\n')[0])
                with socket.create_connection(('127.0.0.1', port), timeout=2) as upstream:
                    client.sendall(b'HTTP/1.1 200 Connection established\r\n\r\n')
                    while True:
                        readable, _, _ = select.select([client, upstream], [], [], 2)
                        if not readable:
                            return
                        for source in readable:
                            data = source.recv(16384)
                            if not data:
                                return
                            (upstream if source is client else client).sendall(data)
        except OSError:
            pass
    worker = threading.Thread(target=tunnel)
    worker.start()
    try:
        with requests.Session() as session:
            session.trust_env = False
            session.mount('https://', PublicHTTPAdapter())
            response = session.get(f'https://fixture.example:{port}/search', timeout=1.5,
                                   verify=str(FIXTURES / 'localhost-test-cert.pem'),
                                   proxies={'https': f'http://127.0.0.1:{listener.getsockname()[1]}'})
        assert response.content == b'ready'
        assert seen == [f'CONNECT fixture.example:{port} HTTP/1.1'.encode()]
    finally:
        listener.close()
        worker.join(timeout=3)


def test_real_ytdlp_handler_uses_verified_failover_without_replacing_sdk_sessions(tls_cdn, monkeypatch):
    from yt_dlp import YoutubeDL
    from yt_dlp.networking import Request
    from utils.requests_transport import prepare_ytdlp_transport
    port, context, _accepted, control = tls_cdn
    control['payload'] = b'HTTP/1.1 200 OK\r\nContent-Length: 5\r\nConnection: close\r\n\r\nready'
    with YoutubeDL({'quiet': True, 'socket_timeout': 1.5}) as ydl:
        handler = ydl._request_director.handlers['Requests']
        monkeypatch.setattr(handler, '_make_sslcontext', lambda **kwargs: context)
        assert prepare_ytdlp_transport(ydl) is ydl
        response = ydl.urlopen(Request(f'https://fixture.example:{port}/manifest'))
        try:
            assert response.read() == b'ready'
        finally:
            response.close()
