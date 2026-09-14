"""
NeDotify / AURA Music - User Taste Profile Extractor
Aggregates ALL local signals: history (play_count + completed), favorites, downloads,
playlist contents. Weights: like/download ≈ 3, completed play ≈ 2, play ≈ 1, + recency boost.
Merges with Last.fm scrobbles if username configured.
"""

import sqlite3
import logging
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

#: Hard cap on how much listening history is ever pulled into memory (privacy + cost).
HISTORY_LIMIT = 500
#: Recomputing the same profile several times per second is pure waste; reuse it briefly.
PROFILE_CACHE_TTL = 60.0

_profile_cache: Dict[int, Any] = {}
_profile_cache_lock = threading.Lock()


class UserTasteProfile:
    """User Taste Profile — aggregates all local DB signals with weights and recency boost."""

    DEFAULT_SEED_ARTISTS = ['The Weeknd', 'Dua Lipa', 'Eminem', 'Queen', 'Coldplay']

    WEIGHT_LIKE = 3.0
    WEIGHT_DOWNLOAD = 3.0
    WEIGHT_COMPLETED_PLAY = 2.0
    WEIGHT_PLAY = 1.0
    RECENCY_HALF_LIFE_DAYS = 30.0

    def __init__(self):
        self.top_artists = []
        self.top_tracks = []
        self.recent_history = []
        self.genre_distribution = {}
        self.favorite_tracks = []
        self.downloaded_tracks = []
        self.playlist_tracks = []
        self.time_of_day_habits = {
            'morning': 0,
            'afternoon': 0,
            'evening': 0,
            'night': 0,
        }
        self._artist_scores = {}
        self._genre_scores = {}

    def build_from_db(self, db: Any) -> 'UserTasteProfile':
        import traceback as _tb

        cache_key = self._cache_key(db)
        cached_state = self._cache_get(cache_key, db)
        if cached_state is not None:
            self._restore_state(cached_state)
            logger.debug('[PROFILE] Reusing profile computed less than %.0fs ago', PROFILE_CACHE_TTL)
            return self

        try:
            conn = self._get_conn(db)

            if conn is None:
                msg = '[PROFILE] No valid DB connection provided to build_from_db — profile will be empty'
                logger.warning(msg)
                print(msg, flush=True)
                return self

            cursor = conn.cursor()

            schema = self._detect_schema(cursor)
            track_cols = schema.get('tracks', set())
            has_is_downloaded = 'is_downloaded' in track_cols
            has_album = 'album' in track_cols
            has_duration = 'duration' in track_cols
            has_cover_url = 'cover_url' in track_cols
            has_cover_path = 'cover_path' in track_cols
            has_source = 'source' in track_cols
            has_source_id = 'source_id' in track_cols
            has_source_url = 'source_url' in track_cols
            has_added_at = 'added_at' in track_cols
            has_playlist_tracks = 'playlist_tracks' in schema.get('_tables', set())

            if not has_is_downloaded:
                logger.info('[PROFILE] is_downloaded column not found in tracks — skipping download signal')

            def _track_cols(prefix='t', extra=None):
                p = prefix + '.' if prefix else ''
                cols = [f'{p}id', f'{p}title', f'{p}artist']
                if has_album:
                    cols.append(f'{p}album')
                if has_duration:
                    cols.append(f'{p}duration')
                if has_cover_url:
                    cols.append(f'{p}cover_url')
                if has_cover_path:
                    cols.append(f'{p}cover_path')
                if has_source:
                    cols.append(f'{p}source')
                if has_source_id:
                    cols.append(f'{p}source_id')
                if has_source_url:
                    cols.append(f'{p}source_url')
                cols.append(f'{p}genre')
                cols.append(f'{p}is_favorite')
                if has_is_downloaded:
                    cols.append(f'{p}is_downloaded')
                cols.append(f'{p}play_count')
                if has_added_at:
                    cols.append(f'{p}added_at')
                if extra:
                    cols.extend(extra)
                return ', '.join(cols)

            try:
                h_extra = ['h.played_at', 'h.completed', 'h.duration_listened']
                cursor.execute(
                    f"""
                    SELECT {_track_cols('t', h_extra)}
                    FROM history h
                    JOIN tracks t ON h.track_id = t.id
                    ORDER BY h.played_at DESC
                    LIMIT {HISTORY_LIMIT}
                """
                )
                history_rows = cursor.fetchall()
                self.recent_history = [self._row_to_dict(r) for r in history_rows[:50]]
            except Exception as e:
                logger.warning(f'[PROFILE] History fetch error: {e}')
                history_rows = []

            try:
                cursor.execute(
                    f"""
                    SELECT {_track_cols('')}
                    FROM tracks
                    WHERE is_favorite = 1
                    {('ORDER BY added_at DESC' if has_added_at else '')}
                    LIMIT {HISTORY_LIMIT}
                """
                )
                self.favorite_tracks = [self._row_to_dict(r) for r in cursor.fetchall()]
            except Exception as e:
                logger.warning(f'[PROFILE] Favorites fetch error: {e}')
                self.favorite_tracks = []

            if has_is_downloaded:
                try:
                    dl_where = 'is_downloaded = 1'
                    if has_source:
                        dl_where += " OR source = 'local'"
                    cursor.execute(
                        f"""
                        SELECT {_track_cols('')}
                        FROM tracks
                        WHERE {dl_where}
                        {('ORDER BY added_at DESC' if has_added_at else '')}
                        LIMIT {HISTORY_LIMIT}
                    """
                    )
                    self.downloaded_tracks = [self._row_to_dict(r) for r in cursor.fetchall()]
                except Exception as e:
                    logger.warning(f'[PROFILE] Downloads fetch error: {e}')
                    self.downloaded_tracks = []
            elif has_source:
                try:
                    cursor.execute(
                        f"""
                            SELECT {_track_cols('')}
                            FROM tracks
                            WHERE source = 'local'
                            {('ORDER BY added_at DESC' if has_added_at else '')}
                            LIMIT {HISTORY_LIMIT}
                        """
                    )
                    self.downloaded_tracks = [self._row_to_dict(r) for r in cursor.fetchall()]
                except Exception as e:
                    logger.warning(f'[PROFILE] Downloads (no is_downloaded) fetch error: {e}')
                    self.downloaded_tracks = []
            else:
                self.downloaded_tracks = []

            if has_playlist_tracks:
                try:
                    cursor.execute(
                        f"""
                        SELECT {_track_cols('t')}
                        FROM playlist_tracks pt
                        JOIN tracks t ON pt.track_id = t.id
                        LIMIT {HISTORY_LIMIT}
                    """
                    )
                    self.playlist_tracks = [self._row_to_dict(r) for r in cursor.fetchall()]
                except Exception as e:
                    logger.warning(f'[PROFILE] Playlist tracks fetch error: {e}')
                    self.playlist_tracks = []
            else:
                self.playlist_tracks = []

            self._artist_scores = defaultdict(float)
            now = datetime.now()

            for row in history_rows:
                artist = self._get_artist(row)
                if not artist:
                    continue
                played_at = self._parse_dt(row['played_at'] if hasattr(row, '__getitem__') else getattr(row, 'played_at', None))
                recency = self._recency_factor(played_at, now)
                completed = row['completed'] if hasattr(row, '__getitem__') else getattr(row, 'completed', 0)
                w = self.WEIGHT_COMPLETED_PLAY if completed else self.WEIGHT_PLAY
                self._artist_scores[artist] += w * recency

            for row in self.favorite_tracks:
                artist = self._get_artist(row)
                if not artist:
                    continue
                self._artist_scores[artist] += self.WEIGHT_LIKE

            for row in self.downloaded_tracks:
                artist = self._get_artist(row)
                if not artist:
                    continue
                self._artist_scores[artist] += self.WEIGHT_DOWNLOAD

            for row in self.playlist_tracks:
                artist = self._get_artist(row)
                if not artist:
                    continue
                self._artist_scores[artist] += self.WEIGHT_PLAY

            sorted_artists = sorted(self._artist_scores.items(), key=lambda x: x[1], reverse=True)
            self.top_artists = [
                {'name': name, 'play_count': round(score, 2)}
                for name, score in sorted_artists[:20]
            ]

            self._genre_scores = defaultdict(float)

            def _add_genre(row, weight=1.0):
                genre = row.get('genre') if isinstance(row, dict) else getattr(row, 'genre', None)
                if genre and genre.strip():
                    self._genre_scores[genre.strip()] += weight

            for row in history_rows:
                completed = row['completed'] if hasattr(row, '__getitem__') else getattr(row, 'completed', 0)
                _add_genre(row, self.WEIGHT_COMPLETED_PLAY if completed else self.WEIGHT_PLAY)

            for row in self.favorite_tracks:
                _add_genre(row, self.WEIGHT_LIKE)

            for row in self.downloaded_tracks:
                _add_genre(row, self.WEIGHT_DOWNLOAD)

            for row in self.playlist_tracks:
                _add_genre(row, self.WEIGHT_PLAY)

            total_genre = sum(self._genre_scores.values()) or 1
            self.genre_distribution = {
                g: round(s / total_genre, 3)
                for g, s in sorted(self._genre_scores.items(), key=lambda x: x[1], reverse=True)
            }

            try:
                if has_is_downloaded:
                    score_expr = '(t.play_count * 1 + t.is_favorite * 3 + t.is_downloaded * 3)'
                else:
                    score_expr = '(t.play_count * 1 + t.is_favorite * 3)'
                cursor.execute(
                    f"""
                    SELECT {_track_cols('t')}, {score_expr} as weighted_score
                    FROM tracks t
                    WHERE t.artist IS NOT NULL AND t.artist != '' AND t.artist != 'Unknown Artist'
                    ORDER BY weighted_score DESC, t.play_count DESC
                    LIMIT 20
                """
                )
                self.top_tracks = [self._row_to_dict(r) for r in cursor.fetchall()]
            except Exception as e:
                logger.warning(f'[PROFILE] Top tracks fetch error: {e}')
                self.top_tracks = []

            try:
                cursor.execute(
                    'SELECT played_at FROM history WHERE played_at IS NOT NULL '
                    'ORDER BY played_at DESC LIMIT ?',
                    (HISTORY_LIMIT,),
                )
                habits = {'morning': 0, 'afternoon': 0, 'evening': 0, 'night': 0}
                for row in cursor.fetchall():
                    slot = self._parse_time_slot(row[0])
                    if slot in habits:
                        habits[slot] += 1
                self.time_of_day_habits = habits
            except Exception as e:
                logger.warning(f'[PROFILE] Time habits error: {e}')

            self._log_profile_summary()
            self._cache_put(cache_key, db)

        except Exception as e:
            err_msg = f'[PROFILE_ERROR] Fatal error in build_from_db: {e}\n{_tb.format_exc()}'
            logger.error(err_msg)
            print(err_msg, flush=True)

        return self

    # ─── 60s profile memoisation (identical profiles were recomputed per section) ───

    _CACHE_MAX_ENTRIES = 4

    _STATE_FIELDS = (
        'top_artists', 'top_tracks', 'recent_history', 'genre_distribution',
        'favorite_tracks', 'downloaded_tracks', 'playlist_tracks',
        'time_of_day_habits', '_artist_scores', '_genre_scores',
    )

    @staticmethod
    def _cache_key(db: Any) -> Any:
        """Identity of the data source. Paths are stable; live objects are keyed by
        identity and pinned in the cache entry so an id can never be recycled."""
        if isinstance(db, str):
            return f'path:{db}'
        return id(db)

    @classmethod
    def _cache_get(cls, cache_key: Any, db: Any) -> Optional[Dict[str, Any]]:
        now = time.time()
        with _profile_cache_lock:
            for key, entry in list(_profile_cache.items()):
                if now - entry['ts'] > PROFILE_CACHE_TTL:
                    _profile_cache.pop(key, None)
            entry = _profile_cache.get(cache_key)
            if entry is None:
                return None
            if not isinstance(cache_key, str) and entry['db'] is not db:
                return None
            return entry['state']

    def _cache_put(self, cache_key: Any, db: Any) -> None:
        state = {f: getattr(self, f) for f in self._STATE_FIELDS}
        with _profile_cache_lock:
            _profile_cache[cache_key] = {'ts': time.time(), 'db': db, 'state': state}
            while len(_profile_cache) > self._CACHE_MAX_ENTRIES:
                _profile_cache.pop(next(iter(_profile_cache)), None)

    def _restore_state(self, state: Dict[str, Any]) -> None:
        for field in self._STATE_FIELDS:
            value = state.get(field)
            if isinstance(value, list):
                setattr(self, field, list(value))
            elif isinstance(value, dict):
                setattr(self, field, dict(value))
            else:
                setattr(self, field, value)

    def _detect_schema(self, cursor) -> dict:
        schema = {'_tables': set()}
        try:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cursor.fetchall()]
            schema['_tables'] = set(tables)
            for table in tables:
                try:
                    cursor.execute(f'PRAGMA table_info({table})')
                    cols = {r[1] for r in cursor.fetchall()}
                    schema[table] = cols
                except Exception as e:
                    logger.debug(f'[PROFILE] Could not read columns of {table}: {e}', exc_info=True)
                    schema[table] = set()
        except Exception as e:
            logger.warning(f'[PROFILE] Schema detection error: {e}')
        return schema

    def _log_profile_summary(self):
        top10_artists = [a['name'] for a in self.top_artists[:10]]
        top5_genres = list(self.genre_distribution.keys())[:5]

        # Artist/genre names are the user's listening history: DEBUG only, never INFO,
        # so they do not end up in the shipped log file.
        if top10_artists:
            logger.debug('[PROFILE] Top artists: %s', ', '.join(str(a) for a in top10_artists))
        else:
            logger.debug('[PROFILE] No artists found — profile is empty')

        if top5_genres:
            logger.debug('[PROFILE] Top genres: %s', ', '.join(str(g) for g in top5_genres))

        # Counts only — safe to surface for terminal visibility.
        smsg = (
            f'[PROFILE] Signals — history:{len(self.recent_history)}, favorites:{len(self.favorite_tracks)}, downloads:{len(self.downloaded_tracks)}, playlist_tracks:{len(self.playlist_tracks)}'
        )
        logger.debug(smsg)
        print(smsg, flush=True)

    def is_empty(self) -> bool:
        return (
            not self.top_artists
            and not self.favorite_tracks
            and not self.downloaded_tracks
            and not self.playlist_tracks
        )

    def get_seed_artists(self, limit: int = 5) -> List[str]:
        seeds = [a['name'] for a in self.top_artists if a.get('name')][:limit]
        if seeds:
            return seeds
        seen = set()
        artists = []
        for src in (self.favorite_tracks, self.downloaded_tracks, self.playlist_tracks, self.recent_history):
            for trk in src:
                a = trk.get('artist') if isinstance(trk, dict) else getattr(trk, 'artist', None)
                if not a:
                    continue
                if a == 'Unknown Artist':
                    continue
                if a in seen:
                    continue
                seen.add(a)
                artists.append(a)
                if len(artists) >= limit:
                    return artists
        if artists:
            return artists
        logger.info('[FALLBACK] Profile empty — using DEFAULT_SEED_ARTISTS')
        return self.DEFAULT_SEED_ARTISTS[:limit]

    def get_local_liked_and_downloaded_tracks(self, limit: int = 20) -> List[Dict[str, Any]]:
        seen = set()
        result = []
        for trk in self.favorite_tracks + self.downloaded_tracks:
            key = f"{(trk.get('artist') or '').lower()}:{(trk.get('title') or '').lower()}"
            if key not in seen:
                seen.add(key)
                result.append(trk)
                if len(result) >= limit:
                    break
        return result

    def get_seed_tracks(self, limit: int = 5) -> List[Dict[str, Any]]:
        if self.top_tracks:
            return self.top_tracks[:limit]
        if self.favorite_tracks:
            return self.favorite_tracks[:limit]
        if self.recent_history:
            return self.recent_history[:limit]
        return []

    def get_time_of_day_vibe(self) -> str:
        hour = datetime.now().hour
        if 5 <= hour < 12:
            return 'morning'
        if 12 <= hour < 18:
            return 'afternoon'
        if 18 <= hour < 23:
            return 'evening'
        return 'night'

    def to_dict(self) -> Dict[str, Any]:
        return {
            'top_artists': self.top_artists,
            'top_tracks': self.top_tracks,
            'recent_history': self.recent_history,
            'genre_distribution': self.genre_distribution,
            'favorite_tracks': self.favorite_tracks,
            'downloaded_tracks': self.downloaded_tracks,
            'time_of_day_habits': self.time_of_day_habits,
            'current_vibe': self.get_time_of_day_vibe(),
            'seed_artists': self.get_seed_artists(),
            'is_empty': self.is_empty(),
        }

    @staticmethod
    def _get_conn(db):
        if hasattr(db, 'conn'):
            return db.conn
        if hasattr(db, 'cursor'):
            return db
        if isinstance(db, str):
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            return conn
        return None

    @staticmethod
    def _get_artist(row) -> Optional[str]:
        artist = row.get('artist') if isinstance(row, dict) else getattr(row, 'artist', None)
        if not artist or artist in ('Unknown Artist', '', None):
            return None
        return artist.strip()

    @staticmethod
    def _recency_factor(played_at: Optional[datetime], now: datetime, half_life_days: float = 30.0) -> float:
        if played_at is None:
            return 0.5
        delta_days = max(0, (now - played_at).total_seconds() / 86400.0)
        return 2.0 ** (-delta_days / half_life_days)

    @staticmethod
    def _parse_dt(ts_val) -> Optional[datetime]:
        if isinstance(ts_val, datetime):
            return ts_val
        if isinstance(ts_val, str):
            try:
                return datetime.fromisoformat(ts_val.replace('Z', '+00:00'))
            except Exception:
                try:
                    return datetime.strptime(ts_val.split('.')[0], '%Y-%m-%d %H:%M:%S')
                except Exception:
                    return None
        return None

    @staticmethod
    def _row_to_dict(row: Any) -> Dict[str, Any]:
        if hasattr(row, 'keys'):
            return dict(row)
        if isinstance(row, (tuple, list)):
            keys = ['id', 'title', 'artist', 'album', 'duration', 'cover_url', 'cover_path', 'source', 'source_id', 'source_url', 'genre', 'is_favorite', 'is_downloaded', 'play_count']
            return {keys[i]: row[i] for i in range(min(len(keys), len(row)))}
        return {}

    @staticmethod
    def _parse_time_slot(ts_val: Any) -> str:
        hour = None
        if isinstance(ts_val, datetime):
            hour = ts_val.hour
        elif isinstance(ts_val, str):
            try:
                dt = datetime.fromisoformat(ts_val.replace('Z', '+00:00'))
                hour = dt.hour
            except Exception:
                try:
                    dt = datetime.strptime(ts_val.split('.')[0], '%Y-%m-%d %H:%M:%S')
                    hour = dt.hour
                except Exception as e:
                    logger.debug(f'[PROFILE] Unparseable played_at timestamp {ts_val!r}: {e}')
        if hour is None:
            return 'afternoon'
        if 5 <= hour < 12:
            return 'morning'
        if 12 <= hour < 18:
            return 'afternoon'
        if 18 <= hour < 23:
            return 'evening'
        return 'night'