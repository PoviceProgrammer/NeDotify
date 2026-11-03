"""
NeDotify - Recommendation Service
Uses local taste signals, YouTube/SoundCloud related metadata and optional
Last.fm discovery to generate playable personalized feeds, mixes and radio.
"""

import os
import time
import math
import logging
import datetime
import re
import unicodedata
import hashlib
from typing import Callable, Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, Future, wait, TimeoutError

from services.base_service import BaseMusicService
from services.lastfm_service import LastFMService
from services.taste_profile import UserTasteProfile, recommendation_track_key
from services.track_resolver import TrackResolver
from services.artist_identity import artist_aliases, canonical_artist, track_key

logger = logging.getLogger(__name__)

CURATED_WELCOME_TRACKS = [
    {"id": "yt_4NRXx6U8ABQ", "title": "Blinding Lights", "artist": "The Weeknd", "source": "youtube", "source_id": "4NRXx6U8ABQ", "duration": 200, "cover_url": "https://i.ytimg.com/vi/4NRXx6U8ABQ/hqdefault.jpg"},
    {"id": "yt_TUVcZfQe-Kw", "title": "Levitating", "artist": "Dua Lipa", "source": "youtube", "source_id": "TUVcZfQe-Kw", "duration": 203, "cover_url": "https://i.ytimg.com/vi/TUVcZfQe-Kw/hqdefault.jpg"},
    {"id": "yt_uelHwf8o7_U", "title": "Love The Way You Lie", "artist": "Eminem ft. Rihanna", "source": "youtube", "source_id": "uelHwf8o7_U", "duration": 263, "cover_url": "https://i.ytimg.com/vi/uelHwf8o7_U/hqdefault.jpg"},
    {"id": "yt_fJ9rUzIMcZQ", "title": "Bohemian Rhapsody", "artist": "Queen", "source": "youtube", "source_id": "fJ9rUzIMcZQ", "duration": 359, "cover_url": "https://i.ytimg.com/vi/fJ9rUzIMcZQ/hqdefault.jpg"},
    {"id": "yt_YykjpeuMNEk", "title": "Hymn for the Weekend", "artist": "Coldplay", "source": "youtube", "source_id": "YykjpeuMNEk", "duration": 258, "cover_url": "https://i.ytimg.com/vi/YykjpeuMNEk/hqdefault.jpg"},
    {"id": "yt_JGwWNGJdvx8", "title": "Shape of You", "artist": "Ed Sheeran", "source": "youtube", "source_id": "JGwWNGJdvx8", "duration": 233, "cover_url": "https://i.ytimg.com/vi/JGwWNGJdvx8/hqdefault.jpg"},
    {"id": "yt_7wtfhZwyrcc", "title": "Believer", "artist": "Imagine Dragons", "source": "youtube", "source_id": "7wtfhZwyrcc", "duration": 204, "cover_url": "https://i.ytimg.com/vi/7wtfhZwyrcc/hqdefault.jpg"},
    {"id": "yt_DyDfgMOUjCI", "title": "bad guy", "artist": "Billie Eilish", "source": "youtube", "source_id": "DyDfgMOUjCI", "duration": 194, "cover_url": "https://i.ytimg.com/vi/DyDfgMOUjCI/hqdefault.jpg"},
]


