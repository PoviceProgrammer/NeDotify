"""
NeDotify / AURA Music - Last.fm Service Wrapper
Provides Last.fm open API querying with API key rotation, multi-TTL caching,
SQLite response caching, rate-limiting resilience, and graceful offline/error handling.
"""

import os
import json
import time
import sqlite3
import logging
import threading
import requests
from typing import Callable, Optional, List, Dict, Any
from services.base_service import BaseMusicService

logger = logging.getLogger(__name__)

API_KEYS = [
    'b25b959554ed76058ac220b7b2e0a026',
    '7f005c21966a362eb5a214d0f622d1f4',
    'a71c8413df426c117d6ee2c85e2586bf',
    'c14c0003b12368c8b211ab9f1c79e6fb',
    '2c8038f0d5757d5f0426315220c8f133',
    '4cb0edd8ea11e4f641723f031a770edc',
]

RECOMMENDATION_TTL = 604800
CHART_TTL = 86400


class LastFmArtistHandler:
    """Namespace wrapper for artist queries."""

    def __init__(self, service: 'LastFMService'):
        self._service = service

    def getSimilar(self, artist: str, limit: int = 10) -> List[Dict]:
        return self._service.artist_get_similar(artist, limit=limit)

    def getTopTracks(self, artist: str, limit: int = 10) -> List[Dict]:
        return self._service.artist_get_top_tracks(artist, limit=limit)

    def getTopTags(self, artist: str) -> List[Dict]:
        return self._service.artist_get_top_tags(artist)


class LastFmTrackHandler:
    """Namespace wrapper for track queries."""

    def __init__(self, service: 'LastFMService'):
        self._service = service

    def getSimilar(self, artist: str, track: str, limit: int = 10) -> List[Dict]:
        return self._service.track_get_similar(artist, track, limit=limit)


class LastFmChartHandler:
    """Namespace wrapper for chart queries."""

    def __init__(self, service: 'LastFMService'):
        self._service = service

    def getTopTracks(self, limit: int = 20) -> List[Dict]:
        return self._service.chart_get_top_tracks(limit=limit)

    def getTopArtists(self, limit: int = 20) -> List[Dict]:
        return self._service.chart_get_top_artists(limit=limit)


class LastFmUserHandler:
    """Namespace wrapper for user scrobble queries."""

    def __init__(self, service: 'LastFMService'):
        self._service = service

    def getRecentTracks(self, user: str, limit: int = 10) -> List[Dict]:
        return self._service.user_get_recent_tracks(user, limit=limit)

    def getTopArtists(self, user: str, limit: int = 10) -> List[Dict]:
        return self._service.user_get_top_artists(user, limit=limit)


