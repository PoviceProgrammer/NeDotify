"""Requests adapter sharing the public-media transport's bounded TLS failover.

Normal requests pooling, response decoding, cookies and proxy managers remain
in use. Only direct HTTPS connection establishment changes.
"""
import ssl

from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPSConnection
from urllib3.connectionpool import HTTPSConnectionPool
from urllib3.util.ssl_match_hostname import CertificateError, match_hostname

from utils.url_safety import _connect_public_tls


class _PublicProviderConnection(HTTPSConnection):
    def connect(self):
        # Keep urllib3's complete proxy/CONNECT and custom TLS-policy handling.
        if (self.proxy is not None or self._tunnel_host or self.cert_file
                or self.assert_fingerprint or self.assert_hostname is not None
                or self.ssl_minimum_version is not None or self.ssl_maximum_version is not None):
            return super().connect()
        context = self.ssl_context
        if context is None:
            context = ssl.create_default_context(cafile=self.ca_certs, capath=self.ca_cert_dir,
                                                 cadata=self.ca_cert_data)
        if context.verify_mode != ssl.CERT_REQUIRED:
            return super().connect()
        self._context = context
        try:
            _connect_public_tls(self)
            if not context.check_hostname:
                try:
                    match_hostname(self.sock.getpeercert(), self.server_hostname or self.host,
                                   hostname_checks_common_name=False)
                except CertificateError as exc:
                    raise ssl.SSLCertVerificationError(str(exc)) from exc
            self.is_verified = True
        except Exception:
            self.close()
            raise


class _PublicProviderPool(HTTPSConnectionPool):
    ConnectionCls = _PublicProviderConnection


class PublicHTTPAdapter(HTTPAdapter):
    """Bounded connection reuse and fast alternate-address TLS establishment."""

    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        # urllib3's default dictionary is shared: customize only this manager.
        self.poolmanager.pool_classes_by_scheme = dict(self.poolmanager.pool_classes_by_scheme)
        self.poolmanager.pool_classes_by_scheme['https'] = _PublicProviderPool


def prepare_ytdlp_transport(ydl):
    """Keep SDK cookies/proxy/SSL options; adapt its direct requests pools.

    The SDK owns each handler/session and closes it normally. This hook is
    local to one YoutubeDL object, never a global patch of requests or yt-dlp.
    Unsupported/future SDKs retain their normal working transport.
    """
    director = getattr(ydl, '_request_director', None)
    handlers = getattr(director, 'handlers', {})
    handler = handlers.get('Requests')
    create = getattr(handler, '_create_instance', None)
    if not callable(create) or getattr(handler, '_nedotify_public_tls', False):
        return ydl

    def create_session(*args, **kwargs):
        session = create(*args, **kwargs)
        for adapter in set(session.adapters.values()):
            manager = getattr(adapter, 'poolmanager', None)
            if manager is not None:
                manager.pool_classes_by_scheme = dict(manager.pool_classes_by_scheme)
                manager.pool_classes_by_scheme['https'] = _PublicProviderPool
        return session

    handler._create_instance = create_session
    handler._nedotify_public_tls = True
    return ydl
