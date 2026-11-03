"""Backend-only Yandex token persistence and bounded renewal."""
import math
import time

import requests

from services.base_service import BaseMusicService


def store_yandex_token(settings, token, now=None):
    read = token.get if isinstance(token, dict) else lambda key, default=None: getattr(token, key, default)
    access = read('access_token')
    if not isinstance(access, str) or not access.strip():
        raise ValueError('Missing OAuth token')
    refresh = read('refresh_token')
    lifetime = float(read('expires_in') or 0)
    if not math.isfinite(lifetime) or lifetime < 0:
        raise ValueError('Invalid OAuth lifetime')
    settings.set('auth', 'yandex_token', access)
    if isinstance(refresh, str) and refresh:
        settings.set('auth', 'yandex_refresh_token', refresh)
    settings.set('auth', 'yandex_token_expires_at', (time.time() if now is None else now) + lifetime if lifetime else 0)
    settings.set('auth', 'yandex_token_valid', True)
    flush = getattr(settings, 'sync_flush_now', None)
    if callable(flush) and flush() is False:
        raise RuntimeError('OAuth token could not be persisted')


def refresh_yandex_token(settings):
    """Use the documented refresh grant without returning credentials to JS.

    https://www.yandex.ru/dev/id/doc/ru/tokens/refresh-client
    """
    if settings is None:
        return False
    refresh = settings.get('auth', 'yandex_refresh_token', '')
    client_id = settings.get('auth', 'oauth_client_id', '')
    if not refresh or not client_id:
        return False
    transport = BaseMusicService()
    transport.settings = settings
    with requests.Session() as session:
        transport.configure_session(session)
        response = session.post('https://oauth.yandex.ru/token', data={
            'grant_type': 'refresh_token', 'refresh_token': refresh, 'client_id': client_id,
            'client_secret': settings.get('auth', 'oauth_client_secret', ''),
        }, timeout=(2, 4), allow_redirects=False)
        if response.status_code != 200 or len(response.content) > 65_536:
            return False
        store_yandex_token(settings, response.json())
    return True


def store_vk_token(settings, token, now=None):
    read = token.get if isinstance(token, dict) else lambda key, default=None: getattr(token, key, default)
    access = read('access_token')
    if not isinstance(access, str) or not access.strip():
        raise ValueError('Missing OAuth token')
    settings.set('auth', 'vk_token', access)
    flush = getattr(settings, 'sync_flush_now', None)
    if callable(flush) and flush() is False:
        raise RuntimeError('OAuth token could not be persisted')


def store_spotify_token(settings, token, now=None):
    read = token.get if isinstance(token, dict) else lambda key, default=None: getattr(token, key, default)
    access = read('access_token')
    if not isinstance(access, str) or not access.strip():
        raise ValueError('Missing OAuth token')
    refresh = read('refresh_token')
    settings.set('auth', 'spotify_token', access)
    if isinstance(refresh, str) and refresh:
        settings.set('auth', 'spotify_refresh_token', refresh)
    flush = getattr(settings, 'sync_flush_now', None)
    if callable(flush) and flush() is False:
        raise RuntimeError('OAuth token could not be persisted')