class LastFMService(BaseMusicService):
    """Last.fm API Client with key rotation, SQLite caching, and rate limiting resilience."""

    BASE_URL = 'http://ws.audioscrobbler.com/2.0/'

    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings
        self.logger = logging.getLogger(self.__class__.__name__)
        self._key_index = 0
        self._key_lock = threading.Lock()
        self._bad_keys = set()

        env_key = os.getenv('LASTFM_API_KEY')
        if env_key and env_key not in API_KEYS:
            API_KEYS.insert(0, env_key)

        if self.settings:
            cfg_key = self.settings.get('auth', 'lastfm_api_key', '')
            if cfg_key and cfg_key not in API_KEYS:
                API_KEYS.insert(0, cfg_key)

        self._cache = {}
        self._cache_lock = threading.Lock()

        self._db_path = self._init_sqlite_cache_path()
        self._init_sqlite_cache_db()

        self.artist = LastFmArtistHandler(self)
        self.track = LastFmTrackHandler(self)
        self.chart = LastFmChartHandler(self)
        self.user = LastFmUserHandler(self)

        self._session_local = threading.local()

        # M-7: token-bucket rate limiter (Condition-based, never time.sleep in the sync path)
        self._rate_capacity = 5.0
        self._rate_tokens = self._rate_capacity
        self._rate_last_refill = time.time()
        self._rate_lock = threading.Condition()

    def _get_session(self) -> requests.Session:
        """Per-thread requests.Session (M-7): Sessions are not thread-safe."""
        session = getattr(self._session_local, 'session', None)
        if session is None:
            session = requests.Session()
            session.headers.update({'User-Agent': 'AURA-Music/1.0 (RecommendationEngine)'})
            self._session_local.session = session
        return session

    def _acquire_token(self) -> None:
        """Token-bucket rate limiter: waits via Condition, never time.sleep (M-7)."""
        with self._rate_lock:
            while True:
                now = time.time()
                elapsed = now - self._rate_last_refill
                self._rate_tokens = min(self._rate_capacity, self._rate_tokens + elapsed * 2.0)
                self._rate_last_refill = now
                if self._rate_tokens >= 1.0:
                    self._rate_tokens -= 1.0
                    return
                wait_for = (1.0 - self._rate_tokens) / 2.0
                self._rate_lock.wait(timeout=min(wait_for, 2.0))

    def _init_sqlite_cache_path(self) -> str:
        base_dir = os.path.join(os.path.expanduser('~'), '.nedotify', 'cache')
        try:
            os.makedirs(base_dir, exist_ok=True)
            return os.path.join(base_dir, 'lastfm_cache.db')
        except Exception:
            return ':memory:'

    def _init_sqlite_cache_db(self):
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS lastfm_response_cache (
                        cache_key TEXT PRIMARY KEY,
                        json_data TEXT,
                        timestamp REAL,
                        ttl REAL
                    )
                ''')
                conn.commit()
        except Exception as e:
            self.logger.warning(f'Failed to initialize Last.fm SQLite cache DB: {e}')

    @property
    def available(self) -> bool:
        return True

    def _mark_bad_key(self, api_key: str):
        with self._key_lock:
            if api_key and api_key not in self._bad_keys:
                self._bad_keys.add(api_key)
                self.logger.warning(f'Disabling invalid/blocked Last.fm API key: {api_key[:6]}...')

    def _get_next_api_key(self) -> str:
        with self._key_lock:
            valid_keys = [k for k in API_KEYS if k not in self._bad_keys]
            if valid_keys:
                key = valid_keys[self._key_index % len(valid_keys)]
                self._key_index = (self._key_index + 1) % len(valid_keys)
                return key
            if API_KEYS:
                return API_KEYS[0]
            return ''

    def _get_cached(self, cache_key: str) -> Optional[Any]:
        with self._cache_lock:
            entry = self._cache.get(cache_key)
            if entry and time.time() - entry['ts'] <= entry['ttl']:
                return entry['data']
        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT json_data, timestamp, ttl FROM lastfm_response_cache WHERE cache_key = ?',
                               (cache_key,))
                row = cursor.fetchone()
                if row:
                    json_str, ts, ttl = row
                    if time.time() - ts <= ttl:
                        data = json.loads(json_str)
                        with self._cache_lock:
                            self._cache[cache_key] = {'data': data, 'ts': ts, 'ttl': ttl}
                        return data
        except Exception as e:
            self.logger.debug(f'SQLite cache lookup error: {e}')
        return None

    def _get_stale_cache(self, cache_key: str) -> Optional[Any]:
        with self._cache_lock:
            entry = self._cache.get(cache_key)
            if entry:
                return entry['data']
        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT json_data FROM lastfm_response_cache WHERE cache_key = ?',
                               (cache_key,))
                row = cursor.fetchone()
                if row:
                    return json.loads(row[0])
        except Exception:
            pass
        return None

    def _set_cache(self, cache_key: str, data: Any, ttl: float):
        now = time.time()
        with self._cache_lock:
            self._cache[cache_key] = {'data': data, 'ts': now, 'ttl': ttl}
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute('INSERT OR REPLACE INTO lastfm_response_cache (cache_key, json_data, timestamp, ttl) VALUES (?, ?, ?, ?)',
                             (cache_key, json.dumps(data), now, ttl))
                conn.commit()
        except Exception as e:
            self.logger.debug(f'SQLite cache store error: {e}')

    def _api_request(self, method: str, params: dict, ttl: float) -> Optional[dict]:
        cache_key = f'{method}:' + '&'.join(f'{k}={v}' for k, v in sorted(params.items()))
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        attempts = len(API_KEYS)
        for _ in range(attempts):
            api_key = self._get_next_api_key()
            if not api_key or api_key in self._bad_keys:
                continue

            req_params = {'method': method, 'api_key': api_key, 'format': 'json'}
            req_params.update(params)
            self._acquire_token()
            try:
                resp = self._get_session().get(self.BASE_URL, params=req_params, timeout=5.0)
                if resp.status_code == 200:
                    data = resp.json()
                    if 'error' in data:
                        err_code = data.get('error')
                        if err_code in (10, 26):
                            self.logger.warning(f'Last.fm API key rejected (code {err_code}): {data.get("message")}')
                            self._mark_bad_key(api_key)
                            continue
                        self.logger.warning(f'Last.fm API error {err_code}: {data.get("message")}. Rotating key.')
                        continue
                    self._set_cache(cache_key, data, ttl)
                    return data
                if resp.status_code in (401, 403):
                    self.logger.warning(f'Last.fm HTTP {resp.status_code} (Forbidden/Unauthorized). Disabling key.')
                    self._mark_bad_key(api_key)
                    continue
                if resp.status_code in (429, 503):
                    self.logger.warning(f'Last.fm HTTP {resp.status_code}. Rate limit backoff & rotating API key.')
                    continue
                self.logger.warning(f'Last.fm HTTP {resp.status_code}: {resp.text}')
                continue
            except Exception as e:
                self.logger.warning(f'Last.fm request failed: {e}')

        stale = self._get_stale_cache(cache_key)
        if stale is not None:
            self.logger.info(f'Using stale cached response for {method}')
            return stale
        return None

    def artist_get_similar(self, artist: str, limit: int = 10, callback: Callable = None) -> List[Dict]:
        def _task():
            data = self._api_request('artist.getsimilar', {'artist': artist, 'limit': limit}, RECOMMENDATION_TTL)
            results = []
            if data and 'similarartists' in data:
                artists_raw = data['similarartists'].get('artist', [])
                if isinstance(artists_raw, dict):
                    artists_raw = [artists_raw]
                for a in artists_raw[:limit]:
                    images = a.get('image', [])
                    if isinstance(images, list) and images:
                        img_url = images[-1].get('#text', '')
                    else:
                        img_url = ''
                    match_val = float(a.get('match', 0)) if a.get('match') else 0.0
                    results.append({
                        'name': a.get('name', ''),
                        'match': match_val,
                        'url': a.get('url', ''),
                        'image': img_url,
                        'mbid': a.get('mbid', ''),
                    })
            if callback:
                callback(results)
            return results

        if callback:
            self._executor.submit(_task)
            return []
        return _task()

    def artist_get_top_tracks(self, artist: str, limit: int = 10, callback: Callable = None) -> List[Dict]:
        def _task():
            data = self._api_request('artist.gettoptracks', {'artist': artist, 'limit': limit}, RECOMMENDATION_TTL)
            results = []
            if data and 'toptracks' in data:
                tracks_raw = data['toptracks'].get('track', [])
                if isinstance(tracks_raw, dict):
                    tracks_raw = [tracks_raw]
                for t in tracks_raw[:limit]:
                    images = t.get('image', [])
                    if isinstance(images, list) and images:
                        img_url = images[-1].get('#text', '')
                    else:
                        img_url = ''
                    if isinstance(t.get('artist'), dict):
                        artist_name = t.get('artist', {}).get('name', artist)
                    else:
                        artist_name = artist
                    results.append({
                        'name': t.get('name', ''),
                        'artist': artist_name,
                        'playcount': int(t.get('playcount', 0)) if t.get('playcount') else 0,
                        'listeners': int(t.get('listeners', 0)) if t.get('listeners') else 0,
                        'url': t.get('url', ''),
                        'image': img_url,
                    })
            if callback:
                callback(results)
            return results

        if callback:
            self._executor.submit(_task)
            return []
        return _task()

    def artist_get_top_tags(self, artist: str, callback: Callable = None) -> List[Dict]:
        def _task():
            data = self._api_request('artist.gettoptags', {'artist': artist}, RECOMMENDATION_TTL)
            results = []
            if data and 'toptags' in data:
                tags_raw = data['toptags'].get('tag', [])
                if isinstance(tags_raw, dict):
                    tags_raw = [tags_raw]
                for tag in tags_raw:
                    results.append({
                        'name': tag.get('name', ''),
                        'count': int(tag.get('count', 0)) if tag.get('count') else 0,
                        'url': tag.get('url', ''),
                    })
            if callback:
                callback(results)
            return results

        if callback:
            self._executor.submit(_task)
            return []
        return _task()

    def track_get_similar(self, artist: str, track: str, limit: int = 10, callback: Callable = None) -> List[Dict]:
        def _task():
            data = self._api_request('track.getsimilar', {'artist': artist, 'track': track, 'limit': limit},
                                     RECOMMENDATION_TTL)
            results = []
            if data and 'similartracks' in data:
                tracks_raw = data['similartracks'].get('track', [])
                if isinstance(tracks_raw, dict):
                    tracks_raw = [tracks_raw]
                for t in tracks_raw[:limit]:
                    images = t.get('image', [])
                    if isinstance(images, list) and images:
                        img_url = images[-1].get('#text', '')
                    else:
                        img_url = ''
                    if isinstance(t.get('artist'), dict):
                        artist_name = t.get('artist', {}).get('name', '')
                    else:
                        artist_name = ''
                    match_val = float(t.get('match', 0)) if t.get('match') else 0.0
                    duration = int(t.get('duration', 0)) if t.get('duration') else 0
                    results.append({
                        'name': t.get('name', ''),
                        'artist': artist_name,
                        'match': match_val,
                        'duration': duration,
                        'url': t.get('url', ''),
                        'image': img_url,
                    })
            if callback:
                callback(results)
            return results

        if callback:
            self._executor.submit(_task)
            return []
        return _task()

    def chart_get_top_tracks(self, limit: int = 20, callback: Callable = None) -> List[Dict]:
        def _task():
            data = self._api_request('chart.gettoptracks', {'limit': limit}, CHART_TTL)
            results = []
            if data and 'tracks' in data:
                tracks_raw = data['tracks'].get('track', [])
                if isinstance(tracks_raw, dict):
                    tracks_raw = [tracks_raw]
                for t in tracks_raw[:limit]:
                    images = t.get('image', [])
                    if isinstance(images, list) and images:
                        img_url = images[-1].get('#text', '')
                    else:
                        img_url = ''
                    if isinstance(t.get('artist'), dict):
                        artist_name = t.get('artist', {}).get('name', '')
                    else:
                        artist_name = ''
                    results.append({
                        'name': t.get('name', ''),
                        'artist': artist_name,
                        'playcount': int(t.get('playcount', 0)) if t.get('playcount') else 0,
                        'listeners': int(t.get('listeners', 0)) if t.get('listeners') else 0,
                        'url': t.get('url', ''),
                        'image': img_url,
                    })
            if callback:
                callback(results)
            return results

        if callback:
            self._executor.submit(_task)
            return []
        return _task()

    def chart_get_top_artists(self, limit: int = 20, callback: Callable = None) -> List[Dict]:
        def _task():
            data = self._api_request('chart.gettopartists', {'limit': limit}, CHART_TTL)
            results = []
            if data and 'artists' in data:
                artists_raw = data['artists'].get('artist', [])
                if isinstance(artists_raw, dict):
                    artists_raw = [artists_raw]
                for a in artists_raw[:limit]:
                    images = a.get('image', [])
                    if isinstance(images, list) and images:
                        img_url = images[-1].get('#text', '')
                    else:
                        img_url = ''
                    results.append({
                        'name': a.get('name', ''),
                        'playcount': int(a.get('playcount', 0)) if a.get('playcount') else 0,
                        'listeners': int(a.get('listeners', 0)) if a.get('listeners') else 0,
                        'url': a.get('url', ''),
                        'image': img_url,
                    })
            if callback:
                callback(results)
            return results

        if callback:
            self._executor.submit(_task)
            return []
        return _task()

    def user_get_recent_tracks(self, user: str, limit: int = 10, callback: Callable = None) -> List[Dict]:
        def _task():
            data = self._api_request('user.getrecenttracks', {'user': user, 'limit': limit}, CHART_TTL)
            results = []
            if data and 'recenttracks' in data:
                tracks_raw = data['recenttracks'].get('track', [])
                if isinstance(tracks_raw, dict):
                    tracks_raw = [tracks_raw]
                for t in tracks_raw[:limit]:
                    images = t.get('image', [])
                    if isinstance(images, list) and images:
                        img_url = images[-1].get('#text', '')
                    else:
                        img_url = ''
                    if isinstance(t.get('artist'), dict):
                        artist_name = t.get('artist', {}).get('#text', '')
                    else:
                        artist_name = str(t.get('artist', ''))
                    results.append({
                        'name': t.get('name', ''),
                        'artist': artist_name,
                        'url': t.get('url', ''),
                        'image': img_url,
                    })
            if callback:
                callback(results)
            return results

        if callback:
            self._executor.submit(_task)
            return []
        return _task()

    def user_get_top_artists(self, user: str, limit: int = 10, callback: Callable = None) -> List[Dict]:
        def _task():
            data = self._api_request('user.gettopartists', {'user': user, 'limit': limit}, RECOMMENDATION_TTL)
            results = []
            if data and 'topartists' in data:
                artists_raw = data['topartists'].get('artist', [])
                if isinstance(artists_raw, dict):
                    artists_raw = [artists_raw]
                for a in artists_raw[:limit]:
                    images = a.get('image', [])
                    if isinstance(images, list) and images:
                        img_url = images[-1].get('#text', '')
                    else:
                        img_url = ''
                    results.append({
                        'name': a.get('name', ''),
                        'playcount': int(a.get('playcount', 0)) if a.get('playcount') else 0,
                        'url': a.get('url', ''),
                        'image': img_url,
                    })
            if callback:
                callback(results)
            return results

        if callback:
            self._executor.submit(_task)
            return []
        return _task()