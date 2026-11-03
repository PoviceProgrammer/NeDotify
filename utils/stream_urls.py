"""Cheap local checks shared by stream caches; never probe the network."""

import base64
import binascii
import json
import time
from urllib.parse import parse_qs, urlsplit
from email.utils import parsedate_to_datetime


def stream_url_expired(url, *, now=None, margin=60.0):
    """Return True for an explicit expired provider/CDN expiry timestamp.

    YouTube uses ``expire`` and signed CDN URLs can use ``Expires``. Leave
    unknown/malformed tokens to the provider's normal TTL and retry path;
    interpreting every numeric query parameter as an expiry would reject
    perfectly playable streams. The margin leaves time to open the socket.
    """
    if not isinstance(url, str) or not url:
        return False
    try:
        query = parse_qs(urlsplit(url).query)
        deadline = (time.time() if now is None else now) + margin
        for name in ("expire", "Expires", "expires"):
            for value in query.get(name, ()):
                if value.isdigit() and len(value) >= 6 and int(value) <= deadline:
                    return True
                if name.lower() == "expires" and not value.isdigit():
                    try:
                        if parsedate_to_datetime(value).timestamp() <= deadline:
                            return True
                    except (TypeError, ValueError, OverflowError):
                        pass
        # SoundCloud's CloudFront URLs have two different deadlines: the
        # outer `expires` may be hours away while the signed Policy is valid
        # for only a few minutes. Both must hold. Reading the public policy
        # only rejects stale URLs; it never grants permission to a resource.
        for encoded in query.get('Policy', ()):
            if len(encoded) > 16384:
                continue
            try:
                raw = encoded.translate(str.maketrans('-_~', '+=/'))
                policy = json.loads(base64.b64decode(raw, validate=True))
                statements = policy.get('Statement', []) if isinstance(policy, dict) else []
                if not isinstance(statements, list):
                    continue
                for statement in statements:
                    if not isinstance(statement, dict):
                        continue
                    expiry = statement.get('Condition', {}).get('DateLessThan', {}).get('AWS:EpochTime')
                    if isinstance(expiry, (int, float)) and not isinstance(expiry, bool) and expiry <= deadline:
                        return True
            except (binascii.Error, ValueError, TypeError, AttributeError, UnicodeError, RecursionError):
                pass
        parsed = urlsplit(url)
        if (parsed.hostname or '').endswith(('music.yandex.net', 'storage.yandex.net')):
            parts = parsed.path.strip('/').split('/')
            if len(parts) >= 3 and parts[2].isdigit() and len(parts[2]) >= 9 and int(parts[2]) <= deadline:
                return True
    except (TypeError, ValueError, OverflowError):
        pass
    return False
