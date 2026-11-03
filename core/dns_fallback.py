"""A bounded, proxy-independent DNS-over-HTTPS fallback after OS DNS fails.

BUG-034: the fallback used to trigger ONLY on socket.gaierror — a poisoned
but "successful" DNS answer (the censor's classic: a public domain resolving
to a loopback / RFC1918 / 0.0.0.0 sinkhole) was accepted as-is. The OS result
is now additionally screened by a conservative reserved-range heuristic
(_looks_poisoned); a hit sends the name through the same single-flight DoH
lookup and the OS answer is replaced only when DoH actually returns an
address.

PRINCIPAL LIMITATION (by design, not fixable here): a poisoned reply carrying
a PLAUSIBLE PUBLIC IP is indistinguishable from the truth without an
independent trusted source for every lookup — this heuristic deliberately
covers only the sinkhole-style answers, the dominant poisoning pattern.
"""
from collections import OrderedDict
from typing import Optional
import ipaddress
import json
import socket
import ssl
import threading
import time
import urllib.parse
import urllib.request


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


# Reserved ranges an honest public DNS answer never contains for the public
# app domains this resolver serves (BUG-034). Mapping into these is the
# standard poisoning/sinkhole fingerprint: loopback, unspecified ("this
# network"), link-local, RFC1918 private, CGNAT (100.64/10), and the IPv6
# equivalents (loopback, ULA, link-local).
# D2 review additions — same "never a legit public answer" class:
#   ::ffff:0:0/96  — IPv4-mapped IPv6 (::ffff:127.0.0.1 is a loopback sinkhole
#     wearing an IPv6 mask; it is NOT inside ::1/128 or any other net below),
#   224.0.0.0/4    — IPv4 multicast, 240.0.0.0/4 — IPv4 reserved incl. the
#     255.255.255.255 broadcast, ff00::/8 — IPv6 multicast.
# Deliberately NOT listed: 64:ff9b::/96 (NAT64). On an IPv6-only network with
# DNS64 the honest OS answer for an A-only domain IS 64:ff9b-prefixed, so
# flagging it would break those networks for no poisoning-detection gain.
_RESERVED_NETS = tuple(
    ipaddress.ip_network(net)
    for net in (
        "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8",
        "169.254.0.0/16", "172.16.0.0/12", "192.168.0.0/16",
        "224.0.0.0/4", "240.0.0.0/4",
        "::1/128", "fc00::/7", "fe80::/10", "ff00::/8", "::ffff:0:0/96",
    )
)

# Escape hatch for domains that LEGITIMATELY resolve into reserved space
# (internal hostnames, test doubles). No domain in the app's provider lists
# needs it today; kept as a documented extension point so a future internal
# service does not have to weaken the heuristic itself. Exact, lower-cased,
# NO suffix matching — a subdomain must be listed explicitly.
_PRIVATE_ADDRESS_ALLOWLIST: frozenset = frozenset()


def _ascii_domain_name(host) -> Optional[str]:
    """ASCII (punycode) form of *host* for DoH, or None when DoH cannot help.

    None for: non-string hosts (socket permits them only because the OS
    resolver does), non-ASCII names, over/under-length names, and numeric IP
    literals — a literal needs no name resolution at all.
    """
    if not isinstance(host, (str, bytes)):
        return None
    try:
        name = (host.decode('ascii') if isinstance(host, bytes)
                else host.encode('idna').decode('ascii'))
    except (UnicodeError, ValueError):
        return None
    if not 0 < len(name) <= 253:
        return None
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return name
    return None  # numeric literal


def _looks_poisoned(name: str, results) -> bool:
    """True when a successful OS answer for *name* smells like a sinkhole.

    Conservative on purpose: only reserved-range mappings count. Local,
    single-label and mDNS-style names never look poisoned (they are not
    public domains and must not pay a DoH round-trip); allowlisted domains
    are exempt.
    """
    lowered = name.lower()
    if "." not in lowered or lowered.endswith((".localhost", ".local")):
        return False
    if lowered in _PRIVATE_ADDRESS_ALLOWLIST:
        return False
    for item in results or ():
        addr = item[4][0] if len(item) > 4 and item[4] else None
        if not addr:
            continue
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        for net in _RESERVED_NETS:
            # Mixed-version containment raises TypeError; a version gate is
            # cheaper and clearer than an exception per pair.
            if ip.version == net.version and ip in net:
                return True
    return False


