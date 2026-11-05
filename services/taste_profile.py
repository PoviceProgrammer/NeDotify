"""
NeDotify - User Taste Profile Extractor
Aggregates ALL local signals: history (play_count + completed), favorites, downloads,
playlist contents. Weights: like/download ≈ 3, completed play ≈ 2, play ≈ 1, + recency boost.
Merges with Last.fm scrobbles if username configured.
"""

import sqlite3
import logging
import threading
import time
import copy
import os
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from services.artist_identity import artist_aliases, canonical_artist, track_key as identity_track_key
from services.music_matching import title_metadata

logger = logging.getLogger(__name__)

#: Hard cap on how much listening history is ever pulled into memory (privacy + cost).
HISTORY_LIMIT = 1500
#: Recomputing the same profile several times per second is pure waste; reuse it briefly.
PROFILE_CACHE_TTL = 60.0

_profile_cache: Dict[int, Any] = {}
_profile_cache_lock = threading.Lock()


def recommendation_track_key(track, aliases):
    """Explicit musical credits match across uploads; versions remain distinct."""
    original = identity_track_key(track, aliases)
    if original[0].startswith('@catalog:'):
        return original
    metadata = title_metadata(track.get('title'), track.get('artist'))
    if metadata['embedded']:
        artist, title = metadata['embedded']
        metadata = title_metadata(title, artist)
    else:
        artist = track.get('artist') or ''
    return identity_track_key(dict(track, artist=artist, title=metadata['title']), aliases)


