"""Shared fail-closed public-network transport with DNS-to-socket binding."""

import http.client
import ipaddress
import errno
import selectors
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from collections import OrderedDict

_DNS_LOCK = threading.Lock()
_DNS_CACHE = {}
_DNS_SLOTS = threading.BoundedSemaphore(8)
_DNS_TIMEOUT = 2.0


def reset_url_safety_cache():
    with _DNS_LOCK:
        _DNS_CACHE.clear()
    if hasattr(_TRANSPORT_LOCAL, 'opener'):
        del _TRANSPORT_LOCAL.opener
    close_guarded_connections()
    _OPEN_CONNECTIONS.clear()


def _public_addresses(host, port):
    # A resolver owns exactly the semaphore slot it acquired, including when
    # tests or a transport lifecycle replace the pool while DNS is in flight.
    slots = _DNS_SLOTS
    key = (host, port)
    with _DNS_LOCK:
        cached = _DNS_CACHE.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
    if not slots.acquire(blocking=True, timeout=1.5):
        return ()
    with _DNS_LOCK:
        cached = _DNS_CACHE.get(key)
        if cached and cached[0] > time.monotonic():
            slots.release()
            return cached[1]
    done, result = threading.Event(), []

    def resolve():
        try:
            for family, kind, protocol, _, address in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
                parsed = ipaddress.ip_address(address[0].split('%', 1)[0])
                if not parsed.is_global or parsed.is_multicast or parsed.is_reserved:
                    result.clear()
                    return
                result.append((family, kind, protocol, address))
        except (OSError, UnicodeError, ValueError):
            result.clear()
        finally:
            done.set()
            slots.release()

    try:
        threading.Thread(target=resolve, name='PublicDNS', daemon=True).start()
    except Exception:
        slots.release()
        return ()
    addresses = tuple(result) if done.wait(_DNS_TIMEOUT) else ()
    with _DNS_LOCK:
        if len(_DNS_CACHE) >= 512:
            _DNS_CACHE.pop(next(iter(_DNS_CACHE)))
        _DNS_CACHE[key] = (time.monotonic() + (30 if addresses else 2), addresses)
    return addresses


def safe_public_url(url):
    try:
        parsed = urlparse(str(url or ''))
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            return False
        return bool(_public_addresses(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80)))
    except (TypeError, ValueError, UnicodeError):
        return False


is_safe_media_url = safe_public_url


def _connect_public(connection):
    addresses = _public_addresses(connection.host, connection.port)
    if not addresses:
        raise urllib.error.URLError('URL does not resolve to a public address')
    from utils.linux_proxy import endpoint
    proxy = endpoint()
    if proxy:
        import socks
        # Use a vetted numerical target to retain DNS rebinding protection.
        error = None
        for _, _, _, address in addresses:
            try:
                connection.sock = socks.create_connection((address[0], connection.port), timeout=connection.timeout,
                    proxy_type=socks.SOCKS5, proxy_addr=proxy[0], proxy_port=proxy[1], proxy_rdns=False)
                return
            except OSError as exc:
                error = exc
        raise error or OSError('App SOCKS connection failed')
    error = None
    for family, kind, protocol, address in addresses:
        candidate = socket.socket(family, kind, protocol)
        try:
            candidate.settimeout(connection.timeout)
            if connection.source_address:
                candidate.bind(connection.source_address)
            candidate.connect(address)
            connection.sock = candidate
            return
        except OSError as exc:
            error = exc
            candidate.close()
    raise error or OSError('Public connection failed')


class _PublicHTTPConnection(http.client.HTTPConnection):
    def connect(self):
        _connect_public(self)


class _PublicHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        _connect_public_tls(self)


