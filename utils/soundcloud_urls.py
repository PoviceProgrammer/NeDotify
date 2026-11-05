"""Resolve official SoundCloud playlist share links before provider extraction."""
import re
import urllib.parse
import urllib.request


def resolve_playlist_share_url(target: str) -> str:
    parsed = urllib.parse.urlsplit(target)
    if parsed.hostname != 'on.soundcloud.com':
        return target
    if (parsed.scheme not in ('http', 'https') or parsed.username or parsed.password
            or not re.fullmatch(r'/[A-Za-z0-9_-]+/?', parsed.path)):
        raise ValueError('Некорректная короткая ссылка SoundCloud')

    # Use the same DNS/redirect-guarded transport as playlist extraction.
    # A desktop user agent follows the web link instead of an app deep link.
    from utils.url_safety import guarded_open_url
    request = urllib.request.Request(target, headers={'User-Agent': 'Mozilla/5.0'})
    with guarded_open_url(request, timeout=6) as response:
        resolved = response.geturl()
    final = urllib.parse.urlsplit(resolved)
    if (final.scheme not in ('http', 'https') or final.username or final.password
            or final.hostname not in ('soundcloud.com', 'www.soundcloud.com')
            or not re.fullmatch(r'/[^/]+/sets/[^/]+/?', final.path)):
        raise ValueError('Короткая ссылка ведёт не на плейлист SoundCloud')
    return resolved
