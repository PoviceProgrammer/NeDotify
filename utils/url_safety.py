"""
NeDotify - URL safety checks for outbound media requests.
"""

import ipaddress
import socket
from urllib.parse import urlparse


_BLOCKED_ATTRS = ("is_private", "is_loopback", "is_link_local", "is_reserved", "is_multicast", "is_unspecified")


def is_safe_media_url(url: str) -> bool:
    """True only for http(s) URLs whose host resolves exclusively to public addresses.

    DNS failures and unparsable hosts fail closed (return False).
    """
    try:
        parsed = urlparse(str(url or ""))
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or None)
    except (OSError, UnicodeError, ValueError):
        return False
    if not infos:
        return False
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0].split('%', 1)[0])
        except ValueError:
            return False
        if any(getattr(addr, attr) for attr in _BLOCKED_ATTRS):
            return False
    return True
