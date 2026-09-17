"""
AURA Music - Yandex Music Service
Search and stream audio from Yandex Music.
"""

from typing import Callable, Optional
import threading
import logging
import time
import os
import re
from services.base_service import BaseMusicService

try:
    from yandex_music import Client
    HAS_YANDEX = True
except ImportError:
    HAS_YANDEX = False


class YandexService(BaseMusicService):
    """Client-side Yandex Music extraction."""

    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings
        self.on_auth_error = None
        self.on_subscription_status = None
        self.auth_error = False
        self.logger = logging.getLogger(__name__)
        self._client = None
        self._client_lock = threading.Lock()

        if HAS_YANDEX:
            BaseMusicService.submit(self._get_client)

    @staticmethod
    def _extract_artists(artists_list, fallback="Unknown Artist") -> str:
        """Safely extract and join artist names."""
        if not artists_list:
            return fallback
        names = []
        for a in artists_list:
            name = getattr(a, "name", None)
            if isinstance(name, str) and name.strip():
                names.append(name.strip())
            elif isinstance(a, dict):
                n = a.get("name")
                if isinstance(n, str) and n.strip():
                    names.append(n.strip())
        return ", ".join(names) or fallback

    def _get_client(self):
        with self._client_lock:
            if not self._client and HAS_YANDEX:
                token = self.settings.get("auth", "yandex_token", "") if self.settings else ""
                if token and len(token.strip()) > 5:
                    try:
                        self._client = Client(token).init()
                        self.logger.info("Yandex Music client initialized with token.")
                        self.auth_error = False
                        if self.on_auth_error:
                            self.on_auth_error(False)
                        self._check_subscription()
                        return self._client
                    except Exception as e:
                        self.logger.error(f"Failed to initialize Yandex Music client with token: {e}")
                        self.auth_error = True
                        if self.on_auth_error:
                            self.on_auth_error(True)
                else:
                    self.auth_error = False
                    if self.on_auth_error:
                        self.on_auth_error(False)

                try:
                    self._client = Client().init()
                    self.logger.info("Yandex Music client initialized (anonymous).")
                except Exception as e:
                    self.logger.error(f"Failed to initialize Yandex Music client (anonymous): {e}")

            return self._client

    def _check_subscription(self):
        """Check if the user has an active Yandex Plus subscription."""
        try:
            if self._client and hasattr(self._client, 'me') and self._client.me:
                account = self._client.me.account
                plus = getattr(self._client.me, 'plus', None)
                has_plus = bool(plus and getattr(plus, 'has_plus', False))
                self.logger.info(f"Yandex account: {getattr(account, 'login', '?')}, Plus: {has_plus}")
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
            keys_to_remove = [k for k in self._stream_cache if k.isdigit() or k.startswith("ya_")]
            for k in keys_to_remove:
                self._stream_cache.pop(k, None)
            search_keys_to_remove = [k for k in self._search_cache if k.startswith("ya_")]
            for k in search_keys_to_remove:
                self._search_cache.pop(k, None)
        if HAS_YANDEX:
            BaseMusicService.submit(self._get_client)

    @property
    def available(self) -> bool:
        return HAS_YANDEX

    def search(self, query: str, max_results: int = 20, callback: Optional[Callable] = None, error_callback: Optional[Callable] = None):
        """Search Yandex Music for tracks."""
        if not query or not str(query).strip():
            if callback:
                callback([])
            return

        if not HAS_YANDEX:
            if error_callback:
                error_callback("Yandex Music client not initialized")
            return

        def _search():
            try:
                cache_key = f"ya_search:{query}"
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
                if search_result and getattr(search_result, "tracks", None):
                    results_list = getattr(search_result.tracks, "results", None) or []
                    for t in results_list[:max_results]:
                        cover_url = ""
                        cover_uri = getattr(t, "cover_uri", None)
                        if cover_uri:
                            if str(cover_uri).startswith(("http://", "https://")):
                                cover_url = str(cover_uri)
                            else:
                                cover_url = f'https://{str(cover_uri).replace("%%", "400x400")}'

                        artist_name = self._extract_artists(getattr(t, "artists", None))
                        title = getattr(t, "title", None) or "Unknown Title"
                        track_id = getattr(t, "id", "")
                        duration_ms = getattr(t, "duration_ms", 0) or 0

                        track = {
                            "title": title,
                            "artist": artist_name,
                            "duration": duration_ms / 1000.0 if duration_ms else 0,
                            "source": "yandex",
                            "source_id": str(track_id),
                            "source_url": f"https://music.yandex.ru/track/{track_id}",
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

        BaseMusicService.submit(_search)

    def get_stream_url(self, track_id: str, callback: Callable = None, error_callback: Callable = None, **kwargs):
        """Extract direct audio stream URL from a Yandex Music track."""
        if not track_id or not str(track_id).strip() or str(track_id).strip().lower() == "none":
            if error_callback:
                error_callback("Неверный ID трека")
            return None

        if not HAS_YANDEX:
            if error_callback:
                error_callback('Функция yandex-music отключена')
            return None

        raw_id = str(track_id).strip()
        if raw_id.startswith("http"):
            m = re.search(r"/track/(\d+)", raw_id)
            if m:
                raw_id = m.group(1)
            else:
                if error_callback:
                    error_callback('Не удалось извлечь ID трека из URL')
                return None

        raw_id = re.sub(r'^(?:yandex|ya|track):', '', raw_id)
        raw_id = raw_id.split(":")[0].strip()
        if not raw_id or raw_id.lower() == "none":
            if error_callback:
                error_callback("Неверный ID трека")
            return None

        info = self.get_from_cache(raw_id)
        if info:
            if callback:
                callback(info.get("stream_url"), info)
            return None

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
                download_infos = track.get_download_info(get_direct_links=True)
                if not download_infos:
                    if error_callback:
                        error_callback('Нет доступных аудиопотоков. Возможно, трек доступен только по подписке')
                    return

                best_info = download_infos[0]
                for info in download_infos:
                    b_bitrate = getattr(best_info, "bitrate_in_kbps", 0) or 0
                    i_bitrate = getattr(info, "bitrate_in_kbps", 0) or 0
                    if getattr(info, "codec", "") == 'mp3' and i_bitrate > b_bitrate:
                        best_info = info

                stream_url = getattr(best_info, "direct_link", None)
                if not stream_url and callable(getattr(best_info, "get_direct_link", None)):
                    try:
                        stream_url = best_info.get_direct_link()
                    except Exception:
                        stream_url = None

                cover_url = ""
                cover_uri = getattr(track, "cover_uri", None)
                if cover_uri:
                    if str(cover_uri).startswith(("http://", "https://")):
                        cover_url = str(cover_uri)
                    else:
                        cover_url = f'https://{str(cover_uri).replace("%%", "400x400")}'

                artist_name = self._extract_artists(getattr(track, "artists", None))
                title = getattr(track, "title", None) or "Unknown Title"
                duration_ms = getattr(track, "duration_ms", 0) or 0

                metadata = {
                    "title": title,
                    "artist": artist_name,
                    "duration": duration_ms / 1000.0 if duration_ms else 0,
                    "cover_url": cover_url,
                    "source_id": str(getattr(track, "id", raw_id)),
                    "stream_url": stream_url,
                    "format": getattr(best_info, "codec", "mp3"),
                    "bitrate": getattr(best_info, "bitrate_in_kbps", 0) or 0
                }

                self.set_to_cache(raw_id, metadata)
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

        BaseMusicService.submit(_extract)
        return None

    def download_audio_sync(self, source_id: str, output_dir: str) -> str:
        """Download audio synchronously from Yandex Music."""
        if not source_id or not str(source_id).strip() or str(source_id).strip().lower() == "none":
            raise ValueError("source_id не может быть пустым")

        client = self._get_client()
        if not client:
            raise Exception("Yandex Music клиент не инициализирован")

        os.makedirs(output_dir, exist_ok=True)
        raw_id = str(source_id).strip()
        if raw_id.startswith("http"):
            m = re.search(r"/track/(\d+)", raw_id)
            if m:
                raw_id = m.group(1)
        raw_id = re.sub(r'^(?:yandex|ya|track):', '', raw_id)
        raw_id = raw_id.split(":")[0].strip()
        if not raw_id or raw_id.lower() == "none":
            raise ValueError("Неверный ID трека")

        tracks = client.tracks([raw_id])
        if not tracks:
            raise Exception("Трек не найден в Яндекс Музыке")

        track = tracks[0]
        file_name = f"ya_{raw_id}_{int(time.time())}.mp3"
        output_path = os.path.join(output_dir, file_name)
        part_path = f"{output_path}.part"

        try:
            track.download(part_path, codec="mp3", bitrate_in_kbps=320)
            if os.path.exists(part_path):
                try:
                    if os.path.getsize(part_path) == 0:
                        raise Exception("Файл пуст после загрузки из Яндекс Музыки")
                except OSError:
                    pass
                try:
                    os.replace(part_path, output_path)
                except OSError:
                    pass
            if not os.path.exists(output_path) and not os.path.exists(part_path):
                raise Exception("Файл не был создан после загрузки из Яндекс Музыки")
        except Exception:
            for p in (part_path, output_path):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            raise

        return output_path