class DnsFallback:
    def __init__(self, resolver, opener=None, clock=time.monotonic, budget=1.8):
        self._resolver = resolver
        self._opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        self._clock = clock
        self._budget = budget
        self._lock = threading.RLock()
        self._cache = OrderedDict()
        self._flights = {}

    def _cached(self, key):
        with self._lock:
            value = self._cache.get(key)
            if value is None:
                return False, None
            expires, ip = value
            if self._clock() >= expires:
                self._cache.pop(key, None)
                return False, None
            self._cache.move_to_end(key)
            return True, ip

    def _query(self, host, record_type):
        deadline = self._clock() + self._budget
        query = urllib.parse.urlencode({'name': host, 'type': record_type})
        for endpoint in ('https://1.1.1.1/dns-query', 'https://8.8.8.8/resolve'):
            remaining = deadline - self._clock()
            if remaining <= 0:
                break
            request = urllib.request.Request(endpoint + '?' + query,
                                             headers={'Accept': 'application/dns-json'})
            try:
                with self._opener.open(request, timeout=min(.9, remaining)) as response:
                    raw = response.read(65_537)
                    if len(raw) > 65_536:
                        continue
                    data = json.loads(raw)
                    for answer in data.get('Answer', []):
                        if answer.get('type') != record_type:
                            continue
                        ip = ipaddress.ip_address(answer.get('data', ''))
                        if ip.version == (6 if record_type == 28 else 4):
                            return str(ip)
            except (OSError, ValueError, TypeError, AttributeError):
                continue
        return None

    def _doh_resolve(self, name, family, port, type, proto, flags, key,
                     original_error: Optional[socket.gaierror] = None,
                     os_results=None):
        """Shared single-flight/cache DoH lookup (BUG-034 refactor).

        *original_error* is the gaierror to re-raise when DoH yields nothing
        (the hard-failure path). On the poisoned-success path it is None and
        the OS answer is returned instead — degrading to the (suspicious) OS
        result beats raising out of an otherwise successful lookup.
        """
        found, ip = self._cached(key)
        if not found:
            with self._lock:
                event = self._flights.get(key)
                owner = event is None
                if owner:
                    if len(self._flights) >= 8:
                        if original_error is not None:
                            raise original_error
                        return os_results
                    event = self._flights[key] = threading.Event()
            if owner:
                try:
                    ip = self._query(name, key[1])
                    with self._lock:
                        self._cache[key] = (self._clock() + (300 if ip else 5), ip)
                        self._cache.move_to_end(key)
                        while len(self._cache) > 256:
                            self._cache.popitem(last=False)
                finally:
                    with self._lock:
                        self._flights.pop(key, None)
                        event.set()
            else:
                event.wait(self._budget)
                _, ip = self._cached(key)
        if not ip:
            if original_error is not None:
                raise original_error
            return os_results
        return self._resolver(ip, port, family, type, proto, flags)

    def getaddrinfo(self, host, port, family=0, type=0, proto=0, flags=0):
        try:
            results = self._resolver(host, port, family, type, proto, flags)
        except socket.gaierror as error:
            results = None
            original_error = error
        else:
            original_error = None

        name = _ascii_domain_name(host)
        if results is not None:
            # Successful OS answer: screen it once (BUG-034). Only a
            # sinkhole-shaped answer pays the DoH round-trip.
            if name is None or not _looks_poisoned(name, results):
                return results
            return self._doh_resolve(name, family, port, type, proto, flags,
                                     (name.lower(), 28 if family == socket.AF_INET6 else 1),
                                     original_error=None, os_results=results)
        # Hard failure: the original DoH-on-gaierror behaviour is unchanged.
        if name is None:
            raise original_error from None
        return self._doh_resolve(name, family, port, type, proto, flags,
                                 (name.lower(), 28 if family == socket.AF_INET6 else 1),
                                 original_error=original_error)


def install():
    current = socket.getaddrinfo
    if getattr(current, '_nedotify_doh', False):
        return
    fallback = DnsFallback(current)
    def resolve(*args, **kwargs):
        return fallback.getaddrinfo(*args, **kwargs)
    resolve._nedotify_doh = True
    socket.getaddrinfo = resolve