class UserTasteProfile:
    """User Taste Profile — aggregates all local DB signals with weights and recency boost."""

    DEFAULT_SEED_ARTISTS = ['The Weeknd', 'Dua Lipa', 'Eminem', 'Queen', 'Coldplay']

    WEIGHT_LIKE = 3.0
    WEIGHT_DOWNLOAD = 3.0
    WEIGHT_COMPLETED_PLAY = 2.0
    WEIGHT_PLAY = 1.0
    RECENCY_HALF_LIFE_DAYS = 30.0

    def __init__(self, settings=None):
        self.settings = settings
        self.artist_aliases = artist_aliases(settings)
        self.top_artists = []
        self.top_tracks = []
        self.recent_history = []
        self.genre_distribution = {}
        self.favorite_tracks = []
        self.downloaded_tracks = []
        self.playlist_tracks = []
        self.known_content_keys = set()
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

        self.artist_aliases = artist_aliases(self.settings)
        cache_key = (self._cache_key(db), tuple(sorted(self.artist_aliases.items())))
        owned_connection = isinstance(db, str)
        conn = None
        try:
            conn = self._get_conn(db)

            if conn is None:
                msg = '[PROFILE] No valid DB connection provided to build_from_db — profile will be empty'
                logger.warning(msg)
                print(msg, flush=True)
                return self

            revision = getattr(db, 'data_revision', None)
            path = getattr(db, 'db_path', db if isinstance(db, str) else None)
            if path and path != ':memory:':
                stamps = []
                for candidate in (path, path + '-wal'):
                    try:
                        stat = os.stat(candidate)
                        stamps.append((stat.st_mtime_ns, stat.st_size))
                    except OSError:
                        stamps.append(None)
                revision = (revision, tuple(stamps))
            if revision is None:
                revision = self._connection_revision(conn)
            self._source_revision = (cache_key, revision)
            cached_state = self._cache_get(cache_key, db, revision)
            if cached_state is not None:
                self._restore_state(cached_state)
                logger.debug('[PROFILE] Reusing unchanged profile computed less than %.0fs ago', PROFILE_CACHE_TTL)
                return self

            # Reusing a profile object after its source changes must not retain
            # fields from a previous build or a failed query.
            UserTasteProfile.__init__(self, self.settings)
            self._source_revision = (cache_key, revision)
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
            history_cols = schema.get('history', set())

            def _fetch_dicts():
                names = [col[0] for col in cursor.description]
                return [dict(zip(names, row)) for row in cursor.fetchall()]

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
                for name, default in (('genre', "''"), ('is_favorite', '0'), ('play_count', '0')):
                    cols.append(f'{p}{name}' if name in track_cols else f'{default} AS {name}')
                if has_is_downloaded:
                    cols.append(f'{p}is_downloaded')
                if 'file_path' in track_cols:
                    cols.append(f'{p}file_path')
                if has_added_at:
                    cols.append(f'{p}added_at')
                if extra:
                    cols.extend(extra)
                return ', '.join(cols)

            try:
                h_extra = [
                    f'h.{name}' if name in history_cols else f'{default} AS {name}'
                    for name, default in (('played_at', 'NULL'), ('completed', '0'), ('duration_listened', 'NULL'), ('listening_measured', '0'), ('media_listened', '0'), ('session_finished', '0'))
                ]
                cursor.execute(
                    f"""
                    SELECT {_track_cols('t', h_extra)}
                    FROM history h
                    JOIN tracks t ON h.track_id = t.id
                    ORDER BY h.played_at DESC
                    LIMIT {HISTORY_LIMIT}
                """
                )
                history_rows = _fetch_dicts()
                get_history = getattr(db, 'get_history', None)
                if callable(get_history):
                    # The public recent feed is one row per track and carries
                    # the same event metrics as the home screen. Keep the raw
                    # bounded rows above for weighted taste scoring below.
                    try:
                        feed_rows = get_history(limit=50)
                        self.recent_history = []
                        for row in (feed_rows or []):
                            if not isinstance(row, dict):
                                continue
                            item = dict(row)
                            track_id = item.get('track_id', item.get('id'))
                            if track_id is not None:
                                item.setdefault('id', track_id)
                                item.setdefault('track_id', track_id)
                            self.recent_history.append(item)
                            if len(self.recent_history) == 50:
                                break
                    except Exception as e:
                        logger.warning(f'[PROFILE] Canonical history feed error: {e}')
                        self.recent_history = self._recent_history_fallback(history_rows)
                else:
                    self.recent_history = self._recent_history_fallback(history_rows)
            except Exception as e:
                logger.warning(f'[PROFILE] History fetch error: {e}')
                history_rows = []
                self.recent_history = []

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
                self.favorite_tracks = _fetch_dicts()
            except Exception as e:
                logger.warning(f'[PROFILE] Favorites fetch error: {e}')
                self.favorite_tracks = []

            if has_is_downloaded:
                try:
                    dl_where = 'is_downloaded = 1'
                    cursor.execute(
                        f"""
                        SELECT {_track_cols('')}
                        FROM tracks
                        WHERE {dl_where}
                        {('ORDER BY added_at DESC' if has_added_at else '')}
                        LIMIT {HISTORY_LIMIT}
                    """
                    )
                    self.downloaded_tracks = _fetch_dicts()
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
                    self.downloaded_tracks = _fetch_dicts()
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
                    self.playlist_tracks = _fetch_dicts()
                except Exception as e:
                    logger.warning(f'[PROFILE] Playlist tracks fetch error: {e}')
                    self.playlist_tracks = []
            else:
                self.playlist_tracks = []

            # Exclusion identity is complete even when taste payloads/history
            # are bounded. Stream only lightweight columns, never artwork or
            # full library objects, and cache against the same DB revision.
            identity_columns = [name for name in ('id', 'title', 'artist', 'source', 'source_id') if name in track_cols]
            try:
                cursor.execute('SELECT ' + ','.join(identity_columns) + ' FROM tracks')
                while rows := cursor.fetchmany(256):
                    for row in rows:
                        item = dict(zip(identity_columns, row))
                        self.known_content_keys.add(recommendation_track_key(item, self.artist_aliases))
            except Exception as exc:
                logger.warning('Known recommendation identities unavailable: %s', exc)

            self._artist_scores = defaultdict(float)
            now = datetime.now()
            artist_names = {}
            track_scores = defaultdict(float)
            signal_tracks = {}

            def _add_signal(row, weight):
                artist = self._get_artist(row)
                if not artist or weight <= 0:
                    return
                artist_key = identity_track_key(dict(row), self.artist_aliases)[0]
                artist_names.setdefault(artist_key, artist)
                self._artist_scores[artist_key] += weight
                track_key = str(self._field(row, 'id') or '') or (
                    f"{artist_key}:{self._name_key(self._field(row, 'title', ''))}"
                )
                track_scores[track_key] += weight
                signal_tracks.setdefault(track_key, dict(row))

            for row in history_rows:
                artist = self._get_artist(row)
                if not artist:
                    continue
                played_at = self._parse_dt(self._field(row, 'played_at'))
                recency = self._recency_factor(played_at, now)
                _add_signal(row, self._listening_weight(row) * recency)

            for row in self.favorite_tracks:
                artist = self._get_artist(row)
                if not artist:
                    continue
                _add_signal(row, self.WEIGHT_LIKE)

            for row in self.downloaded_tracks:
                artist = self._get_artist(row)
                if not artist:
                    continue
                _add_signal(row, self.WEIGHT_DOWNLOAD)

            for row in self.playlist_tracks:
                artist = self._get_artist(row)
                if not artist:
                    continue
                _add_signal(row, self.WEIGHT_PLAY)

            sorted_artists = sorted(self._artist_scores.items(), key=lambda x: x[1], reverse=True)
            self.top_artists = [
                dict({'name': artist_names.get(key, key), 'play_count': round(score, 2)}, **({'identity_key': key} if key.startswith('@catalog:') else {}))
                for key, score in sorted_artists[:20]
            ]

            self._genre_scores = defaultdict(float)

            def _add_genre(row, weight=1.0):
                genre = self._field(row, 'genre')
                if genre and genre.strip():
                    self._genre_scores[genre.strip()] += weight

            for row in history_rows:
                played_at = self._parse_dt(self._field(row, 'played_at'))
                _add_genre(row, self._listening_weight(row) * self._recency_factor(played_at, now))

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

            # An imported but never played/liked track is not a taste signal.
            # Use the same recency/listening weights as artist ranking instead
            # of ordering all library rows (including zero-score imports).
            self.top_tracks = []
            for key, score in sorted(track_scores.items(), key=lambda item: item[1], reverse=True)[:20]:
                track = dict(signal_tracks[key])
                track['weighted_score'] = round(score, 3)
                self.top_tracks.append(track)

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
            self._cache_put(cache_key, db, revision)

        except Exception as e:
            err_msg = f'[PROFILE_ERROR] Fatal error in build_from_db: {e}\n{_tb.format_exc()}'
            logger.error(err_msg)
            print(err_msg, flush=True)

        finally:
            if owned_connection and conn is not None:
                conn.close()

        return self

    # ─── 60s profile memoisation (identical profiles were recomputed per section) ───

    _CACHE_MAX_ENTRIES = 4

    @staticmethod
    def _recent_history_fallback(rows):
        """Deduplicate raw history rows for connection-only/legacy DB callers.

        Rows arrive newest first. Preserve the newest event's fields and add
        the recent-window event count and summed listened duration expected by
        consumers of the canonical database history feed.
        """
        unique = {}
        for raw in rows:
            row = dict(raw)
            track_id = row.get('track_id', row.get('id'))
            if track_id is None:
                continue
            key = str(track_id)
            listened = max(0, row.get('duration_listened') or 0)
            row['id'] = track_id
            row['track_id'] = track_id
            if key not in unique:
                row['play_count'] = 0
                row['duration_listened'] = 0
                row['latest_duration_listened'] = listened
                unique[key] = row
            current = unique[key]
            current['play_count'] += 1
            current['duration_listened'] += listened
        return list(unique.values())[:50]

    _STATE_FIELDS = (
        'top_artists', 'top_tracks', 'recent_history', 'genre_distribution',
        'favorite_tracks', 'downloaded_tracks', 'playlist_tracks', 'known_content_keys',
        'time_of_day_habits', '_artist_scores', '_genre_scores',
    )

    @staticmethod
    def _cache_key(db: Any) -> Any:
        """Identity of the data source. Paths are stable; live objects are keyed by
        identity and pinned in the cache entry so an id can never be recycled."""
        if isinstance(db, str):
            return f'path:{db}'
        return id(db)

    @staticmethod
    def _connection_revision(conn) -> Any:
        """Detect writes on this connection and commits from other threads.

        data_version is relative to a connection, so its identity is part of
        the revision. A new connection rebuilds once rather than accidentally
        reusing a coincidentally equal version from a different connection.
        """
        try:
            data_version = conn.execute('PRAGMA data_version').fetchone()[0]
            schema_version = conn.execute('PRAGMA schema_version').fetchone()[0]
            return (conn.total_changes, data_version, schema_version)
        except (AttributeError, sqlite3.Error, TypeError):
            # If a connection cannot expose a revision, never reuse stale data.
            return object()

    @classmethod
    def _cache_get(cls, cache_key: Any, db: Any, revision: Any = None) -> Optional[Dict[str, Any]]:
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
            if entry.get('revision') != revision:
                return None
            return copy.deepcopy(entry['state'])

    def _cache_put(self, cache_key: Any, db: Any, revision: Any = None) -> None:
        state = copy.deepcopy({f: getattr(self, f) for f in self._STATE_FIELDS})
        with _profile_cache_lock:
            _profile_cache[cache_key] = {'ts': time.time(), 'db': db, 'revision': revision, 'state': state}
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
                a = self._field(trk, 'artist')
                if not a:
                    continue
                if self._name_key(a) in ('unknown artist', 'unknown'):
                    continue
                artist_key = self._name_key(a)
                if artist_key in seen:
                    continue
                seen.add(artist_key)
                artists.append(' '.join(str(a).split()))
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
    def _field(row, name: str, default=None):
        """Read a column from a dict or sqlite3.Row (Row has no attribute access)."""
        if isinstance(row, dict):
            return row.get(name, default)
        try:
            return row[name]
        except (IndexError, KeyError, TypeError):
            return default

    @classmethod
    def _get_artist(cls, row) -> Optional[str]:
        artist = cls._field(row, 'artist')
        if not artist or cls._name_key(artist) in ('unknown artist', 'unknown', 'none', 'null'):
            return None
        return ' '.join(str(artist).split())

    @staticmethod
    def _name_key(value: Any) -> str:
        return ' '.join(unicodedata.normalize('NFKC', str(value or '')).split()).casefold()

    @classmethod
    def _listening_weight(cls, row) -> float:
        if cls._field(row, 'completed', 0):
            return cls.WEIGHT_COMPLETED_PLAY
        try:
            listened = float(cls._field(row, 'duration_listened') or 0)
            duration = float(cls._field(row, 'duration') or 0)
        except (TypeError, ValueError):
            return cls.WEIGHT_PLAY
        if cls._field(row, 'listening_measured', 0) and listened <= 0:
            return 0.0
        if cls._field(row, 'listening_measured', 0) and not cls._field(row, 'session_finished', 0):
            return cls.WEIGHT_PLAY
        # Unknown/legacy duration values do not prove a skip. Positive measured
        # short listens do; repeated one-second auditions must not outweigh a
        # fully played or explicitly liked track.
        if listened > 0 and duration > 0:
            media_listened = cls._field(row, 'media_listened', 0)
            fraction = (float(media_listened) if media_listened else listened) / duration
            if listened < 10 and fraction < 0.1:
                return cls.WEIGHT_PLAY * 0.1
        return cls.WEIGHT_PLAY

    @staticmethod
    def _recency_factor(played_at: Optional[datetime], now: datetime, half_life_days: float = 30.0) -> float:
        if played_at is None:
            return 0.5
        # timestamp() handles both local SQLite timestamps and imported ISO UTC
        # values without subtracting aware and naive datetime objects.
        delta_days = max(0, (now.timestamp() - played_at.timestamp()) / 86400.0)
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
