"""Deezer catalogue; full audio is matched against existing audio providers."""
import math
import threading
import time
from urllib.parse import urlencode

import requests

from services.base_service import BaseMusicService
from utils.requests_transport import PublicHTTPAdapter


class DeezerError(RuntimeError):
    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


class DeezerService(BaseMusicService):
    display_name = 'Deezer'

    def __init__(self, settings=None, providers=None):
        super().__init__()
        self.settings = settings
        self._providers = providers
        self._sessions = threading.local()

    @staticmethod
    def _id(value):
        value = str(value or '')
        if not value.isascii() or not value.isdecimal() or int(value) <= 0:
            raise DeezerError('Некорректный идентификатор Deezer')
        return value

    def _get(self, path, **params):
        session = getattr(self._sessions, 'session', None)
        if session is None:
            session = requests.Session()
            session.mount('https://', PublicHTTPAdapter(pool_connections=8, pool_maxsize=8, max_retries=0))
            self._sessions.session = session
        self.configure_session(session)
        url = 'https://api.deezer.com/' + path
        if params:
            url += '?' + urlencode(params)
        with session.get(url, timeout=(3, 5), allow_redirects=False) as response:
            if response.status_code != 200:
                raise DeezerError(f'Deezer HTTP {response.status_code}',
                                  response.status_code in (408, 429, 500, 502, 503, 504))
            data = response.json()
        if not isinstance(data, dict):
            raise DeezerError('Некорректный ответ Deezer')
        if data.get('error'):
            code = (data['error'] or {}).get('code')
            raise DeezerError('Deezer: каталог недоступен или плейлист закрыт', code in (4, 700))
        return data

    def _track(self, item, album=None):
        sid = self._id(item.get('id'))
        album = item.get('album') or album or {}
        artist = item.get('artist') or {}
        title = str(item.get('title') or '').strip()
        if not title or not artist.get('name'):
            raise DeezerError('Deezer вернул трек без названия или исполнителя')
        try:
            duration = float(item.get('duration') or 0)
        except (ValueError, TypeError):
            duration = 0
        if not math.isfinite(duration) or duration < 0:
            duration = 0
        track = {'id': 'deezer_' + sid, 'source': 'deezer', 'source_id': sid,
                 'source_url': 'https://www.deezer.com/track/' + sid,
                 'title': title, 'artist': artist['name'], 'album': album.get('title') or '',
                 'duration': duration, 'cover_url': album.get('cover_big') or album.get('cover_medium') or '',
                 'is_favorite': False}
        # Metadata only: never mistake a 30-second preview for the full track.
        self.set_search_cache('deezer:track:' + sid, track)
        return track

    def get_track(self, track_id):
        sid = self._id(track_id)
        cached = self.get_search_cache('deezer:track:' + sid)
        return dict(cached) if cached else self._track(self._get('track/' + sid))

    def get_artist(self, query: str) -> dict:
        """Fetch artist profile from Deezer API by artist name, returning high-res avatar and fan count."""
        try:
            data = self._get('search/artist', q=query, limit=10)
            items = data.get('data') or []
            if not items:
                return {}
            from services.music_matching import artist_matches
            first = next((item for item in items
                          if artist_matches(query, item.get('name') or '', self.settings)), None)
            if first is None:
                return {}
            sid = self._id(first.get('id'))
            name = first.get('name') or query
            picture = first.get('picture_xl') or first.get('picture_big') or first.get('picture_medium') or first.get('picture') or ''
            return {
                'id': sid,
                'name': name,
                'avatar_url': picture,
                'nb_fan': first.get('nb_fan') or 0
            }
        except Exception as exc:
            logger.debug("Deezer get_artist(%s) failed: %s", query, exc)
            return {}

    def search(self, query, callback=None, error_callback=None, limit=20, result_type=None, is_current=None):
        kind = {'album': 'album', 'albums': 'album', 'playlist': 'playlist', 'playlists': 'playlist', 'artist': 'artist', 'artists': 'artist'}.get(result_type, 'track')
        limit = max(1, min(int(limit), 100))
        key = f'deezer:search:{kind}:{limit}:{query}'
        cached = self.get_search_cache(key)
        if cached is not None:
            if callback and (not is_current or is_current()):
                callback(cached)
            return
        leader, success, failure = self._join_request((key, id(is_current)), callback, error_callback)
        if not leader:
            return
        def run():
            try:
                if is_current and not is_current():
                    raise DeezerError('Запрос устарел')
                data = self._get('search/' + kind, q=query, limit=limit)
                if not isinstance(data.get('data'), list):
                    raise DeezerError('Некорректный ответ поиска Deezer')
                results = []
                for item in data['data']:
                    if kind == 'track':
                        results.append(self._track(item))
                    elif kind == 'artist':
                        sid = self._id(item.get('id'))
                        name = item.get('name') or 'Deezer Artist'
                        cover = item.get('picture_xl') or item.get('picture_big') or item.get('picture_medium') or item.get('picture') or ''
                        nb_fan = item.get('nb_fan') or 0
                        results.append({'id': f'deezer_artist_{sid}', 'source': 'deezer', 'source_id': sid,
                                        'title': name, 'artist': name, 'name': name, 'type': 'artist',
                                        'cover_url': cover, 'avatar_url': cover,
                                        'subscribers': str(nb_fan) if nb_fan else '',
                                        'nb_fan': nb_fan})
                    else:
                        sid = self._id(item.get('id'))
                        results.append({'id': f'deezer_{kind}_{sid}', 'source': 'deezer', 'source_id': sid,
                                        'title': item.get('title') or 'Deezer', 'type': kind,
                                        'artist': (item.get('artist') or item.get('user') or {}).get('name') or '',
                                        'cover_url': item.get('cover_big') or item.get('picture_big') or '',
                                        'track_count': item.get('nb_tracks') or 0})
                self.set_search_cache(key, results)
                if not is_current or is_current():
                    success(results)
                else:
                    failure('Запрос устарел')
            except Exception as exc:
                failure(str(exc))
        if self.submit(run) is None:
            failure('Сервис остановлен')

    def collection(self, kind, collection_id, limit=2000, require_complete=False):
        if kind not in ('album', 'playlist'):
            raise DeezerError('Неизвестный тип коллекции Deezer')
        sid = self._id(collection_id)
        limit = max(1, min(int(limit), 2000))
        metadata = self._get(f'{kind}/{sid}')
        expected = int(metadata.get('nb_tracks') or 0)
        if require_complete and expected > limit:
            raise DeezerError(f'В плейлисте больше {limit} треков')
        tracks, seen, offset = [], set(), 0
        while offset < limit:
            page = self._get(f'{kind}/{sid}/tracks', index=offset, limit=min(100, limit - offset))
            items = page.get('data')
            if not isinstance(items, list):
                raise DeezerError('Не удалось прочитать страницу плейлиста Deezer')
            if not items:
                if page.get('next') or (require_complete and offset < expected):
                    raise DeezerError('Deezer вернул неполный плейлист. Повторите импорт.', True)
                break
            fresh = 0
            for item in items[:limit - offset]:
                track = self._track(item, metadata if kind == 'album' else None)
                if track['source_id'] not in seen:
                    seen.add(track['source_id'])
                    tracks.append(track)
                    fresh += 1
            offset += len(items)
            if not page.get('next'):
                if require_complete and offset < expected:
                    raise DeezerError('Deezer вернул неполный плейлист. Повторите импорт.', True)
                break
            if not fresh or (require_complete and offset >= limit):
                raise DeezerError('Не удалось получить полный плейлист Deezer')
        if not tracks:
            raise DeezerError('В плейлисте Deezer нет доступных треков')
        result = {'name': metadata.get('title') or 'Deezer', 'source': 'deezer', 'tracks': tracks}
        if kind == 'album':
            result['album'] = {'source': 'deezer', 'source_id': sid, 'type': 'album',
                'title': metadata.get('title') or '', 'artist': (metadata.get('artist') or {}).get('name') or '',
                'release_date': metadata.get('release_date') or '',
                'year': str(metadata.get('release_date') or '')[:4],
                'album_type': metadata.get('record_type') or 'album', 'track_count': len(tracks),
                'cover_url': metadata.get('cover_xl') or metadata.get('cover_big') or metadata.get('cover_medium') or ''}
        return result

    def get_playlist_tracks(self, playlist_id, limit=50, callback=None, error_callback=None):
        def run():
            try:
                tracks = self.collection('playlist', playlist_id, limit)['tracks']
                if callback:
                    callback(tracks)
            except Exception as exc:
                if error_callback:
                    error_callback(str(exc))
        if self.submit(run) is None and error_callback:
            error_callback('Сервис остановлен')

    def _audio_candidates(self, track_id, checkpoint=lambda: None):
        from core.playback_recovery import same_recording
        checkpoint()
        wanted = self.get_track(track_id)
        if not self._providers:
            raise DeezerError('Источники аудио не подключены')
        failures = []
        for source in ('youtube', 'soundcloud'):
            checkpoint()
            if self.settings and self.settings.get('services', source + '_enabled', True) is False:
                continue
            provider = self._providers(source)
            done, results, errors = threading.Event(), [], []
            def success(items, results=results, done=done):
                results.extend(items or [])
                done.set()
            def failure(error, errors=errors, done=done):
                errors.append(error)
                done.set()
            try:
                provider.search(f"{wanted['artist']} {wanted['title']}", max_results=5,
                                callback=success, error_callback=failure)
            except Exception as exc:
                failure(exc)
            deadline = time.monotonic() + 8
            while not done.wait(.1):
                checkpoint()
                if time.monotonic() >= deadline:
                    errors.append('Search timed out')
                    break
            checkpoint()
            failures.extend(errors)
            for candidate in results:
                if isinstance(candidate, dict) and candidate.get('source') == source and candidate.get('source_id') and same_recording(wanted, candidate):
                    yield provider, candidate
                    # One verified recording per provider per attempt keeps
                    # failures bounded; a queue retry can refresh the search.
                    break
        if failures:
            raise DeezerError('Не удалось проверить источники аудио: connection timeout', True)
        raise DeezerError('Подходящая версия трека Deezer не найдена в аудиоисточниках')

    def get_stream_url(self, track_id, callback=None, error_callback=None, quality='high', **kwargs):
        def run():
            try:
                provider, candidate = next(self._audio_candidates(track_id))
                def resolved(url, metadata=None):
                    meta = dict(metadata or {}, resolved_source=candidate['source'],
                                resolved_source_id=candidate['source_id'])
                    if callback:
                        callback(url, meta)
                provider.get_stream_url(candidate['source_id'], callback=resolved,
                                        error_callback=error_callback, quality=quality)
            except Exception as exc:
                if error_callback:
                    error_callback(str(exc))
        if self.submit_playback(run) is None and error_callback:
            error_callback('Сервис остановлен')

    def download_audio_sync(self, track_id, output_dir, download_context=None):
        checkpoint = download_context.checkpoint if download_context else lambda: None
        failure = None
        try:
            for provider, candidate in self._audio_candidates(track_id, checkpoint):
                checkpoint()
                try:
                    return provider.download_audio_sync(candidate['source_id'], output_dir, download_context=download_context)
                except Exception as exc:
                    from core.download_transfer import DownloadInterrupted
                    if isinstance(exc, DownloadInterrupted):
                        raise
                    checkpoint()  # Pause/cancel must never start another source.
                    if isinstance(exc, OSError) and getattr(exc, 'errno', None) in (13, 28):
                        raise
                    failure = exc
        except DeezerError as exc:
            if failure is not None:
                if getattr(exc, 'retryable', False) and not getattr(failure, 'retryable', False):
                    try:
                        failure.retryable = True
                    except (AttributeError, TypeError):
                        raise DeezerError(str(failure), retryable=True) from failure
                raise failure
            raise