class RecommendationService(BaseMusicService):
    """Generates personalized discovery without requiring a Last.fm API key."""

    DEFAULT_FALLBACK_ARTISTS = ['The Weeknd', 'Dua Lipa', 'Eminem', 'Queen', 'Coldplay']

    def __init__(self, settings=None, db=None, soundcloud_service=None, youtube_service=None):
        super().__init__()
        self.settings = settings
        self.db = db
        self.logger = logging.getLogger(self.__class__.__name__)

        self.soundcloud_service = soundcloud_service
        self.sc_service = soundcloud_service
        self.youtube_service = youtube_service

        self.lastfm = LastFMService(settings=settings)
        # settings= matters: without it the resolver's fallback path builds
        # providers that ignore the configured proxy and cookies file.
        self.resolver = TrackResolver(db=db, settings=settings, soundcloud_service=soundcloud_service, youtube_service=youtube_service)
        # Imported/local catalogue rows are taste seeds, not native radio IDs.
        # Excluding the DB here prevents resolving straight back to that row.
        self._radio_seed_resolver = TrackResolver(db=None, settings=settings,
            soundcloud_service=soundcloud_service, youtube_service=youtube_service)
        self._candidate_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='RecommendationMetadata')
        self._candidate_flights = {}
        self._discovery = None

    @property
    def available(self) -> bool:
        return True

    def reset_service(self):
        with self._cache_lock:
            for key in list(self._search_cache):
                if key.startswith('recommendation:'):
                    self._search_cache.pop(key, None)

    def _prefetch_resolutions(self, pairs: List[Any], limit: int = 20) -> None:
        """Resolve up to `limit` (title, artist) candidates in parallel before the
        sequential loop consumes them, so a section costs ~one timeout, not N."""
        prefetch = getattr(self.resolver, 'prefetch', None)
        if not callable(prefetch) or not pairs:
            return
        cleaned = [(p[0] or '', p[1] or '') for p in pairs if p and (p[0] or p[1])]
        if not cleaned:
            return
        try:
            prefetch(cleaned[:max(8, limit)])
        except Exception as e:
            self.logger.debug(f'Resolution prefetch skipped: {e}', exc_info=True)

    def _format_ui_track(self, track: Dict[str, Any]) -> Dict[str, Any]:
        if hasattr(track, 'keys') and not isinstance(track, dict):
            track = dict(track)
        if not isinstance(track, dict):
            return {}
        try:
            duration = float(track.get('duration') or 0)
            duration = max(0.0, duration) if math.isfinite(duration) else 0.0
        except (ValueError, TypeError):
            duration = 0.0
        return {
            'id': track.get('id'),
            'title': track.get('title') or 'Unknown Title',
            'artist': track.get('artist') or 'Unknown Artist',
            'cover_url': track.get('cover_url') or track.get('cover_path') or '',
            'source': track.get('source') or 'unknown',
            'source_id': str(track.get('source_id') or track.get('id') or ''),
            'source_url': track.get('source_url') or '',
            'file_path': track.get('file_path') or '',
            'duration': duration,
            'genre': track.get('genre') or '',
            'recommendation_relevance': self._bounded_score(track.get('recommendation_relevance')),
            'recommendation_source': track.get('recommendation_source') or '',
            'recommendation_origin': track.get('recommendation_origin') or '',
            'recommendation_seed_artists': list(track.get('recommendation_seed_artists') or []),
            'is_favorite': bool(track.get('is_favorite', False)),
            'is_downloaded': bool(track.get('is_downloaded', False)),
        }

    def _get_time_of_day_context(self) -> Dict[str, str]:
        hour = datetime.datetime.now().hour
        if 5 <= hour < 12:
            return {
                'greeting': 'Доброе утро',
                'title': 'Утренний вайб',
                'vibe_key': 'morning',
                'genres': ['Acoustic', 'Indie', 'Chill', 'Pop'],
            }
        if 12 <= hour < 18:
            return {
                'greeting': 'Добрый день',
                'title': 'Дневной фокус',
                'vibe_key': 'afternoon',
                'genres': ['Focus', 'Electronic', 'Pop', 'Rock'],
            }
        if 18 <= hour < 23:
            return {
                'greeting': 'Добрый вечер',
                'title': 'Вечерний релакс',
                'vibe_key': 'evening',
                'genres': ['Lo-Fi', 'Soul', 'R&B', 'Chill'],
            }
        return {
            'greeting': 'Доброй ночи',
            'title': 'Ночной вайб',
            'vibe_key': 'night',
            'genres': ['Ambient', 'Lo-Fi', 'Synthwave', 'Deep House'],
        }

    @staticmethod
    def _text_key(value):
        return ' '.join(unicodedata.normalize('NFKC', str(value or '')).casefold().split())

    def _artist_key(self, value):
        aliases = artist_aliases(self.settings)
        return track_key(value, aliases)[0] if isinstance(value, dict) else canonical_artist(value, aliases)

    def _feedback(self):
        artists = self.settings.get('personalization', 'blocked_artists', []) if self.settings else []
        tracks = self.settings.get('personalization', 'disliked_tracks', []) if self.settings else []
        return ({self._artist_key(a) for a in artists if isinstance(a, str)} if isinstance(artists, list) else set(),
                {self._content_key(t) for t in tracks if isinstance(t, dict)} if isinstance(tracks, list) else set())

    def _content_key(self, track):
        return recommendation_track_key(track, artist_aliases(self.settings))

    def _known_content_keys(self, profile):
        return ({self._content_key(t) for t in self._known_tracks(profile)}
                | set(getattr(profile, 'known_content_keys', ())))

    def _provider_enabled(self, source):
        if source == 'deezer':
            return ((not self.settings or self.settings.get('services', 'deezer_enabled', True) is not False)
                    and any(self._provider_enabled(provider) for provider in ('youtube', 'soundcloud')))
        if source not in ('youtube', 'soundcloud'):
            return True
        return not self.settings or self.settings.get('services', source + '_enabled', True) is not False

    def _playable(self, track):
        if not isinstance(track, dict):
            return False
        if track.get('file_path'):
            return True
        source = track.get('source')
        if not self._provider_enabled(source):
            return False
        sid = str(track.get('source_id') or '')
        if source == 'local':
            return bool(track.get('id')) and not sid.startswith('fallback_')
        return source in ('youtube', 'soundcloud', 'spotify', 'yandex', 'deezer') and bool(sid or track.get('source_url'))

    def _profile(self, history=None):
        profile = UserTasteProfile(settings=self.settings).build_from_db(self.db) if self.db else UserTasteProfile(settings=self.settings)
        if history:
            merged, seen = [], set()
            measured = {}
            for entry in profile.recent_history:
                measured.setdefault(self._content_key(entry), entry)
            for track in list(history) + profile.recent_history:
                if not isinstance(track, dict) or not track.get('title'):
                    continue
                key = self._content_key(track)
                if key not in seen:
                    seen.add(key)
                    item = dict(track)
                    for field in ('completed', 'duration_listened', 'listening_measured', 'media_listened', 'session_finished'):
                        if field not in item and key in measured and field in measured[key]:
                            item[field] = measured[key][field]
                    merged.append(item)
            profile.recent_history = merged[:50]
        return profile

    def _known_tracks(self, profile):
        return (profile.recent_history + profile.favorite_tracks + profile.downloaded_tracks
                + profile.playlist_tracks + profile.top_tracks)

    def _seed_tracks(self, profile, limit=5):
        seeds, artists, seen = [], set(), set()
        blocked, disliked = self._feedback()
        pool = profile.get_seed_tracks(limit=20) + profile.recent_history + profile.favorite_tracks
        for track in pool:
            key = self._content_key(track)
            artist = key[0]
            if key in seen or key in disliked or artist in blocked or (artist and artist in artists):
                continue
            if not self._playable(track):
                continue
            seen.add(key)
            artists.add(artist)
            seeds.append(track)
            if len(seeds) >= limit:
                break
        return seeds

    def _calculate_taste_weights(self, candidate, taste_profile):
        artist = self._artist_key(candidate)
        scores = {(a.get('identity_key') or self._artist_key(a.get('name'))): max(0, float(a.get('play_count') or 0))
                  for a in taste_profile.top_artists}
        maximum = max(scores.values(), default=0)
        affinity = math.log1p(scores.get(artist, 0)) / math.log1p(maximum) if maximum else 0
        recent = max((1 - i / 20 for i, t in enumerate(taste_profile.recent_history[:20])
                      if self._artist_key(t) == artist), default=0)
        favorite = any(self._artist_key(t) == artist for t in taste_profile.favorite_tracks)
        relevance = self._bounded_score(candidate.get('recommendation_relevance'))
        preferred = {self._text_key(g): self._bounded_score(weight) for g, weight in taste_profile.genre_distribution.items()}
        configured = self.settings.get('personalization', 'favorite_genres', []) if self.settings else []
        if isinstance(configured, list):
            preferred.update({self._text_key(g): 1 for g in configured if isinstance(g, str)})
        genres = {self._text_key(g) for g in re.split(r'[,;/]', str(candidate.get('genre') or '')) if g.strip()}
        genre_score = max((preferred.get(g, 0) for g in genres), default=0)
        # Riff rankCandidates accumulates independent seed evidence. A bounded
        # corroboration bonus rewards a song related to several liked artists
        # without allowing duplicates from one seed to manufacture relevance.
        evidence = {self._artist_key(a) for a in candidate.get('recommendation_seed_artists', []) if a}
        corroboration = min(.15, max(0, len(evidence) - 1) * .05)
        return affinity * .35 + recent * .1 + float(favorite) * .1 + relevance * .35 + genre_score * .1 + corroboration

    @staticmethod
    def _bounded_score(value):
        try:
            score = float(value or 0)
            return min(1.0, max(0.0, score)) if math.isfinite(score) else 0.0
        except (ValueError, TypeError):
            return 0.0

    def _rank_tracks(self, tracks, profile, limit, exclude_tracks=(), exclude_ids=()):
        limit = max(0, min(50, int(limit)))
        if not limit:
            return []
        excluded = {str(i).strip().casefold() for i in exclude_ids if i is not None}
        excluded_content = {self._content_key(t) for t in exclude_tracks if isinstance(t, dict)}
        blocked, disliked = self._feedback()
        excluded_content.update(disliked)
        known = self._known_content_keys(profile)
        known_rows = {}
        def identity_quality(t):
            return (bool(t.get('file_path')), bool(t.get('is_favorite')),
                    bool(t.get('is_downloaded')), bool(t.get('id')))
        for known_track in self._known_tracks(profile):
            if not self._playable(known_track):
                continue
            content = self._content_key(known_track)
            previous = known_rows.get(content)
            if previous is None or identity_quality(known_track) > identity_quality(previous):
                known_rows[content] = known_track
        skipped = set()
        for track in profile.recent_history:
            listened, duration = track.get('duration_listened'), track.get('duration')
            if track.get('listening_measured') and not track.get('session_finished'):
                continue
            if listened is not None and duration and not track.get('completed') and not track.get('is_favorite'):
                try:
                    heard = float(track.get('media_listened') or listened)
                    if 0 <= float(listened) < 10 and heard < float(duration) * .1 and (float(listened) > 0 or track.get('listening_measured')):
                        skipped.add(self._content_key(track))
                except (TypeError, ValueError):
                    pass
        ranked, seen, seen_ids = [], set(), set()
        for index, track in enumerate(tracks):
            if not self._playable(track):
                continue
            key = self._content_key(track)
            original_ids = {str(track.get(k)).strip().casefold() for k in ('id', 'source_id') if track.get(k) is not None}
            if key in known_rows:
                track = dict(track)
                current = known_rows[key]
                for field in ('id', 'source', 'source_id', 'source_url', 'file_path', 'is_favorite', 'is_downloaded'):
                    if current.get(field) is not None and (current.get(field) != '' or field in ('is_favorite', 'is_downloaded')):
                        track[field] = current[field]
            ids = {str(track.get(k)).strip().casefold() for k in ('id', 'source_id') if track.get(k) is not None}
            ids.update(original_ids)
            ids.add(':'.join(key))
            provider_id = (track.get('source'), str(track.get('source_id') or track.get('id') or ''))
            if key[0] in blocked or key in seen or key in excluded_content or ids.intersection(excluded) or provider_id in seen_ids:
                continue
            seen.add(key)
            seen_ids.add(provider_id)
            score = self._calculate_taste_weights(track, profile) + (0.18 if key not in known else 0)
            if key in skipped:
                score -= 1
            ranked.append((score, index, self._format_ui_track(track), key in known))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        result, deferred, artist_counts = [], [], {}
        familiar_count, familiar_cap = 0, max(1, round(limit * 0.3))
        artist_cap = max(2, math.ceil(limit / 5))
        known_artists = {(a.get('identity_key') or self._artist_key(a.get('name'))) for a in profile.top_artists}
        known_artists.update(self._artist_key(t) for t in self._known_tracks(profile))
        configured_ratio = self.settings.get('personalization', 'discovery_ratio', .2) if self.settings else .2
        discovery_count = round(limit * min(.4, self._bounded_score(configured_ratio))) if known_artists else 0
        for _, _, track, familiar in ranked:
            artist = self._artist_key(track)
            if discovery_count <= 0:
                break
            if artist not in known_artists and self._bounded_score(track.get('recommendation_relevance')) >= .5 and artist_counts.get(artist, 0) < artist_cap:
                result.append(track)
                artist_counts[artist] = artist_counts.get(artist, 0) + 1
                discovery_count -= 1
        for _, _, track, familiar in ranked:
            if track in result:
                continue
            artist = self._artist_key(track)
            low_confidence_discovery = (artist not in known_artists and
                                       0 < self._bounded_score(track.get('recommendation_relevance')) < .5)
            if low_confidence_discovery:
                continue
            if artist_counts.get(artist, 0) >= artist_cap or (familiar and familiar_count >= familiar_cap):
                deferred.append((track, familiar))
                continue
            result.append(track)
            artist_counts[artist] = artist_counts.get(artist, 0) + 1
            familiar_count += int(familiar)
            if len(result) >= limit:
                return result[:limit]
        # A small offline library still produces a useful list.
        # Relax artist limits before filling with extra familiar songs.
        deferred.sort(key=lambda item: item[1])
        return (result + [track for track, _ in deferred])[:limit]

    def _lastfm_enabled(self):
        if self.settings is None or self.settings.get('services', 'lastfm_enabled', False) is not True:
            return False
        configured = getattr(self.lastfm, '_resolve_api_keys', None)
        return bool(configured()) if callable(configured) else bool(self.lastfm)

    def _collect_candidates(self, profile, seeds=None, artists=None, limit=20, deadline=None):
        seeds = seeds if seeds is not None else self._seed_tracks(profile)
        artists = artists if artists is not None else self._get_merged_seed_artists(profile, limit=3)
        blocked, disliked = self._feedback()
        seeds = [t for t in seeds if self._artist_key(t) not in blocked and self._content_key(t) not in disliked]
        artists = [a for a in artists if self._artist_key(a) not in blocked]
        signature = (tuple((self._content_key(t), t.get('source'), t.get('source_id')) for t in seeds), tuple(artists), limit,
                     self._provider_enabled('youtube'), self._provider_enabled('soundcloud'), self._provider_enabled('deezer'), self._lastfm_enabled())
        key = 'recommendation:candidates:' + repr(signature)
        cached = self.get_search_cache(key)
        if cached is not None:
            if isinstance(cached, dict) and cached.get('error'):
                raise RuntimeError(cached['error'])
            return [dict(t) for t in cached]
        with self._cache_lock:
            future = self._candidate_flights.get(key)
            leader = future is None
            if leader:
                future = Future()
                self._candidate_flights[key] = future
        if not leader:
            try:
                remaining = min(12.0, max(0, deadline - time.monotonic())) if deadline is not None else 12.0
                return [dict(t) for t in future.result(timeout=remaining)]
            except TimeoutError:
                return []
        try:
            candidates = self._collect_uncached_candidates(seeds, artists, limit, deadline=deadline)
            self.set_search_cache(key, [dict(t) for t in candidates])
            if not candidates:
                with self._cache_lock:
                    self._search_cache[key]['ts'] -= self._SEARCH_CACHE_TTL - 15
            future.set_result(candidates)
            return candidates
        except Exception as exc:
            self.set_search_cache(key, {'error': str(exc)})
            with self._cache_lock:
                self._search_cache[key]['ts'] -= self._SEARCH_CACHE_TTL - 15
            future.set_exception(exc)
            raise
        finally:
            with self._cache_lock:
                if self._candidate_flights.get(key) is future:
                    self._candidate_flights.pop(key, None)

    def _collect_uncached_candidates(self, seeds, artists, limit, deadline=None):
        deadline = min(deadline, time.monotonic() + 12.0) if deadline is not None else time.monotonic() + 12.0
        jobs = []
        def add_job(source, artist, work):
            jobs.append((source, self._artist_key(artist), work))
        artist_budget = 10 if limit >= 60 else 2
        for seed in seeds[:10 if limit >= 60 else 5]:
            sid = str(seed.get('source_id') or '')
            if seed.get('source') == 'soundcloud' and self.sc_service and self._provider_enabled('soundcloud'):
                add_job('soundcloud_related', seed.get('artist'), lambda seed=seed:
                        self._related_soundcloud_seed(seed, min(30, limit + 5), deadline))
            elif seed.get('source') == 'youtube' and self.youtube_service and self._provider_enabled('youtube'):
                related = getattr(self.youtube_service, 'get_related_tracks_sync', None)
                if callable(related):
                    add_job('youtube_radio', seed.get('artist'), lambda sid=sid, related=related: related(sid, limit=min(30, limit + 5)))
            elif seed.get('title') and seed.get('artist'):
                add_job('seed_radio', seed.get('artist'), lambda seed=seed:
                        self._related_catalogue_seed(seed, min(30, limit + 5), deadline))
        if self.youtube_service and self._provider_enabled('youtube'):
            for artist in artists[:artist_budget]:
                add_job('artist_search', artist, lambda artist=artist: self.youtube_service.search_sync(artist, limit=8, timeout=5))
        if self._provider_enabled('deezer') and (seeds or artists):
            add_job('catalogue_discovery', '', lambda: self._catalogue_discovery_candidates(seeds, artists, limit, deadline))
        if self._lastfm_enabled():
            for seed in seeds[:2]:
                if seed.get('artist') and seed.get('title'):
                    add_job('lastfm_similar', seed['artist'], lambda seed=seed: self.lastfm.track.getSimilar(seed['artist'], seed['title'], limit=10))
            for artist in artists[:2]:
                add_job('lastfm_artist', artist, lambda artist=artist: self.lastfm.artist.getTopTracks(artist, limit=6))
        futures = [self._candidate_executor.submit(work) for _, _, work in jobs]
        done, pending = wait(futures, timeout=min(8.0, max(0, deadline - time.monotonic()))) if futures else (set(), set())
        for future in pending:
            future.cancel()
        by_content, errors = {}, []
        for future, (source, seed_artist, _) in zip(futures, jobs):
            if future not in done:
                errors.append(source + ': request deadline exceeded')
                continue
            try:
                items = future.result() or []
            except Exception as exc:
                errors.append(source + ': ' + str(exc))
                self.logger.warning('Recommendation provider unavailable: %s', exc)
                continue
            for position, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                candidate = dict(item)
                candidate['title'] = candidate.get('title') or candidate.get('name') or ''
                if isinstance(candidate.get('artist'), dict):
                    candidate['artist'] = candidate['artist'].get('name') or ''
                key = self._content_key(candidate)
                if not key[1]:
                    continue
                rank = 1 / (1 + position * .18)
                evidence_source = source
                seed_artists = [seed_artist] if seed_artist else []
                if source == 'catalogue_discovery':
                    evidence_source = candidate.get('recommendation_source') or 'deezer_radio'
                    relevance = self._bounded_score(candidate.get('recommendation_relevance'))
                    seed_artists = list(candidate.get('recommendation_seed_artists') or [])
                elif source == 'lastfm_similar' and candidate.get('match') is not None:
                    relevance = self._bounded_score(candidate['match']) * .6 + rank * .4
                else:
                    relevance = rank * {'youtube_radio': .95, 'soundcloud_related': .9, 'seed_radio': .9,
                                        'artist_search': .4, 'lastfm_similar': .8, 'lastfm_artist': .45}[source]
                candidate.update(recommendation_source=evidence_source, recommendation_relevance=relevance,
                                 recommendation_seed_artists=seed_artists)
                previous = by_content.get(key)
                if previous:
                    seeds_for_track = list(dict.fromkeys(previous['recommendation_seed_artists'] + candidate['recommendation_seed_artists']))
                    # Preserve an already playable result while combining stronger
                    # Last.fm/radio evidence for this exact song.
                    winner = candidate if self._playable(candidate) and not self._playable(previous) else previous
                    best_relevance = max(relevance, previous['recommendation_relevance'])
                    best_source = evidence_source if relevance > previous['recommendation_relevance'] else previous['recommendation_source']
                    winner['recommendation_relevance'] = best_relevance
                    winner['recommendation_source'] = best_source
                    winner['recommendation_seed_artists'] = seeds_for_track
                    by_content[key] = winner
                else:
                    by_content[key] = candidate
        candidates = [t for t in by_content.values() if self._playable(t)]
        metadata = [t for t in by_content.values() if not self._playable(t) and t.get('artist')]
        remaining = max(0, deadline - time.monotonic())
        if metadata and remaining > 0:
            try:
                pairs = [(t['title'], t['artist']) for t in metadata[:20]]
                resolved = self.resolver.resolve_tracks(pairs, timeout=remaining)
                for result, evidence in zip(resolved, metadata):
                    candidate = dict(result)
                    for key in ('recommendation_relevance', 'recommendation_source', 'recommendation_seed_artists'):
                        candidate[key] = evidence[key]
                    if not candidate.get('genre'):
                        candidate['genre'] = evidence.get('genre') or ''
                    candidates.append(candidate)
            except Exception as exc:
                self.logger.debug('Recommendation metadata resolution unavailable: %s', exc)
        if not candidates and errors:
            raise RuntimeError('Источники рекомендаций недоступны: ' + '; '.join(errors))
        return candidates

    def _related_soundcloud_seed(self, seed, limit, deadline, recover=True):
        """A stored native ID is evidence only after checking its actual recording.

        Imported rows can carry a stale/mislabelled ID. Never rewrite the user's
        row or teach their taste profile from that unrelated ID's radio graph.
        """
        if time.monotonic() >= deadline:
            return []
        sid = str(seed.get('source_id') or '')
        key = 'recommendation:sc_seed_metadata:' + sid
        metadata = self.get_search_cache(key)
        if metadata is None:
            getter = getattr(self.sc_service, 'get_track_metadata', None)
            try:
                metadata = getter(sid) if callable(getter) else {}
            except Exception:
                metadata = {}
            if metadata:
                self.set_search_cache(key, dict(metadata))
        metadata = metadata or {}
        expected_key, actual_key = self._content_key(seed), self._content_key(metadata)
        try:
            expected_duration = float(seed.get('duration') or 0)
            actual_duration = float(metadata.get('duration') or 0)
        except (ValueError, TypeError):
            expected_duration = actual_duration = 0
        duration_known = expected_duration > 0 and actual_duration > 0
        duration_matches = duration_known and abs(expected_duration - actual_duration) <= max(2, expected_duration * .02)
        # SC's artist field is often an uploader. An exact recording title and
        # close duration can corroborate such a row without requiring that name.
        same_title = bool(expected_key[1] and expected_key[1] == actual_key[1])
        same_recording = same_title and (duration_matches or
                         (not duration_known and expected_key == actual_key))
        if same_recording and time.monotonic() < deadline:
            return self.sc_service.get_related_tracks_sync(sid, limit=limit)
        if recover:
            return self._related_catalogue_seed(seed, limit, deadline)
        return []

    def _related_catalogue_seed(self, seed, limit, deadline):
        remaining = min(5.0, max(0, deadline - time.monotonic()))
        if not remaining or not any(self._provider_enabled(p) for p in ('youtube', 'soundcloud')):
            return []
        resolved = self._radio_seed_resolver.resolve_tracks(
            [(seed['title'], seed['artist'], seed.get('duration') or 0)], timeout=remaining)
        if not resolved or time.monotonic() >= deadline:
            return []
        native = resolved[0]
        if native.get('source') == 'soundcloud' and self._provider_enabled('soundcloud'):
            return self._related_soundcloud_seed(native, limit, deadline, recover=False)
        provider = (self.youtube_service if native.get('source') == 'youtube' else
                    self.sc_service if native.get('source') == 'soundcloud' else None)
        related = getattr(provider, 'get_related_tracks_sync', None)
        if callable(related) and native.get('source_id') and self._provider_enabled(native['source']):
            return related(str(native['source_id']), limit=limit)
        return []

    def _catalogue_discovery_candidates(self, seeds, artists, limit, deadline):
        from services.recommendation_discovery import RecommendationDiscovery
        with self._cache_lock:
            if self._discovery is None:
                self._discovery = RecommendationDiscovery(settings=self.settings)
            discovery = self._discovery
        return discovery.get_candidates(seeds, artists, limit=limit, deadline=deadline)

    def _feed_tracks(self, profile, max_results, deadline=None):
        if max_results <= 0:
            return []
        source_revision = getattr(profile, '_source_revision', None)
        seed_signature = source_revision or tuple((self._content_key(t), t.get('id'), t.get('source'), t.get('source_id'),
                                t.get('file_path'), t.get('weighted_score'), t.get('is_favorite'),
                                t.get('is_downloaded'), t.get('duration_listened'), t.get('completed'), t.get('media_listened'), t.get('session_finished'))
                               for t in self._known_tracks(profile))
        seed_artists = self._get_merged_seed_artists(profile, limit=3)
        signature = (tuple(seed_artists), tuple((a.get('name'), a.get('play_count')) for a in profile.top_artists),
                     seed_signature, tuple(self._content_key(t) for t in profile.recent_history[:10]),
                     tuple(self._content_key(t) for t in profile.favorite_tracks),
                     self._get_time_of_day_context()['vibe_key'], datetime.date.today().isoformat(), max_results,
                     repr(self._feedback()), repr(artist_aliases(self.settings)),
                     repr(self.settings.get('personalization', 'favorite_genres', []) if self.settings else []),
                     self.settings.get('personalization', 'discovery_ratio', .2) if self.settings else .2,
                     self._provider_enabled('youtube'), self._provider_enabled('soundcloud'), self._provider_enabled('deezer'), self._lastfm_enabled())
        digest = hashlib.sha256()
        for component in signature:
            encoded = repr(component).encode('utf-8')
            digest.update(str(len(encoded)).encode('ascii'))
            digest.update(b':')
            digest.update(encoded)
        key = 'recommendation:feed:' + digest.hexdigest()
        cached = self.get_search_cache(key)
        if cached is not None:
            return [dict(t) for t in cached]
        familiar = profile.get_seed_tracks(limit=20) + profile.get_local_liked_and_downloaded_tracks(limit=20) + profile.recent_history
        try:
            candidates = self._collect_candidates(profile, artists=seed_artists, deadline=deadline)
        except Exception:
            # An unavailable discovery provider must not hide the user's local
            # library. With no usable alternative, retain the explicit failure.
            if not self._rank_tracks(familiar, profile, max_results, exclude_tracks=profile.recent_history[:1]):
                raise
            candidates = []
        tracks = self._rank_tracks(candidates + familiar, profile, max_results,
                                   exclude_tracks=profile.recent_history[:1])
        if not tracks and profile.is_empty() and not profile.recent_history:
            tracks = self._rank_tracks(CURATED_WELCOME_TRACKS, profile, max_results)
        tracks = [dict(t, recommendation_origin='feed') for t in tracks]
        self.set_search_cache(key, [dict(t) for t in tracks])
        if not candidates:
            with self._cache_lock:
                self._search_cache[key]['ts'] -= self._SEARCH_CACHE_TTL - 15
        return tracks

    def _async_recommendation(self, key, task, callback, error_callback):
        leader, callback, error_callback = self._join_request(key, callback, error_callback)
        if not leader:
            return None
        def run():
            try:
                callback(task())
            except Exception as exc:
                self.logger.warning('Recommendation generation failed: %s', exc)
                error_callback(str(exc))
        if self.submit(run) is None:
            error_callback('Recommendation service is shutting down')
        return None

    def _get_merged_seed_artists(self, taste_profile, limit=10):
        seed_artists = taste_profile.get_seed_artists(limit=max(20, limit))
        seed_artists += [t.get('artist') for t in self._known_tracks(taste_profile) if t.get('artist')]
        username = self.settings.get('auth', 'lastfm_username', '') if self.settings else ''
        username = username or os.getenv('LASTFM_USERNAME', '')
        user_artists = []
        if username and self._lastfm_enabled():
            key = 'recommendation:scrobbles:' + str(username)
            cached = self.get_search_cache(key)
            if isinstance(cached, dict) and cached.get('expires', 0) > time.monotonic():
                user_artists = cached.get('artists', [])
            else:
                # Scrobble import must not hold up local/YouTube recommendations.
                with self._cache_lock:
                    leader = key not in self._candidate_flights
                    if leader:
                        self._candidate_flights[key] = Future()
                if leader:
                    def warm(cache_key=key, username=username):
                        names = []
                        try:
                            names = [a['name'] for a in (self.lastfm.user.getTopArtists(username, limit=5) or [])
                                     if isinstance(a, dict) and a.get('name')]
                        except Exception as exc:
                            self.logger.debug('Scrobble seeds unavailable: %s', exc)
                        finally:
                            self.set_search_cache(cache_key, {'artists': names,
                                'expires': time.monotonic() + (300 if names else 15)})
                            with self._cache_lock:
                                self._candidate_flights.pop(cache_key, None)
                    try:
                        self._candidate_executor.submit(warm)
                    except RuntimeError:
                        with self._cache_lock:
                            self._candidate_flights.pop(key, None)
        combined = (user_artists + seed_artists if taste_profile.is_empty() and not taste_profile.recent_history
                    else seed_artists + user_artists)
        result, seen = [], set()
        blocked = self._feedback()[0]
        for artist in combined:
            key = self._artist_key(artist)
            if key and key not in seen and key not in blocked:
                seen.add(key)
                result.append(artist)
                if len(result) >= limit:
                    break
        return result[:limit]

    def _sequence_mix_tracks(self, tracks):
        # Interleave artists using actual metadata; do not invent energy/BPM.
        remaining, result = list(tracks), []
        while remaining:
            previous = self._artist_key(result[-1]) if result else None
            index = next((i for i, t in enumerate(remaining) if self._artist_key(t) != previous), 0)
            result.append(remaining.pop(index))
        return result

    def _fetch_recommendations(self, seed_track, max_results):
        return self.get_wave_for_track(seed_track, limit=max_results)

    def get_recommendations(self, seed_track: dict, max_results: int = 20, callback: Callable = None, error_callback: Callable = None):
        def _task():
            try:
                tracks = self._fetch_recommendations(seed_track, max_results)
                if callback:
                    callback(tracks)
            except Exception as e:
                self.logger.error(f'Exception in get_recommendations: {e}')
                if error_callback:
                    error_callback(str(e))

        self._executor.submit(_task)

    def get_charts(self, country='US', max_results=20, callback: Optional[Callable] = None, error_callback: Optional[Callable] = None):
        def _task():
            tracks = []
            try:
                chart_raw = []
                if self._lastfm_enabled() and hasattr(self, 'lastfm') and self.lastfm and hasattr(self.lastfm, 'country_get_top_tracks'):
                    try:
                        chart_raw = self.lastfm.country_get_top_tracks(country, limit=max_results * 2) or []
                    except Exception as exc:
                        self.logger.warning(f'Last.fm country_get_top_tracks failed: {exc}')
                        chart_raw = []
                seen = set()

                self._prefetch_resolutions(
                    [(item.get('name', ''), item.get('artist', '')) for item in chart_raw],
                    max_results + 5,
                )

                for item in chart_raw:
                    t_name = item.get('name', '')
                    t_artist = item.get('artist', '')
                    key = f'{t_artist.lower()}:{t_name.lower()}'
                    if key in seen:
                        continue
                    seen.add(key)

                    resolved = self.resolver.resolve_track(t_name, t_artist)
                    if not resolved:
                        continue
                    if resolved.get('source') not in ('soundcloud', 'youtube', 'local'):
                        continue

                    ui_track = self._format_ui_track(resolved)
                    tracks.append(ui_track)
                    if len(tracks) >= max_results:
                        break
            except Exception as e:
                self.logger.warning(f"Last.fm get_charts failed ({e}), falling back to local DB/curated")

            if not tracks:
                if self.db and hasattr(self.db, 'get_most_played_tracks'):
                    try:
                        db_tracks = self.db.get_most_played_tracks(limit=max_results)
                        tracks = [self._format_ui_track(t) for t in db_tracks] if db_tracks else []
                    except Exception as e:
                        self.logger.warning(f'get_most_played_tracks fallback failed: {e}')
                        tracks = []
                elif self.db and callable(getattr(self.db, 'get_all_tracks', None)):
                    try:
                        rows = self.db.get_all_tracks(limit=max_results)
                        tracks = [self._format_ui_track(r) for r in rows] if rows else []
                    except Exception as e:
                        self.logger.warning(f'Local tracks fallback query failed: {e}')
                        tracks = []
                if not tracks:
                    tracks = CURATED_WELCOME_TRACKS[:max_results]

            if callback:
                callback(tracks[:max_results])

        self._executor.submit(_task)

    def get_feed(self, history=None, personalization=None, max_results=20, callback=None, error_callback=None):
        max_results = max(0, min(50, int(max_results)))
        key = 'recommendation:pending-feed:' + repr((history, personalization, max_results))
        return self._async_recommendation(key, lambda: self._feed_tracks(self._profile(history), max_results),
                                          callback, error_callback)

    def get_custom_artists(self, history: List[dict] = None, personalization: dict = None, max_results: int = 10, callback: Callable = None):
        def _task():
            try:
                artists = []
                seen = set()

                def add_artist(name, thumb=''):
                    if name and name not in seen and name != 'Unknown Artist':
                        seen.add(name)
                        artists.append({
                            'artist': name,
                            'cover_url': thumb or 'https://img.youtube.com/vi/hqdefault.jpg',
                        })

                if history:
                    for t in history:
                        add_artist(t.get('artist'), t.get('cover_url'))

                if self.db:
                    taste_profile = UserTasteProfile(settings=self.settings).build_from_db(self.db)
                else:
                    taste_profile = UserTasteProfile(settings=self.settings)

                seed_artists = self._get_merged_seed_artists(taste_profile, limit=10)
                for sa in seed_artists:
                    add_artist(sa)

                if len(artists) < max_results and self._lastfm_enabled():
                    try:
                        chart_arts = self.lastfm.chart.getTopArtists(limit=max_results)
                        for ca in chart_arts:
                            add_artist(ca.get('name'), ca.get('image'))
                    except Exception as e:
                        self.logger.warning(f'Last.fm chart.getTopArtists failed: {e}')

                if callback:
                    callback(artists[:max_results])
            except Exception as e:
                self.logger.error(f'Error fetching custom artists: {e}')
                if callback:
                    callback([])

        self._executor.submit(_task)

    def get_releases(self, favorite_artists=None, max_results=10, callback=None, error_callback=None):
        # The providers offer popular artist tracks, not verified release dates.
        # The home section is labelled "From favorite artists" accordingly.
        def task():
            profile = self._profile()
            artists = [str(a).strip() for a in (favorite_artists or []) if a and str(a).strip()]
            if not artists and not profile.is_empty():
                artists = self._get_merged_seed_artists(profile, limit=3)
            if not artists:
                return []
            candidates = self._collect_candidates(profile, seeds=[], artists=artists[:3], limit=max_results)
            return [dict(t, recommendation_origin='artist') for t in self._rank_tracks(candidates, profile, max_results)]
        return self._async_recommendation('recommendation:pending-artists:' + repr((favorite_artists, max_results)),
                                          task, callback, error_callback)

    def _daily_artist_buckets(self, profile):
        # Riff planMixes: rank taste artists, distribute across up to five
        # buckets, with at least two artists per daily mix. Stable per day.
        import random
        artists=list(dict.fromkeys(self._get_merged_seed_artists(profile, limit=28)))
        if len(artists)<2:return []
        weights={self._artist_key(row.get('name','')):float(row.get('play_count',0) or 0) for row in profile.top_artists}
        rng=random.Random(datetime.date.today().isoformat()+repr(artists))
        artists.sort(key=lambda name:-(weights.get(self._artist_key(name),1)*(0.65+rng.random()*0.7)))
        count=min(5,len(artists)//2)
        return [artists[index::count] for index in range(count)]

    def get_mixes(self, history=None, personalization=None, max_results=10, callback=None, error_callback=None):
        def task():
            deadline = time.monotonic() + 17.0
            profile = self._profile(history)
            familiar = self._rank_tracks(profile.get_local_liked_and_downloaded_tracks(limit=30)
                                         + profile.get_seed_tracks(limit=20) + profile.recent_history,
                                         profile, 20)
            feed = self._feed_tracks(profile, 30, deadline=deadline)
            known = self._known_content_keys(profile)
            buckets = self._daily_artist_buckets(profile)
            candidates = self._daily_mix_candidates(profile, buckets, feed, known, deadline)
            discoveries = self._rank_tracks([t for t in candidates if self._content_key(t) not in known], profile, 20)
            mixes = []
            def add_mix(title, tracks, discovery_first=False):
                if discovery_first:
                    ordered = (self._sequence_mix_tracks([t for t in tracks if self._content_key(t) not in known])
                               + self._sequence_mix_tracks([t for t in tracks if self._content_key(t) in known]))
                else:
                    ordered = self._sequence_mix_tracks(tracks)
                tracks = [dict(t, recommendation_origin='mix') for t in ordered[:12]]
                if tracks:
                    mixes.append({'type': 'custom_playlist', 'title': title, 'artist': 'NeDotify',
                                  'cover_url': tracks[0].get('cover_url') or '', 'tracks': tracks})
            add_mix('Любимые и знакомые', familiar)
            add_mix('Открытия для вас', discoveries)
            for index,artists in enumerate(buckets,1):
                keys={self._artist_key(artist) for artist in artists}
                related = [t for t in candidates if self._belongs_to_daily_bucket(t, keys)]
                unheard = self._rank_tracks([t for t in related if self._content_key(t) not in known], profile, 12)
                if unheard:
                    old = self._rank_tracks([t for t in familiar if self._artist_key(t) in keys], profile, 12-len(unheard))
                    # The visible collage and the beginning of the exact play
                    # queue reflect the generated material, rather than replay.
                    add_mix(f'Ежедневный микс {index}', unheard + old, discovery_first=True)
                    mixes[-1].update(artist=', '.join(artists),mix_id=f'daily-mix-{index}',date=datetime.date.today().isoformat())
            if not mixes:
                add_mix('Первое знакомство', self._rank_tracks(CURATED_WELCOME_TRACKS, profile, 12))
            return mixes[:max(0, min(10, int(max_results)))]
        return self._async_recommendation('recommendation:pending-mixes:' + repr((history, personalization, max_results)),
                                          task, callback, error_callback)

    def _belongs_to_daily_bucket(self, track, artist_keys):
        return (self._artist_key(track) in artist_keys or
                bool(set(track.get('recommendation_seed_artists') or []).intersection(artist_keys)))

    def _daily_mix_candidates(self, profile, buckets, feed, known, deadline):
        missing = [artists for artists in buckets if not any(
            self._content_key(track) not in known and self._belongs_to_daily_bucket(
                track, {self._artist_key(artist) for artist in artists}) for track in feed)]
        if not missing or time.monotonic() >= deadline:
            return feed
        # Round-robin the first two seed artists of each underserved bucket.
        # One shared batch owns the remaining deadline, never five serial jobs.
        artists = [group[index] for index in range(2) for group in missing if len(group) > index][:10]
        available = self._known_tracks(profile)
        seeds = []
        for artist in artists:
            seed = next((t for t in available if self._artist_key(t) == self._artist_key(artist) and self._playable(t)), None)
            if seed:
                seeds.append(seed)
        try:
            return feed + self._collect_candidates(profile, seeds=seeds, artists=artists, limit=60, deadline=deadline)
        except Exception as exc:
            self.logger.debug('Daily discovery sources unavailable: %s', exc)
            return feed

    def get_smart_home_feed(self, history: List[dict] = None, personalization: dict = None, callback: Callable = None, error_callback: Callable = None):
        """Assemble the home view from the same signals used by Mix and Wave.

        Riff's My Mix/My Wave share history, favorites, candidate collection and
        avoidance feedback. Keep those contracts here too: no second resolver
        pipeline or stale home-only cache that can ignore a dislike or a source.
        """
        def task():
            profile = self._profile(history)
            context = self._get_time_of_day_context()
            feed = self._feed_tracks(profile, 30)
            familiar = self._rank_tracks(
                profile.get_local_liked_and_downloaded_tracks(limit=30)
                + profile.get_seed_tracks(limit=20) + profile.recent_history,
                profile, 20)
            known = self._known_content_keys(profile)
            discoveries = [t for t in feed if self._content_key(t) not in known]
            mixes = []

            def add_mix(title, tracks):
                tracks = [dict(t, recommendation_origin='mix')
                          for t in self._sequence_mix_tracks(tracks[:12])]
                if tracks:
                    mixes.append({'type': 'custom_playlist', 'title': title,
                                  'artist': 'NeDotify', 'cover_url': tracks[0].get('cover_url') or '',
                                  'tracks': tracks})

            add_mix('Любимые и знакомые', familiar)
            add_mix('Открытия для вас', discoveries)
            for artist in self._get_merged_seed_artists(profile, limit=3):
                group = self._rank_tracks(
                    [t for t in feed + familiar if self._artist_key(t) == self._artist_key(artist)],
                    profile, 8)
                if len(group) >= 3:
                    add_mix(f'Микс: {artist}', group)
            sections = [{'title': context['title'], 'items': feed[:10]},
                        {'title': 'Специально для вас', 'items': mixes}]
            if discoveries:
                sections.append({'title': 'Открытия для вас', 'items': discoveries[:10]})
            return {'greeting': context['greeting'], 'sections': sections}

        key = 'recommendation:pending-smart-home:' + repr((history, personalization))
        return self._async_recommendation(key, task, callback, error_callback)

    def get_authentic_home(self, history=None, max_results=5, callback: Optional[Callable] = None, error_callback: Optional[Callable] = None):
        # Callers in core/api.py (get_authentic_home_feed) fetch history from the DB
        # themselves and pass it through get_feed; this helper keeps a safe default
        # of [] when no history is supplied so it never blocks on missing data.
        if history is None:
            history = []
        def _on_feed(payload):
            if callback:
                if isinstance(payload, dict) and 'sections' in payload:
                    callback(payload['sections'][:max(0, min(20, int(max_results)))])
                else:
                    callback(payload)

        self.get_smart_home_feed(history=history, callback=_on_feed, error_callback=error_callback)

    def get_yt_playlist_tracks(self, playlist_id: str, limit: int = 50, callback: Optional[Callable] = None, error_callback: Optional[Callable] = None):
        # A playlist id identifies real provider contents, never Last.fm charts.
        limit = max(0, min(50, int(limit)))
        if not limit or not self._provider_enabled('youtube'):
            if callback:
                callback([])
            return None
        provider = getattr(self.youtube_service, 'get_playlist_tracks', None)
        if not callable(provider):
            if error_callback:
                error_callback('Источник YouTube недоступен')
            return None

        def completed(tracks):
            if callback:
                callback([self._format_ui_track(t) for t in (tracks or []) if self._playable(t)][:limit])
        try:
            return provider(playlist_id, limit=limit, callback=completed, error_callback=error_callback)
        except Exception as exc:
            if error_callback:
                error_callback(str(exc))
            return None

    def get_wave_for_track(self, seed_track, limit=15, exclude_ids=None, callback=None, error_callback=None):
        def task():
            seed = seed_track if isinstance(seed_track, dict) else {}
            profile = self._profile()
            seeds = [seed] if seed else self._seed_tracks(profile)
            artists = [seed['artist']] if seed.get('artist') else self._get_merged_seed_artists(profile, limit=2)
            candidates = self._collect_candidates(profile, seeds=seeds, artists=artists, limit=limit)
            familiar = profile.get_seed_tracks(limit=20) + profile.recent_history
            blocked = list(exclude_ids or []) + [seed.get('id'), seed.get('source_id')]
            return [dict(t, recommendation_origin='wave') for t in self._rank_tracks(candidates + familiar, profile, limit, exclude_tracks=[seed], exclude_ids=blocked)]
        if callback:
            key = 'recommendation:pending-wave:' + repr((seed_track, limit, exclude_ids))
            return self._async_recommendation(key, task, callback, error_callback)
        return task()