def _connect_public_tls(connection):
    """Stagger up to two vetted CDN addresses through TCP *and* TLS.

    A server can accept TCP while its TLS handshake stalls. Trying addresses
    only until TCP succeeds kept playback stuck there for 12 seconds. The
    selector needs no extra worker threads, uses one overall timeout and
    closes losing sockets before returning the fully verified winner.
    """
    addresses = _public_addresses(connection.host, connection.port)
    if not addresses:
        raise urllib.error.URLError('URL does not resolve to a public address')
    from utils.linux_proxy import endpoint
    if endpoint():
        _connect_public(connection)
        try:
            connection.sock = connection._context.wrap_socket(connection.sock, server_hostname=connection.host)
        except Exception:
            connection.sock.close()
            raise
        return
    timeout = connection.timeout
    if timeout is socket._GLOBAL_DEFAULT_TIMEOUT:
        timeout = socket.getdefaulttimeout()
    deadline = time.monotonic() + (timeout if timeout is not None else 12.0)
    # Try the other IP family second when available, rather than waiting on
    # two stalled IPv6 addresses before reaching a working IPv4 endpoint.
    first_family = addresses[0][0]
    same = [entry for entry in addresses if entry[0] == first_family]
    other = [entry for entry in addresses if entry[0] != first_family]
    ordered = []
    while same or other:
        if same:
            ordered.append(same.pop(0))
        if other:
            ordered.append(other.pop(0))
    # Some Google CDN names publish only one address. A stalled TLS flow can
    # still recover on one fresh connection to that same vetted endpoint.
    # Healthy handshakes finish before the delayed second attempt starts.
    single_address = len(ordered) == 1
    if single_address:
        ordered.append(ordered[0])
    candidates = iter(ordered)
    exhausted = False
    pending = {}
    error = None
    next_attempt = 0.0
    in_progress = {0, errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY, 10035, 10036, 10037}
    with selectors.DefaultSelector() as selector:
        def discard(candidate):
            try:
                selector.unregister(candidate)
            except (KeyError, ValueError):
                pass
            pending.pop(candidate, None)
            candidate.close()

        try:
            while True:
                now = time.monotonic()
                if now >= deadline:
                    if isinstance(error, ssl.SSLCertVerificationError):
                        raise error
                    raise TimeoutError('Public CDN TCP/TLS connection timed out') from error
                if not exhausted and len(pending) < 2 and (not pending or now >= next_attempt):
                    try:
                        family, kind, protocol, address = next(candidates)
                    except StopIteration:
                        exhausted = True
                    else:
                        candidate = socket.socket(family, kind, protocol)
                        try:
                            candidate.setblocking(False)
                            if connection.source_address:
                                candidate.bind(connection.source_address)
                            result = candidate.connect_ex(address)
                            if result not in in_progress:
                                raise OSError(result, 'Public CDN TCP connection failed')
                            pending[candidate] = 'tcp'
                            selector.register(candidate, selectors.EVENT_WRITE)
                            next_attempt = now + (.4 if single_address else .25)
                        except OSError as exc:
                            error = exc
                            discard(candidate)
                        continue
                if exhausted and not pending:
                    raise error or OSError('Public CDN connection failed')
                wait = deadline - time.monotonic()
                if not exhausted and len(pending) < 2:
                    wait = min(wait, max(0.0, next_attempt - time.monotonic()))
                for selected, _events in selector.select(max(0.0, wait)):
                    candidate = selected.fileobj
                    try:
                        if pending[candidate] == 'tcp':
                            result = candidate.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                            if result:
                                raise OSError(result, 'Public CDN TCP connection failed')
                            selector.unregister(candidate)
                            pending.pop(candidate)
                            try:
                                candidate = connection._context.wrap_socket(
                                    candidate, server_hostname=connection.host, do_handshake_on_connect=False)
                            except Exception:
                                candidate.close()
                                raise
                            pending[candidate] = 'tls'
                            selector.register(candidate, selectors.EVENT_READ | selectors.EVENT_WRITE)
                        try:
                            candidate.do_handshake()
                        except ssl.SSLWantReadError:
                            selector.modify(candidate, selectors.EVENT_READ)
                        except ssl.SSLWantWriteError:
                            selector.modify(candidate, selectors.EVENT_WRITE)
                        else:
                            selector.unregister(candidate)
                            pending.pop(candidate)
                            candidate.settimeout(timeout)
                            connection.sock = candidate
                            return
                    except (OSError, ValueError) as exc:
                        error = exc
                        discard(candidate)
        finally:
            for candidate in list(pending):
                discard(candidate)


class _PublicHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        if req.has_proxy() or req._tunnel_host:
            return self.do_open(_PublicHTTPConnection, req)
        return _pooled_open(req, _PublicHTTPConnection)


class _PublicHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        if req.has_proxy() or req._tunnel_host:
            return self.do_open(_PublicHTTPSConnection, req, context=self._context)
        return _pooled_open(req, _PublicHTTPSConnection, context=self._context)


