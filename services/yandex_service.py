"""
NeDotify - Yandex Music Service
Search and stream audio from Yandex Music.
"""

from typing import Callable, Optional
import re
import threading
import logging
import time
from urllib.parse import urlsplit
from concurrent.futures import ThreadPoolExecutor
from services.base_service import BaseMusicService, normalize_proxy_url

try:
    from yandex_music import Client
    HAS_YANDEX = True
except ImportError:
    HAS_YANDEX = False


class YandexService(BaseMusicService):
    """Client-side Yandex Music extraction."""

    def __init__(self, settings=None, on_auth_error=None, on_subscription_status=None):
        super().__init__()
        self.settings = settings
        self.on_auth_error = on_auth_error
        self.on_subscription_status = on_subscription_status
        self.auth_error = False
        self._executor = ThreadPoolExecutor(max_workers=3)
        self.logger = logging.getLogger(__name__)
        self._client = None
        self._client_config = None
        self._client_lock = threading.Lock()

        if HAS_YANDEX:
            self._executor.submit(self._get_client)

    @staticmethod
    def _extract_track_id(value):
        """Normalize a Yandex track id or supported Yandex track URL."""
        raw = str(value or '').strip()
        if not raw:
            return ''
        if raw.lower().startswith(('http://', 'https://')):
            try:
                parsed = urlsplit(raw)
            except ValueError:
                return ''
            if (parsed.hostname or '').lower() not in {'music.yandex.ru', 'music.yandex.com'}:
                return ''
            match = re.search(r'(?:^|/)track/(\d+)(?:/|$)', parsed.path)
            return match.group(1) if match else ''
        if raw.lower().startswith('yandex:'):
            raw = raw.split(':', 1)[1].strip()
        return raw if re.fullmatch(r'\d+', raw) else ''

    def _get_client(self):
        with self._client_lock:
            expires = self.settings.get('auth', 'yandex_token_expires_at', 0) if self.settings else 0
            try:
                needs_refresh = 0 < float(expires) <= time.time() + 60
            except (TypeError, ValueError):
                needs_refresh = False
            if needs_refresh and time.monotonic() - getattr(self, '_last_refresh_attempt', -1e9) > 30:
                self._last_refresh_attempt = time.monotonic()
                try:
                    from core.oauth import refresh_yandex_token
                    refresh_yandex_token(self.settings)
                except Exception:
                    self.logger.warning('Yandex OAuth renewal failed')
        token = str(self.settings.get("auth", "yandex_token", "") or "").strip() if self.settings else ""
        proxy = normalize_proxy_url(self.settings.get("auth", "proxy_url", "")) if self.settings else ""
        config = (token, proxy)
        with self._client_lock:
            if config != self._client_config:
                self._client = None
                self.auth_error = False
                self._client_config = config
                with self._cache_lock:
                    for key in list(self._stream_cache):
                        if key.startswith('yandex:'):
                            self._stream_cache.pop(key, None)
                    for key in list(self._search_cache):
                        if key.startswith('ya_'):
                            self._search_cache.pop(key, None)
            if self._client or not HAS_YANDEX or self.auth_error:
                return self._client
            try:
                from yandex_music.utils.request import Request
                self._client = Client(token or None, request=Request(proxy_url=proxy or None)).init()
                self.auth_error = False
                if self.on_auth_error:
                    self.on_auth_error(False)
                self._check_subscription()
            except Exception:
                self._client = None
                self.auth_error = bool(token)
                self.logger.warning('Yandex Music authentication/connection failed', exc_info=True)
                if self.on_auth_error:
                    self.on_auth_error(self.auth_error)
            return self._client

    def _check_subscription(self):
        """Check if the user has an active Yandex Plus subscription."""
        try:
            if self._client and hasattr(self._client, 'me') and self._client.me:
                account = self._client.me.account
                plus = getattr(self._client.me, 'plus', None)
                has_plus = bool(plus and getattr(plus, 'has_plus', False))
                self.logger.info('Yandex subscription available: %s', has_plus)
                if not has_plus:
                    self.logger.warning('No Yandex Plus subscription — tracks limited to 30-sec previews!')
                    if self.on_subscription_status:
                        self.on_subscription_status(False)
                        return
                    return
                if self.on_subscription_status:
                    self.on_subscription_status(True)
                    return
        except Exception as e:
            self.logger.debug(f'Could not check subscription: {e}')

    def reset_client(self):
        """Reset client and clear all yandex-related caches."""
        with self._client_lock:
            self._client = None
        with self._cache_lock:
            keys_to_remove = [k for k in self._stream_cache if k.startswith("yandex:")]
            for k in keys_to_remove:
                self._stream_cache.pop(k, None)
            search_keys_to_remove = [k for k in self._search_cache if k.startswith("ya_")]
            for k in search_keys_to_remove:
                self._search_cache.pop(k, None)
        if HAS_YANDEX:
            self._executor.submit(self._get_client)

    @property
    def available(self) -> bool:
        return HAS_YANDEX
    def search(self, query: str, max_results: int = 20, callback: Optional[Callable] = None, error_callback: Optional[Callable] = None):
        """Search Yandex Music for tracks."""
        if not HAS_YANDEX:
            if error_callback:
                error_callback("Yandex Music client not initialized")
            return

        def _search():
            try:
                self._get_client()
                cache_key = f"ya_search:{query}:{max_results}"
                cached = self.get_search_cache(cache_key)
                if cached is not None:
                    if callback:
                        callback(cached)
                    return

                client = self._get_client()
                if not client:
                    if error_callback:
                        error_callback("Yandex Music client not initialized")
                    return

                search_result = client.search(query, type_="track")
                tracks = []
                if search_result and search_result.tracks:
                    for t in search_result.tracks.results[:max_results]:
                        cover_url = ""
                        if t.cover_uri:
                            cover_url = f'https://{t.cover_uri.replace("%%", "400x400")}'

                        artist_name = 'Unknown Artist'
                        if t.artists:
                            artist_name = ", ".join(a.name for a in t.artists)
                        track = {
                            "title": t.title,
                            "artist": artist_name,
                            "duration": t.duration_ms / 1000.0 if t.duration_ms else 0,
                            "source": "yandex",
                            "source_id": str(t.id),
                            "source_url": f"https://music.yandex.ru/track/{t.id}",
                            "cover_url": cover_url
                        }
                        tracks.append(track)

                self.set_search_cache(cache_key, tracks)
                if callback:
                    callback(tracks)
            except Exception as e:
                self.logger.exception('Ошибка при поиске Yandex Music')
                if error_callback:
                    error_callback(f'Произошла ошибка: {type(e).__name__} - {str(e)}')

        self._executor.submit(_search)

    def get_stream_url(self, track_id: str, callback: Callable = None, error_callback: Callable = None, **kwargs):
        """Extract direct audio stream URL from a Yandex Music track."""
        if not HAS_YANDEX:
            if error_callback:
                error_callback('Функция yandex-music отключена')
            return

        raw_id = self._extract_track_id(track_id)
        if not raw_id:
            if error_callback:
                error_callback('Не удалось извлечь ID трека из URL')
            return

        token = str(self.settings.get('auth', 'yandex_token', '') or '').strip() if self.settings else ''
        proxy = normalize_proxy_url(self.settings.get('auth', 'proxy_url', '')) if self.settings else ''
        info = self.get_from_cache(f"yandex:{raw_id}") if (token, proxy) == self._client_config else None
        if info:
            if callback:
                callback(info.get("stream_url"), info)
            return

        leader, callback, error_callback = self._join_request(
            ('yandex:stream', raw_id, token, proxy), callback, error_callback)
        if not leader:
            return

        def _extract():
            try:
                client = self._get_client()
                if not client:
                    if error_callback:
                        error_callback('Yandex Music client not initialized')
                    return

                tracks = client.tracks([raw_id])
                if not tracks:
                    if error_callback:
                        error_callback('Трек не найден')
                    return

                track = tracks[0]
                # Each direct link requires a separate signed XML request.
                # Resolve the chosen quality only, rather than all formats.
                download_infos = track.get_download_info()
                if not download_infos:
                    if error_callback:
                        error_callback('Нет доступных аудиопотоков. Возможно, трек доступен только по подписке')
                    return

                best_info = download_infos[0]
                for info in download_infos:
                    if info.codec == 'mp3' and info.bitrate_in_kbps > best_info.bitrate_in_kbps:
                        best_info = info

                stream_url = best_info.direct_link or best_info.get_direct_link()
                cover_url = ""
                if track.cover_uri:
                    cover_url = f'https://{track.cover_uri.replace("%%", "400x400")}'

                artist_name = 'Unknown Artist'
                if track.artists:
                    artist_name = ", ".join(a.name for a in track.artists)

                metadata = {
                    "title": track.title,
                    "artist": artist_name,
                    "duration": track.duration_ms / 1000.0 if track.duration_ms else 0,
                    "cover_url": cover_url,
                    "source_id": str(track.id),
                    "stream_url": stream_url,
                    "format": best_info.codec,
                    "bitrate": best_info.bitrate_in_kbps
                }

                self.set_to_cache(f"yandex:{raw_id}", metadata)
                if callback:
                    callback(stream_url, metadata)
            except Exception as e:
                err_name = type(e).__name__
                err_str = str(e)
                self.logger.exception('Ошибка при извлечении потока Yandex Music')

                if 'BadRequestError' in err_name or 'validate' in err_str:
                    msg = 'Трек недоступен (нет прав или требуется подписка Яндекс Музыки)'
                elif 'Unauthorized' in err_name or '401' in err_str:
                    msg = 'Ошибка авторизации Яндекс Музыки. Добавьте токен в Настройки → Авторизация'
                elif 'NotFound' in err_name or '404' in err_str:
                    msg = 'Трек не найден в Яндекс Музыке'
                else:
                    msg = f'Ошибка Яндекс Музыки: {err_name}'

                if error_callback:
                    error_callback(msg)

        if self.submit_playback(_extract) is None:
            error_callback('Сервис завершает работу')
        return None

    def download_audio_sync(self, source_id: str, output_dir: str, download_context=None) -> str:
        """Download audio synchronously from Yandex Music."""
        import os
        import time
        client = self._get_client()
        if not client:
            raise Exception("Yandex Music клиент не инициализирован")

        raw_id = self._extract_track_id(source_id)
        if not raw_id:
            raise ValueError('Некорректный ID трека Яндекс.Музыки')
        if download_context:
            download_context.checkpoint()
        tracks = client.tracks([raw_id])
        if not tracks:
            raise Exception("Трек не найден в Яндекс Музыке")

        track = tracks[0]
        safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', raw_id)
        file_name = f"ya_{safe_id}_{int(time.time())}.mp3"
        if download_context:
            download_context.checkpoint()
            variants = [item for item in track.get_download_info() if item.codec == 'mp3']
            if not variants:
                raise Exception('Для трека нет доступной MP3-загрузки')
            variant = max(variants, key=lambda item: int(item.bitrate_in_kbps or 0))
            output_path = os.path.join(output_dir, download_context.stem + '.mp3')
            return download_context.download_http(variant.get_direct_link(), output_path)
        output_path = os.path.join(output_dir, file_name)
        track.download(output_path, codec="mp3", bitrate_in_kbps=320)

        if not os.path.exists(output_path):
            raise Exception("Файл не был создан после загрузки из Яндекс Музыки")

        return output_path

