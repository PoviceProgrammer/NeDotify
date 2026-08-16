"""
NeDotify / AURA Music - Recommendation Service
Completely decoupled from YTMusic. Uses LastFMService, UserTasteProfile, and TrackResolver
to generate personalized smart feeds, time-of-day contextual recommendations, and curated mixes.
"""

import os
import time
import math
import random
import logging
import datetime
from typing import Callable, Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

from services.base_service import BaseMusicService
from services.lastfm_service import LastFMService
from services.taste_profile import UserTasteProfile
from services.track_resolver import TrackResolver, resolve_track

logger = logging.getLogger(__name__)


class RecommendationService(BaseMusicService):
    """Generates track and mix recommendations using Last.fm API, UserTasteProfile, and TrackResolver."""

    DEFAULT_FALLBACK_ARTISTS = ['The Weeknd', 'Dua Lipa', 'Eminem', 'Queen', 'Coldplay']

    def __init__(self, settings=None, db=None, soundcloud_service=None, youtube_service=None):
        super().__init__()
        self.settings = settings
        self.db = db
        self.logger = logging.getLogger(self.__class__.__name__)

        self.lastfm = LastFMService(settings=settings)
        self.resolver = TrackResolver(db=db, soundcloud_service=soundcloud_service, youtube_service=youtube_service)

    @property
    def available(self) -> bool:
        return True

    def reset_service(self):
        pass

    def _format_ui_track(self, track: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(track, dict):
            return {}
        return {
            'title': track.get('title') or 'Unknown Title',
            'artist': track.get('artist') or 'Unknown Artist',
            'cover_url': track.get('cover_url') or track.get('cover_path') or '',
            'source': track.get('source') or 'unknown',
            'source_id': str(track.get('source_id') or track.get('id') or ''),
            'source_url': track.get('source_url') or '',
            'duration': float(track.get('duration') or 0),
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

    def _calculate_taste_weights(self, candidate: Dict[str, Any], taste_profile: UserTasteProfile) -> float:
        artist = candidate.get('artist', '')
        title = candidate.get('title', '')

        play_count = 0
        for top_a in taste_profile.top_artists:
            if top_a.get('name', '').lower() == artist.lower():
                play_count = top_a.get('play_count', 0)
                break

        play_count_norm = min(1.0, play_count / 20.0)

        recency_norm = 0.2
        for idx, hist in enumerate(taste_profile.recent_history[:20]):
            if hist.get('artist', '').lower() == artist.lower():
                recency_norm = max(recency_norm, 1.0 - idx / 20.0)
                break

        current_vibe = taste_profile.get_time_of_day_vibe()
        vibe_count = taste_profile.time_of_day_habits.get(current_vibe, 0)
        total_habits = sum(taste_profile.time_of_day_habits.values()) or 1
        time_match_norm = min(1.0, vibe_count / float(total_habits))

        is_fav = any(f.get('artist', '').lower() == artist.lower() for f in taste_profile.favorite_tracks)
        fav_boost = 1.0 if is_fav else 0.0

        weight = play_count_norm * 0.4 + recency_norm * 0.3 + time_match_norm * 0.2 + fav_boost * 0.1
        return weight

    def _get_merged_seed_artists(self, taste_profile: UserTasteProfile, limit: int = 10) -> List[str]:
        seed_artists = taste_profile.get_seed_artists(limit=limit)

        if taste_profile.is_empty():
            self.logger.info('[FALLBACK] Profile is empty — using DEFAULT_FALLBACK_ARTISTS for seeds')

        lastfm_user = None
        if self.settings:
            lastfm_user = self.settings.get('auth', 'lastfm_username', '')
        if not lastfm_user:
            lastfm_user = os.getenv('LASTFM_USERNAME', '')

        if lastfm_user:
            try:
                user_top = self.lastfm.user.getTopArtists(lastfm_user, limit=5)
                for a in user_top:
                    name = a.get('name')
                    if name and name not in seed_artists:
                        seed_artists.append(name)
                self.logger.info(f'[PROFILE] Merged Last.fm scrobbles for user: {lastfm_user}')
            except Exception as e:
                self.logger.warning(f'Failed to merge Last.fm scrobbles for {lastfm_user}: {e}')

        return seed_artists[:limit]

    def _sequence_mix_tracks(self, tracks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not tracks or len(tracks) < 3:
            return tracks

        for idx, t in enumerate(tracks):
            if 'energy' not in t:
                t['_energy'] = t.get('energy', 0.4 + (idx % 5) * 0.1)
            else:
                t['_energy'] = float(t['energy'])

        sorted_by_energy = sorted(tracks, key=lambda x: x.get('_energy', 0.5))
        n = len(sorted_by_energy)

        low = sorted_by_energy[:int(n * 0.25)]
        peak = sorted_by_energy[int(n * 0.25):int(n * 0.75)]
        wind_down = sorted_by_energy[int(n * 0.75):]

        sequenced = low + peak + list(reversed(wind_down))

        for t in sequenced:
            t.pop('_energy', None)

        return sequenced

    def _fetch_recommendations(self, seed_track: dict, max_results: int):
        artist = seed_track.get('artist', '')
        title = seed_track.get('title', '')

        raw_candidates = []

        if artist and title and artist != 'Unknown Artist':
            try:
                sim_tracks = self.lastfm.track.getSimilar(artist, title, limit=max_results)
                for st in sim_tracks:
                    raw_candidates.append({'artist': st.get('artist'), 'title': st.get('name')})
            except Exception as e:
                self.logger.warning(f'Last.fm track.getSimilar failed: {e}')

        if len(raw_candidates) < max_results and artist and artist != 'Unknown Artist':
            try:
                sim_artists = self.lastfm.artist.getSimilar(artist, limit=5)
                for sa in sim_artists:
                    sa_name = sa.get('name')
                    if not sa_name:
                        continue
                    top_trks = self.lastfm.artist.getTopTracks(sa_name, limit=3)
                    for tt in top_trks:
                        raw_candidates.append({'artist': tt.get('artist') or sa_name, 'title': tt.get('name')})
            except Exception as e:
                self.logger.warning(f'Last.fm artist.getSimilar failed: {e}')

        if len(raw_candidates) < max_results:
            try:
                chart_trks = self.lastfm.chart.getTopTracks(limit=max_results)
                for ct in chart_trks:
                    raw_candidates.append({'artist': ct.get('artist'), 'title': ct.get('name')})
            except Exception as e:
                self.logger.warning(f'Last.fm chart.getTopTracks fallback failed: {e}')

        if not raw_candidates:
            for seed_a in self.DEFAULT_FALLBACK_ARTISTS:
                raw_candidates.append({'artist': seed_a, 'title': ''})

        resolved_tracks = []
        seen_keys = set()

        for cand in raw_candidates:
            c_artist = cand.get('artist', '')
            c_title = cand.get('title', '')
            if not c_artist and not c_title:
                continue

            dedup_key = f'{c_artist.lower()}:{c_title.lower()}'
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            resolved = self.resolver.resolve_track(c_title, c_artist)
            if not resolved:
                continue
            if resolved.get('source') not in ('soundcloud', 'youtube', 'local'):
                continue
            if not resolved.get('source_id') and not resolved.get('source_url'):
                continue

            ui_track = self._format_ui_track(resolved)
            resolved_tracks.append(ui_track)
            if len(resolved_tracks) >= max_results:
                break

        if not resolved_tracks:
            if self.db:
                try:
                    local_trks = UserTasteProfile().build_from_db(self.db).recent_history
                    for lt in local_trks[:max_results]:
                        resolved_tracks.append(self._format_ui_track(lt))
                except Exception:
                    pass

        if not resolved_tracks:
            for idx, seed_a in enumerate(self.DEFAULT_FALLBACK_ARTISTS[:max_results]):
                resolved_tracks.append(self._format_ui_track({
                    'title': f'Popular Track {idx + 1}',
                    'artist': seed_a,
                    'source': 'local',
                    'source_id': f'fallback_{idx + 1}',
                    'source_url': '',
                    'cover_url': 'https://img.youtube.com/vi/hqdefault.jpg',
                }))

        return resolved_tracks[:max_results]

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
            try:
                chart_raw = self.lastfm.chart.getTopTracks(limit=max_results * 2)
                tracks = []
                seen = set()

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

                if callback:
                    callback(tracks[:max_results])
            except Exception as e:
                self.logger.error(f'Error fetching charts: {e}')
                if error_callback:
                    error_callback(str(e))

        self._executor.submit(_task)

    def get_feed(self, history: List[dict], personalization: dict = None, max_results: int = 20, callback: Callable = None, error_callback: Callable = None):
        def _task():
            try:
                if self.db:
                    taste_profile = UserTasteProfile().build_from_db(self.db)
                else:
                    taste_profile = UserTasteProfile()

                seed_artists = self._get_merged_seed_artists(taste_profile, limit=5)

                all_candidates = []
                for artist in seed_artists[:3]:
                    top_trks = self.lastfm.artist.getTopTracks(artist, limit=5)
                    for tt in top_trks:
                        all_candidates.append({'artist': tt.get('artist', artist), 'title': tt.get('name', '')})

                if not all_candidates:
                    chart_trks = self.lastfm.chart.getTopTracks(limit=10)
                    for ct in chart_trks:
                        all_candidates.append({'artist': ct.get('artist', ''), 'title': ct.get('name', '')})

                resolved_list = []
                seen = set()

                for cand in all_candidates:
                    key = f"{cand['artist'].lower()}:{cand['title'].lower()}"
                    if key in seen:
                        continue
                    seen.add(key)

                    resolved = self.resolver.resolve_track(cand['title'], cand['artist'])
                    if not resolved:
                        continue
                    if resolved.get('source') not in ('soundcloud', 'youtube', 'local'):
                        continue

                    ui_track = self._format_ui_track(resolved)
                    ui_track['_weight'] = self._calculate_taste_weights(ui_track, taste_profile)
                    resolved_list.append(ui_track)

                resolved_list.sort(key=lambda x: x.get('_weight', 0.5), reverse=True)
                for t in resolved_list:
                    t.pop('_weight', None)

                if callback:
                    callback(resolved_list[:max_results])
            except Exception as e:
                self.logger.error(f'Exception in get_feed: {e}')
                if error_callback:
                    error_callback(str(e))

        self._executor.submit(_task)

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
                    taste_profile = UserTasteProfile().build_from_db(self.db)
                else:
                    taste_profile = UserTasteProfile()

                seed_artists = self._get_merged_seed_artists(taste_profile, limit=10)
                for sa in seed_artists:
                    add_artist(sa)

                if len(artists) < max_results:
                    chart_arts = self.lastfm.chart.getTopArtists(limit=max_results)
                    for ca in chart_arts:
                        add_artist(ca.get('name'), ca.get('image'))

                if callback:
                    callback(artists[:max_results])
            except Exception as e:
                self.logger.error(f'Error fetching custom artists: {e}')
                if callback:
                    callback([])

        self._executor.submit(_task)

    def get_releases(self, favorite_artists: List[str] = None, max_results: int = 10, callback: Optional[Callable] = None, error_callback: Optional[Callable] = None):
        def _task():
            try:
                artists_pool = favorite_artists or self.DEFAULT_FALLBACK_ARTISTS
                tracks = []
                seen = set()

                for artist in artists_pool[:5]:
                    top_trks = self.lastfm.artist.getTopTracks(artist, limit=4)
                    for tt in top_trks:
                        t_name = tt.get('name')
                        key = f'{artist.lower()}:{t_name.lower()}'
                        if key in seen:
                            continue
                        seen.add(key)

                        resolved = self.resolver.resolve_track(t_name, artist)
                        if not resolved:
                            continue
                        if resolved.get('source') not in ('soundcloud', 'youtube', 'local'):
                            continue

                        tracks.append(self._format_ui_track(resolved))
                        if len(tracks) >= max_results:
                            break
                    if len(tracks) >= max_results:
                        break

                if not tracks:
                    chart_trks = self.lastfm.chart.getTopTracks(limit=max_results)
                    for ct in chart_trks:
                        resolved = self.resolver.resolve_track(ct.get('name', ''), ct.get('artist', ''))
                        if not resolved:
                            continue
                        if resolved.get('source') not in ('soundcloud', 'youtube', 'local'):
                            continue

                        tracks.append(self._format_ui_track(resolved))

                if callback:
                    callback(tracks[:max_results])
            except Exception as e:
                self.logger.error(f'Error fetching releases: {e}')
                if error_callback:
                    error_callback(str(e))

        self._executor.submit(_task)

    def get_mixes(self, history: List[dict] = None, personalization: dict = None, max_results: int = 10, callback: Optional[Callable] = None, error_callback: Optional[Callable] = None):
        def _task():
            try:
                if self.db:
                    taste_profile = UserTasteProfile().build_from_db(self.db)
                else:
                    taste_profile = UserTasteProfile()

                global_seen = set()

                mixes = []

                local_tracks = taste_profile.get_local_liked_and_downloaded_tracks(limit=20)
                if local_tracks:
                    local_mix_tracks = []
                    for lt in local_tracks:
                        key = f"{(lt.get('artist') or '').lower()}:{(lt.get('title') or '').lower()}"
                        if key not in global_seen:
                            global_seen.add(key)
                            local_mix_tracks.append(self._format_ui_track(lt))

                    sequenced_local = self._sequence_mix_tracks(local_mix_tracks)
                    if sequenced_local:
                        mixes.append({
                            'type': 'custom_playlist',
                            'title': 'Из лайков и загрузок',
                            'artist': 'AURA Music',
                            'cover_url': sequenced_local[0].get('cover_url') or '',
                            'tracks': sequenced_local,
                        })

                seed_artists = self._get_merged_seed_artists(taste_profile, limit=5)
                for artist in seed_artists[:3]:
                    top_trks = self.lastfm.artist.getTopTracks(artist, limit=8)
                    resolved_mix_tracks = []
                    for tt in top_trks:
                        t_title = tt.get('name', '')
                        t_artist = tt.get('artist', artist)
                        key = f'{t_artist.lower()}:{t_title.lower()}'
                        if key in global_seen:
                            continue

                        resolved = self.resolver.resolve_track(t_title, t_artist)
                        if not resolved:
                            continue
                        if resolved.get('source') not in ('soundcloud', 'youtube', 'local'):
                            continue

                        rkey = f"{(resolved.get('artist') or '').lower()}:{(resolved.get('title') or '').lower()}"
                        if rkey not in global_seen:
                            global_seen.add(rkey)
                            resolved_mix_tracks.append(self._format_ui_track(resolved))

                    sequenced_tracks = self._sequence_mix_tracks(resolved_mix_tracks)
                    if not sequenced_tracks:
                        continue

                    mixes.append({
                        'type': 'custom_playlist',
                        'title': f'Микс: {artist}',
                        'artist': 'AURA Music',
                        'cover_url': sequenced_tracks[0].get('cover_url') or '',
                        'tracks': sequenced_tracks,
                    })

                ctx = self._get_time_of_day_context()
                chart_trks = self.lastfm.chart.getTopTracks(limit=10)
                flow_tracks = []
                for ct in chart_trks:
                    t_title = ct.get('name', '')
                    t_artist = ct.get('artist', '')
                    key = f'{t_artist.lower()}:{t_title.lower()}'
                    if key in global_seen:
                        continue

                    resolved = self.resolver.resolve_track(t_title, t_artist)
                    if not resolved:
                        continue
                    if resolved.get('source') not in ('soundcloud', 'youtube', 'local'):
                        continue

                    rkey = f"{(resolved.get('artist') or '').lower()}:{(resolved.get('title') or '').lower()}"
                    if rkey not in global_seen:
                        global_seen.add(rkey)
                        flow_tracks.append(self._format_ui_track(resolved))

                if flow_tracks:
                    sequenced_flow = self._sequence_mix_tracks(flow_tracks)
                    mixes.append({
                        'type': 'custom_playlist',
                        'title': f'Мой поток: {ctx["title"]}',
                        'artist': 'AURA Music Flow',
                        'cover_url': sequenced_flow[0].get('cover_url') or '',
                        'tracks': sequenced_flow,
                    })

                if callback:
                    callback(mixes[:max_results])
            except Exception as e:
                self.logger.error(f'Error fetching mixes: {e}')
                if error_callback:
                    error_callback(str(e))

        self._executor.submit(_task)

    def get_smart_home_feed(self, history: List[dict] = None, personalization: dict = None, callback: Callable = None, error_callback: Callable = None):
        def _task():
            try:
                if self.db:
                    taste_profile = UserTasteProfile().build_from_db(self.db)
                else:
                    taste_profile = UserTasteProfile()

                ctx = self._get_time_of_day_context()
                time_greeting = ctx['greeting']
                time_title = ctx['title']

                global_seen = set()

                def _resolve_deduped(title, artist):
                    cand_key = f'{artist.lower()}:{title.lower()}'
                    if cand_key in global_seen:
                        return None

                    resolved = self.resolver.resolve_track(title, artist)
                    if not resolved or resolved.get('source') not in ('soundcloud', 'youtube', 'local'):
                        return None

                    rkey = f"{(resolved.get('artist') or '').lower()}:{(resolved.get('title') or '').lower()}"
                    if rkey in global_seen:
                        return None

                    global_seen.add(cand_key)
                    global_seen.add(rkey)
                    return self._format_ui_track(resolved)

                sections = []

                seed_artists = self._get_merged_seed_artists(taste_profile, limit=6)

                contextual_tracks = []
                for artist in seed_artists[:2]:
                    top_trks = self.lastfm.artist.getTopTracks(artist, limit=5)
                    for tt in top_trks:
                        res = _resolve_deduped(tt.get('name', ''), tt.get('artist', artist))
                        if not res:
                            continue
                        contextual_tracks.append(res)

                if not contextual_tracks:
                    chart_trks = self.lastfm.chart.getTopTracks(limit=8)
                    for ct in chart_trks:
                        res = _resolve_deduped(ct.get('name', ''), ct.get('artist', ''))
                        if not res:
                            continue
                        contextual_tracks.append(res)

                sections.append({'title': time_title, 'items': contextual_tracks[:10]})

                mix_items = []

                local_tracks = taste_profile.get_local_liked_and_downloaded_tracks(limit=15)
                if local_tracks:
                    local_mix = []
                    for lt in local_tracks:
                        key = f"{(lt.get('artist') or '').lower()}:{(lt.get('title') or '').lower()}"
                        if key not in global_seen:
                            global_seen.add(key)
                            local_mix.append(self._format_ui_track(lt))

                    if local_mix:
                        seq = self._sequence_mix_tracks(local_mix)
                        mix_items.append({
                            'type': 'custom_playlist',
                            'title': 'Из лайков и загрузок',
                            'artist': 'AURA Music',
                            'cover_url': seq[0].get('cover_url') or '',
                            'source': seq[0].get('source') or 'local',
                            'source_id': seq[0].get('source_id') or '',
                            'source_url': seq[0].get('source_url') or '',
                            'duration': seq[0].get('duration') or 0,
                            'tracks': seq,
                        })

                for artist in seed_artists[:2]:
                    top_trks = self.lastfm.artist.getTopTracks(artist, limit=6)
                    mix_trks = []
                    for tt in top_trks:
                        res = _resolve_deduped(tt.get('name', ''), tt.get('artist', artist))
                        if not res:
                            continue
                        mix_trks.append(res)

                    if not mix_trks:
                        continue

                    seq_mix = self._sequence_mix_tracks(mix_trks)
                    mix_items.append({
                        'type': 'custom_playlist',
                        'title': f'Микс: {artist}',
                        'artist': 'AURA Music',
                        'cover_url': seq_mix[0].get('cover_url') or '',
                        'source': seq_mix[0].get('source') or 'soundcloud',
                        'source_id': seq_mix[0].get('source_id') or '',
                        'source_url': seq_mix[0].get('source_url') or '',
                        'duration': seq_mix[0].get('duration') or 0,
                        'tracks': seq_mix,
                    })

                sections.append({'title': 'Специально для вас', 'items': mix_items})

                release_tracks = []
                if len(seed_artists) > 2:
                    rel_artists = seed_artists[2:4]
                else:
                    rel_artists = seed_artists[:2]

                for artist in rel_artists:
                    top_trks = self.lastfm.artist.getTopTracks(artist, limit=4)
                    for tt in top_trks:
                        res = _resolve_deduped(tt.get('name', ''), tt.get('artist', artist))
                        if not res:
                            continue
                        release_tracks.append(res)

                sections.append({'title': 'Новые релизы', 'items': release_tracks[:10]})

                chart_raw = self.lastfm.chart.getTopTracks(limit=15)
                chart_tracks = []
                for item in chart_raw:
                    res = _resolve_deduped(item.get('name', ''), item.get('artist', ''))
                    if res:
                        chart_tracks.append(res)
                    if len(chart_tracks) >= 10:
                        break

                sections.append({'title': 'Топ-чарты', 'items': chart_tracks[:10]})

                payload = {'greeting': time_greeting, 'sections': sections}

                if callback:
                    callback(payload)
            except Exception as e:
                self.logger.error(f'Error in get_smart_home_feed: {e}')
                if error_callback:
                    error_callback(str(e))

        self._executor.submit(_task)

    def get_authentic_home(self, max_results=5, callback: Optional[Callable] = None, error_callback: Optional[Callable] = None):
        def _on_feed(payload):
            if callback:
                if isinstance(payload, dict) and 'sections' in payload:
                    callback(payload['sections'])
                else:
                    callback(payload)

        self.get_smart_home_feed(history=[], callback=_on_feed, error_callback=error_callback)

    def get_yt_playlist_tracks(self, playlist_id: str, limit: int = 50, callback: Optional[Callable] = None, error_callback: Optional[Callable] = None):
        def _task():
            try:
                chart_raw = self.lastfm.chart.getTopTracks(limit=limit)
                tracks = []
                for item in chart_raw:
                    res = self.resolver.resolve_track(item.get('name', ''), item.get('artist', ''))
                    if not res:
                        continue
                    if res.get('source') not in ('soundcloud', 'youtube', 'local'):
                        continue

                    tracks.append(self._format_ui_track(res))

                if callback:
                    callback(tracks[:limit])
            except Exception as e:
                if error_callback:
                    error_callback(str(e))

        self._executor.submit(_task)

    def get_wave_for_track(self, seed_track: dict, limit: int = 15, exclude_ids: list = None, callback: Optional[Callable] = None, error_callback: Optional[Callable] = None):
        """
        Generate a smart wave / radio of similar tracks based on a seed track.
        Prioritizes:
        1. SoundCloud Related API (fast & high relevance)
        2. Last.fm Similar Tracks API + Track Resolver
        3. Last.fm Similar Artists + Top Tracks
        4. User Taste Profile / Local DB
        """
        if exclude_ids is None:
            exclude_ids = []
        exclude_set = {str(eid).strip().lower() for eid in exclude_ids if eid}

        def _task():
            try:
                results = []
                seen_keys = set()

                seed_id = str(seed_track.get('source_id') or seed_track.get('id') or '')
                seed_artist = str(seed_track.get('artist') or '').strip()
                seed_title = str(seed_track.get('title') or '').strip()
                seed_source = seed_track.get('source') or ''

                if seed_id:
                    exclude_set.add(seed_id.lower())
                if seed_artist and seed_title:
                    seen_keys.add(f"{seed_artist.lower()}:{seed_title.lower()}")

                # 1. Primary: SoundCloud Related API
                if self.sc_service and (seed_source == 'soundcloud' or seed_id.isdigit()):
                    try:
                        sc_related = self.sc_service.get_related_tracks_sync(seed_id, limit=limit + 5)
                        for trk in sc_related:
                            tid = str(trk.get('source_id') or '').lower()
                            t_key = f"{(trk.get('artist') or '').lower()}:{(trk.get('title') or '').lower()}"
                            if tid in exclude_set or t_key in seen_keys:
                                continue
                            seen_keys.add(t_key)
                            results.append(self._format_ui_track(trk))
                            if len(results) >= limit:
                                break
                    except Exception as e:
                        self.logger.warning(f"SoundCloud related tracks retrieval failed: {e}")

                # 2. Secondary: Last.fm similar tracks + TrackResolver
                if len(results) < limit and seed_artist and seed_title and seed_artist != 'Unknown Artist':
                    try:
                        sim_tracks = self.lastfm.track.getSimilar(seed_artist, seed_title, limit=limit)
                        for st in sim_tracks:
                            c_title = st.get('name') or ''
                            c_artist = st.get('artist') or seed_artist
                            t_key = f"{c_artist.lower()}:{c_title.lower()}"
                            if t_key in seen_keys:
                                continue
                            seen_keys.add(t_key)

                            resolved = self.resolver.resolve_track(c_title, c_artist)
                            if resolved and (resolved.get('source_id') or resolved.get('source_url')):
                                tid = str(resolved.get('source_id') or '').lower()
                                if tid not in exclude_set:
                                    results.append(self._format_ui_track(resolved))
                                    if len(results) >= limit:
                                        break
                    except Exception as e:
                        self.logger.warning(f"Last.fm similar tracks retrieval failed: {e}")

                # 3. Tertiary: Last.fm similar artists top tracks
                if len(results) < limit and seed_artist and seed_artist != 'Unknown Artist':
                    try:
                        sim_artists = self.lastfm.artist.getSimilar(seed_artist, limit=5)
                        for sa in sim_artists:
                            sa_name = sa.get('name')
                            if not sa_name:
                                continue
                            top_trks = self.lastfm.artist.getTopTracks(sa_name, limit=3)
                            for tt in top_trks:
                                c_title = tt.get('name') or ''
                                c_artist = tt.get('artist') or sa_name
                                t_key = f"{c_artist.lower()}:{c_title.lower()}"
                                if t_key in seen_keys:
                                    continue
                                seen_keys.add(t_key)

                                resolved = self.resolver.resolve_track(c_title, c_artist)
                                if resolved and (resolved.get('source_id') or resolved.get('source_url')):
                                    tid = str(resolved.get('source_id') or '').lower()
                                    if tid not in exclude_set:
                                        results.append(self._format_ui_track(resolved))
                                        if len(results) >= limit:
                                            break
                            if len(results) >= limit:
                                break
                    except Exception as e:
                        self.logger.warning(f"Last.fm similar artists retrieval failed: {e}")

                # 4. Fallback: Local database / taste profile
                if len(results) < limit and self.db:
                    try:
                        taste = UserTasteProfile().build_from_db(self.db)
                        for hist in taste.recent_history:
                            t_key = f"{(hist.get('artist') or '').lower()}:{(hist.get('title') or '').lower()}"
                            tid = str(hist.get('source_id') or hist.get('id') or '').lower()
                            if t_key not in seen_keys and tid not in exclude_set:
                                seen_keys.add(t_key)
                                results.append(self._format_ui_track(hist))
                                if len(results) >= limit:
                                    break
                    except Exception:
                        pass

                if callback:
                    callback(results[:limit])
                return results[:limit]
            except Exception as e:
                self.logger.error(f"Error in get_wave_for_track: {e}")
                if error_callback:
                    error_callback(str(e))
                return []

        if callback:
            self._executor.submit(_task)
            return None
        return _task()