class _IdleConnections:
    """Bounded idle sockets shared by the proxy's short-lived request threads.

    Only fully consumed responses return here. A checked-out connection has
    exactly one owner; another worker can never read its in-flight response.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._idle = OrderedDict()

    def take(self, key):
        with self._lock:
            now = time.monotonic()
            for ident, (origin, connection, stamp) in list(self._idle.items()):
                if now - stamp >= 20 or connection.sock is None:
                    self._idle.pop(ident)
                    connection.close()
            for ident in reversed(self._idle):
                origin, connection, _stamp = self._idle[ident]
                if origin == key:
                    self._idle.pop(ident)
                    return connection
        return None

    def put(self, key, connection):
        with self._lock:
            self._idle[id(connection)] = (key, connection, time.monotonic())
            same_origin = [ident for ident, entry in self._idle.items() if entry[0] == key]
            for ident in same_origin[:-4]:
                self._idle.pop(ident)[1].close()
            while len(self._idle) > 24:
                self._idle.popitem(last=False)[1][1].close()

    def clear(self):
        with self._lock:
            for _origin, connection, _stamp in self._idle.values():
                connection.close()
            self._idle.clear()


_OPEN_CONNECTIONS = _IdleConnections()


class _OpenResponse:
    """urllib-compatible response that releases its pinned HTTP connection."""

    def __init__(self, raw, connection, key, url):
        self.raw, self.connection, self.key, self.url = raw, connection, key, url
        self.status = self.code = raw.status
        self.headers, self.msg = raw.headers, raw.reason
        self.closed = False
        self.failed = False

    def __getattr__(self, name):
        return getattr(self.raw, name)

    def geturl(self):
        return self.url

    def _read(self, method, *args):
        try:
            return method(*args)
        except Exception:
            self.failed = True
            raise

    def read(self, *args):
        return self._read(self.raw.read, *args)

    def read1(self, *args):
        return self._read(self.raw.read1, *args)

    def readinto(self, *args):
        return self._read(self.raw.readinto, *args)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def close(self):
        if self.closed:
            return
        self.closed = True
        complete = self.raw.length == 0 or (self.raw.chunked and self.raw.isclosed() and self.raw.chunk_left is None)
        reusable = complete and not self.failed and not self.raw.will_close and self.connection.sock is not None
        self.raw.close()
        if reusable:
            _OPEN_CONNECTIONS.put(self.key, self.connection)
        else:
            self.connection.close()


def _pooled_open(req, factory, **kwargs):
    # The normal opener still handles proxies, HTTP errors, redirects and
    # credential stripping. Only the direct connection lifetime changes.
    key = (req.type, req.host)
    prior = _OPEN_CONNECTIONS.take(key)
    connection = prior or factory(req.host, timeout=req.timeout, **kwargs)
    headers = dict(req.unredirected_hdrs)
    headers.update(req.headers)
    headers.setdefault('Connection', 'keep-alive')
    for attempt in range(2):
        try:
            connection.timeout = req.timeout
            if connection.sock is not None:
                connection.sock.settimeout(req.timeout)
            header_socket = None
            if prior is not None and not attempt and req.get_method() in ('GET', 'HEAD') and connection.sock is not None:
                # A silently stalled keep-alive flow must not spend the entire
                # playback timeout before the existing single fresh retry.
                header_socket = connection.sock
                header_socket.settimeout(min(1.0, req.timeout) if req.timeout is not None else 1.0)
            connection.request(req.get_method(), req.selector, req.data, headers,
                               encode_chunked=req.has_header('Transfer-encoding'))
            raw = connection.getresponse()
            if header_socket is not None:
                # http.client may detach connection.sock on Connection: close;
                # the response body still owns this socket through its file.
                header_socket.settimeout(req.timeout)
            return _OpenResponse(raw, connection, key, req.full_url)
        except (OSError, http.client.HTTPException) as exc:
            connection.close()
            # Retry only one silently retired idle socket, and only a safe GET
            # or HEAD. Fresh connection failures retain the caller's policy.
            if prior is None or attempt or req.get_method() not in ('GET', 'HEAD'):
                raise urllib.error.URLError(exc) from exc
            connection = factory(req.host, timeout=req.timeout, **kwargs)


class PublicRedirectHandler(urllib.request.HTTPRedirectHandler):
    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not safe_public_url(newurl):
            raise urllib.error.URLError('Unsafe redirect destination')
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and urlparse(req.full_url).hostname != urlparse(newurl).hostname:
            for store in (redirected.headers, redirected.unredirected_hdrs):
                for name in list(store):
                    if name.lower() in ('authorization', 'cookie', 'proxy-authorization'):
                        del store[name]
        return redirected


_TRANSPORT_LOCAL = threading.local()


def guarded_open_url(request, timeout=12.0):
    """Validate every hop and connect only to its vetted IP; retain TLS SNI."""
    url = request.full_url if hasattr(request, 'full_url') else str(request)
    if not safe_public_url(url):
        raise urllib.error.URLError('Unsafe URL rejected')
    opener = getattr(_TRANSPORT_LOCAL, 'opener', None)
    if opener is None:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler(), _PublicHTTPHandler(), _PublicHTTPSHandler(), PublicRedirectHandler())
        _TRANSPORT_LOCAL.opener = opener
    return opener.open(request, timeout=timeout)


class _StreamingResponse:
    def __init__(self, raw):
        self.raw = raw
        self.status_code = raw.status
        self.headers = raw.headers

    def iter_content(self, chunk_size):
        while True:
            chunk = self.raw.read(chunk_size)
            if not chunk:
                return
            yield chunk

    def raise_for_status(self):
        if self.status_code >= 400:
            raise urllib.error.HTTPError(self.raw.geturl(), self.status_code, 'Upstream media request failed', self.headers, self.raw)

    def close(self):
        self.raw.close()


def close_guarded_connections():
    """Release this worker's bounded idle connections, never another thread's IO."""
    _OPEN_CONNECTIONS.clear()
    pool = getattr(_TRANSPORT_LOCAL, 'connections', None)
    if pool:
        for connection, _stamp in pool.values():
            connection.close()
        pool.clear()


class _PooledResponse:
    def __init__(self, raw, connection, pool, key, url):
        self.raw, self.connection, self.pool, self.key, self.url = raw, connection, pool, key, url
        self.status_code, self.headers = raw.status, raw.headers
        self.exhausted = False
        self.closed = False

    def iter_content(self, chunk_size):
        while True:
            chunk = self.raw.read(chunk_size)
            if not chunk:
                self.exhausted = True
                return
            yield chunk

    def raise_for_status(self):
        if self.status_code >= 400:
            raise urllib.error.HTTPError(self.url, self.status_code, 'Upstream media request failed', self.headers, None)

    def close(self):
        if self.closed:
            return
        self.closed = True
        reusable = self.exhausted and not self.raw.will_close and self.connection.sock is not None
        self.raw.close()
        if reusable:
            # At most four idle origins per bounded download worker. In-use
            # responses are not in the pool and can never be handed out twice.
            previous = self.pool.pop(self.key, None)
            if previous:
                previous[0].close()
            self.pool[self.key] = (self.connection, time.monotonic())
            while len(self.pool) > 4:
                self.pool.popitem(last=False)[1][0].close()
        else:
            self.connection.close()


def guarded_requests_get(url, headers=None, stream=True, timeout=(5, 5), allow_redirects=False):
    """Keep-alive streaming with DNS-to-socket pinning and explicit redirects.

    Riff's bounded keep-alive agent is the architectural reference. Connections
    stay private to a worker, retain certificate/SNI checks, and expire at 30s.
    """
    if allow_redirects:
        raise ValueError('Transfers must validate redirects explicitly')
    if not safe_public_url(url):
        raise urllib.error.URLError('Unsafe URL rejected')
    parsed = urlparse(url)
    key = (parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80))
    pool = getattr(_TRANSPORT_LOCAL, 'connections', None)
    if pool is None:
        pool = _TRANSPORT_LOCAL.connections = OrderedDict()
    connect_timeout, read_timeout = timeout if isinstance(timeout, tuple) else (timeout, timeout)
    prior = pool.pop(key, None)
    reused = prior is not None and time.monotonic() - prior[1] < 30
    if prior and not reused:
        prior[0].close()
    factory = _PublicHTTPSConnection if parsed.scheme == 'https' else _PublicHTTPConnection
    connection = prior[0] if reused else factory(key[1], key[2], timeout=connect_timeout)
    target = (parsed.path or '/') + (('?' + parsed.query) if parsed.query else '')
    request_headers = {'Accept-Encoding': 'identity', **(headers or {})}
    for attempt in range(2):
        try:
            connection.request('GET', target, headers=request_headers)
            if connection.sock:
                connection.sock.settimeout(read_timeout)
            raw = connection.getresponse()
            return _PooledResponse(raw, connection, pool, key, url)
        except (OSError, http.client.HTTPException):
            connection.close()
            # A server may silently retire an idle socket. Retry that one stale
            # GET once; fresh-connection errors belong to the manager's policy.
            if not reused or attempt:
                raise
            connection = factory(key[1], key[2], timeout=connect_timeout)
