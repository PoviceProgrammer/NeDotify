"""Real HTTP fixture for bounded keep-alive, early close and redirect policy."""
import http.server
import socket
import threading

import pytest

from utils import url_safety


@pytest.fixture
def media_origin(monkeypatch):
    connections, requests = [], []
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def setup(self):
            super().setup()
            self.connection.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
            connections.append(True)
        def do_GET(self):
            requests.append(self.path)
            self.send_response(302 if self.path == '/redirect' else 200)
            if self.path == '/redirect':
                self.send_header('Location','http://127.0.0.1/private')
            self.send_header('Content-Length','8192')
            self.end_headers()
            self.wfile.write(b'x'*8192)
        def log_message(self,*args):
            pass
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    worker=threading.Thread(target=server.serve_forever,daemon=True)
    worker.start()
    def fixture_addresses(host,port):
        if host=='fixture.example' and port==server.server_port:
            return ((socket.AF_INET,socket.SOCK_STREAM,6,('127.0.0.1',port)),)
        return ()
    monkeypatch.setattr(url_safety,'_public_addresses',fixture_addresses)
    url_safety.close_guarded_connections()
    yield f'http://fixture.example:{server.server_port}',connections,requests
    url_safety.close_guarded_connections()
    server.shutdown()
    server.server_close()


def test_complete_responses_reuse_the_same_pinned_connection(media_origin):
    origin,connections,_=media_origin
    for index in range(4):
        response=url_safety.guarded_requests_get(origin+'/'+str(index))
        assert b''.join(response.iter_content(1024)) == b'x'*8192
        response.close()
    assert len(connections)==1


def test_early_close_is_not_returned_to_the_idle_pool(media_origin):
    origin,connections,_=media_origin
    response=url_safety.guarded_requests_get(origin+'/first')
    response.close()
    response=url_safety.guarded_requests_get(origin+'/second')
    assert len(b''.join(response.iter_content(1024)))==8192
    response.close()
    assert len(connections)==2


def test_guarded_opener_reuses_completed_media_across_proxy_threads(media_origin):
    origin, connections, _ = media_origin
    failures = []
    def read():
        try:
            with url_safety.guarded_open_url(origin + '/manifest') as response:
                assert response.read() == b'x' * 8192
        except Exception as exc:
            failures.append(exc)
    for _ in range(4):
        worker = threading.Thread(target=read)
        worker.start()
        worker.join(timeout=2)
        assert not worker.is_alive()
    assert not failures
    assert len(connections) == 1, 'Each HLS manifest/segment must not repeat TCP and TLS'


def test_guarded_opener_partial_body_does_not_contaminate_next_response(media_origin):
    origin, connections, _ = media_origin
    with url_safety.guarded_open_url(origin + '/partial') as response:
        assert response.read(1) == b'x'
    with url_safety.guarded_open_url(origin + '/complete') as response:
        assert response.read() == b'x' * 8192
    assert len(connections) == 2


def test_guarded_opener_keeps_redirect_private_address_protection(media_origin):
    origin, _, requests = media_origin
    with pytest.raises(Exception, match='Unsafe'):
        url_safety.guarded_open_url(origin + '/redirect')
    assert requests == ['/redirect']


def test_redirects_are_returned_for_per_hop_validation(media_origin):
    origin,_,requests=media_origin
    response=url_safety.guarded_requests_get(origin+'/redirect')
    assert response.status_code==302
    assert response.headers['Location']=='http://127.0.0.1/private'
    response.close()
    assert requests==['/redirect']
    with pytest.raises(Exception,match='Unsafe'):
        url_safety.guarded_requests_get('http://127.0.0.1/private')


def test_pool_eviction_closes_oldest_idle_origin(monkeypatch):
    from collections import OrderedDict
    class Socket:
        def settimeout(self,*args): pass
    class Response:
        status=200
        headers={}
        will_close=False
        def read(self,size): return b''
        def close(self): pass
    created=[]
    class Connection:
        def __init__(self,*args,**kwargs):
            self.sock=Socket();self.closed=False;created.append(self)
        def request(self,*args,**kwargs): pass
        def getresponse(self):return Response()
        def close(self):self.closed=True
    monkeypatch.setattr(url_safety,'safe_public_url',lambda value:True)
    monkeypatch.setattr(url_safety,'_PublicHTTPSConnection',Connection)
    url_safety._TRANSPORT_LOCAL.connections=OrderedDict()
    try:
        for number in range(6):
            response=url_safety.guarded_requests_get(f'https://origin{number}.example/audio')
            list(response.iter_content(1));response.close()
        assert len(url_safety._TRANSPORT_LOCAL.connections)==4
        assert created[0].closed and created[1].closed
        assert not created[2].closed
    finally:
        url_safety.close_guarded_connections()
