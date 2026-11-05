"""A warmed TLS socket can accept a request while withholding all headers."""

from pathlib import Path
import socket
import ssl
import threading
import time
import urllib.request

import pytest

from utils import url_safety


@pytest.fixture
def idle_tls_origin(monkeypatch):
    fixtures = Path(__file__).parent / 'fixtures/tls'
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(fixtures / 'localhost-test-cert.pem', fixtures / 'localhost-test-key.pem')
    client_context = ssl.create_default_context(cafile=fixtures / 'localhost-test-cert.pem')
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    listener.settimeout(.1)
    port = listener.getsockname()[1]
    stop = threading.Event()
    stalled_request = threading.Event()
    closed_stalled = threading.Event()
    sockets, workers, connections, requests = [], [], [], []
    control = {'stall_reused': True, 'fresh_delay': 0, 'body_delay': 0, 'close_response': False}

    def receive_headers(secured):
        data = b''
        while b'\r\n\r\n' not in data:
            part = secured.recv(4096)
            if not part:
                return None
            data += part
        return data.split(b'\r\n', 1)[0].decode('ascii')

    def serve(raw, number):
        try:
            with server_context.wrap_socket(raw, server_side=True) as secured:
                sockets.append(secured)
                secured.settimeout(5)
                count = 0
                while not stop.is_set():
                    request = receive_headers(secured)
                    if request is None:
                        break
                    requests.append((number, request))
                    count += 1
                    if number == 1 and count == 2 and control['stall_reused']:
                        stalled_request.set()
                        # Accept the request, then send no HTTP bytes. Only the
                        # client's retirement of this socket ends the stall.
                        while secured.recv(4096):
                            pass
                        closed_stalled.set()
                        break
                    is_probe = number == 1 and count == 1 and '/probe ' in request
                    if not is_probe:
                        stop.wait(control['fresh_delay'])
                    payload = b'p' if is_probe else b'ready'
                    head = request.startswith('HEAD ')
                    disposition = b'close' if control['close_response'] and not is_probe else b'keep-alive'
                    secured.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: ' + str(len(payload)).encode()
                                    + b'\r\nConnection: ' + disposition + b'\r\n\r\n')
                    if not head:
                        if not is_probe:
                            stop.wait(control['body_delay'])
                        secured.sendall(payload)
        except (OSError, ssl.SSLError):
            pass

    def accept():
        while not stop.is_set():
            try:
                raw, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            sockets.append(raw)
            worker = threading.Thread(target=serve, args=(raw, len(workers) + 1), daemon=True)
            workers.append(worker)
            worker.start()

    original = url_safety._PublicHTTPSConnection

    class ObservedConnection(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.predecessor_closed = not connections or connections[-1].sock is None
            connections.append(self)

    pool = url_safety._IdleConnections()
    monkeypatch.setattr(url_safety, '_OPEN_CONNECTIONS', pool)
    monkeypatch.setattr(url_safety, '_PublicHTTPSConnection', ObservedConnection)
    monkeypatch.setattr(url_safety, '_public_addresses', lambda *args:
                        ((socket.AF_INET, socket.SOCK_STREAM, 6, ('127.0.0.1', port)),))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
        url_safety._PublicHTTPHandler(), url_safety._PublicHTTPSHandler(context=client_context),
        url_safety.PublicRedirectHandler())
    monkeypatch.setattr(url_safety._TRANSPORT_LOCAL, 'opener', opener, raising=False)
    acceptor = threading.Thread(target=accept, daemon=True)
    acceptor.start()
    yield (f'https://fixture.example:{port}', control, connections, requests, stalled_request, closed_stalled)
    stop.set()
    pool.clear()
    listener.close()
    for connection in connections:
        connection.close()
    for secured in sockets:
        try:
            secured.close()
        except OSError:
            pass
    acceptor.join(timeout=1)
    for worker in workers:
        worker.join(timeout=1)


@pytest.mark.parametrize('method', ['GET', 'HEAD'])
def test_reused_tls_socket_header_stall_retires_before_one_fresh_verified_retry(idle_tls_origin, method):
    origin, control, connections, requests, stalled_request, closed_stalled = idle_tls_origin
    with url_safety.guarded_open_url(origin + '/probe', timeout=3) as response:
        assert response.read() == b'p'
    assert len(connections) == 1
    started = time.monotonic()
    with url_safety.guarded_open_url(urllib.request.Request(origin + '/audio', method=method), timeout=3) as response:
        assert response.read() == (b'' if method == 'HEAD' else b'ready')
    elapsed = time.monotonic() - started
    assert stalled_request.is_set(), 'the warmed connection must actually receive the stalled request'
    assert elapsed < 1.5, f'reused header stall consumed {elapsed:.2f}s of the full 3s request timeout'
    assert len(connections) == 2, 'exactly one fresh connection may retry a safe request'
    assert connections[1].predecessor_closed, 'close the suspect socket before creating its replacement'
    assert closed_stalled.wait(.5)
    assert [request for _, request in requests] == ['GET /probe HTTP/1.1', f'{method} /audio HTTP/1.1', f'{method} /audio HTTP/1.1']


def test_fresh_tls_response_keeps_callers_header_and_body_timeout(idle_tls_origin):
    origin, control, connections, _, _, _ = idle_tls_origin
    control.update(stall_reused=False, fresh_delay=1.1, body_delay=1.1)
    started = time.monotonic()
    with url_safety.guarded_open_url(origin + '/audio', timeout=3) as response:
        assert response.read() == b'ready'
    assert time.monotonic() - started >= 2.1
    assert len(connections) == 1, 'a healthy fresh response must not be needlessly retried'


@pytest.mark.parametrize('close_after_headers', [False, True])
def test_reused_tls_socket_body_keeps_callers_timeout_after_headers(idle_tls_origin, close_after_headers):
    origin, control, connections, _, _, _ = idle_tls_origin
    with url_safety.guarded_open_url(origin + '/probe', timeout=3) as response:
        assert response.read() == b'p'
    control.update(stall_reused=False, body_delay=1.1, close_response=close_after_headers)
    with url_safety.guarded_open_url(origin + '/audio', timeout=3) as response:
        assert response.read() == b'ready'
    assert len(connections) == 1, 'header-only recovery must not shorten streaming reads'
