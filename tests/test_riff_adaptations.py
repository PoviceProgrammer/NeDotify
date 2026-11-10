"""Shared home signals and cache-first downloads adapted from Riff's source."""
from contextlib import contextmanager
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from services.taste_profile import UserTasteProfile
from tests.helpers import recommendations, fetch, track
from tests.audio_helpers import wave_bytes


def test_smart_home_uses_supplied_history_without_lastfm(recommendations):
    seed = track('seed', 'Seed')
    calls = []
    recommendations.youtube_service.get_related_tracks_sync = lambda sid, **kw: calls.append(sid) or [track('new', 'Discovery', 'New Artist')]
    payload = fetch(recommendations.get_smart_home_feed, history=[seed])
    assert calls == ['seed']
    assert any(item.get('title') == 'Discovery' for section in payload['sections'] for item in section['items'])


def test_smart_home_keeps_local_file_and_applies_changed_feedback(recommendations, tmp_path):
    favorite = track('local', 'My favorite', source='local', id=7, file_path=str(tmp_path / 'music.wav'), is_favorite=True)
    profile = UserTasteProfile()
    profile.favorite_tracks = [favorite]
    profile.top_tracks = [favorite]
    recommendations._profile = lambda history=None: profile
    values = {'blocked_artists': [], 'recommendation_mode': 'familiar'}
    recommendations.settings = SimpleNamespace(get=lambda category, key, default=None: values.get(key, default))
    recommendations.resolver.resolve_track = lambda *a, **kw: pytest.fail('A playable local track must not be re-resolved')
    payload = fetch(recommendations.get_smart_home_feed)
    assert any(item.get('file_path') == favorite['file_path'] for section in payload['sections'] for item in section['items'])
    values['blocked_artists'] = ['Artist']
    updated = fetch(recommendations.get_smart_home_feed)
    assert all(item.get('artist') != 'Artist' for section in updated['sections'] for item in section['items'])
    assert all(t.get('artist') != 'Artist' for section in updated['sections'] for item in section['items'] for t in item.get('tracks', []))


def test_network_outage_keeps_available_favorites_in_feed(recommendations):
    recommendations.settings = SimpleNamespace(get=lambda category, key, default=None:
        'familiar' if key == 'recommendation_mode' else default)
    current = track('seed', 'Current')
    favorite = track('local', 'Offline favorite', artist='Local Artist', source='local', id=7, file_path='C:/music/song.wav')
    profile = UserTasteProfile()
    profile.recent_history = [current]
    profile.favorite_tracks = [favorite]
    recommendations._profile = lambda history=None: profile
    recommendations.youtube_service.get_related_tracks_sync = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('Network unavailable'))
    assert fetch(recommendations.get_feed)[0]['file_path'] == favorite['file_path']


def test_disabled_source_is_not_requested_or_returned_from_cache(recommendations):
    seed = track('seed', 'Seed')
    recommendations.youtube_service.get_related_tracks_sync = lambda *a, **kw: [track('new', 'Discovery')]
    assert fetch(recommendations.get_feed, [seed])
    recommendations.settings = SimpleNamespace(get=lambda category, key, default=None: False if key in ('youtube_enabled', 'soundcloud_enabled') else default)
    recommendations.youtube_service.search_sync = lambda *a, **kw: pytest.fail('Disabled YouTube was requested')
    recommendations.youtube_service.get_related_tracks_sync = lambda *a, **kw: pytest.fail('Disabled YouTube was requested')
    assert fetch(recommendations.get_feed, [seed]) == []


def test_complete_audio_cache_is_reused_before_conversion(downloader, tmp_db, core_ns, monkeypatch, redirect_home):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        pytest.skip('Real ffmpeg unavailable')
    from utils.cache_manager import stream_cache_stem
    core_ns.settings.set('downloads', 'format', 'mp3')
    track_id = tmp_db.add_track(title='Cached conversion', source='youtube', source_id='cached')
    folder = redirect_home / '.nedotify' / 'streams'
    folder.mkdir(parents=True)
    cached = folder / (stream_cache_stem('youtube', 'cached') + '.wav')
    cached.write_bytes(wave_bytes())
    monkeypatch.setattr(tmp_db, 'get_cached_stream', lambda *a, **kw: {'cached_file_path': str(cached)})
    core_ns.youtube.download_audio_sync = lambda *a, **kw: pytest.fail('Complete cache should avoid another provider transfer')
    @contextmanager
    def lease(**options):
        assert options['require_yt_dlp'] is False, 'Cached audio must also work without an extractor'
        yield {'ffmpeg_path': ffmpeg, 'yt_dlp_module': True}
    core_ns.setup = SimpleNamespace(acquire_download_tools=lease)
    assert downloader.queue_download(track_id, 'youtube', 'cached')
    downloader._download_worker(downloader._queue.pop(0))
    final = tmp_db.get_track(track_id)
    assert final['is_downloaded']
    assert Path(final['file_path']).suffix == '.mp3'
    assert cached.read_bytes() == wave_bytes()


def test_independent_seed_evidence_gets_bounded_ranking_bonus(recommendations):
    profile = UserTasteProfile()
    single = track('single', 'Single seed', recommendation_relevance=.8, recommendation_seed_artists=['Artist'])
    repeated = track('repeated', 'Repeated same seed', recommendation_relevance=.8, recommendation_seed_artists=['Artist'] * 20)
    consensus = track('consensus', 'Shared favorite', recommendation_relevance=.8, recommendation_seed_artists=['Artist', 'Other Artist'])
    assert recommendations._calculate_taste_weights(single, profile) == recommendations._calculate_taste_weights(repeated, profile)
    assert recommendations._rank_tracks([single, consensus], profile, 1)[0]['source_id'] == 'consensus'


def test_recommendation_playlist_helper_uses_the_actual_playlist_provider(recommendations):
    calls = []
    def playlist(playlist_id, *, limit, callback, error_callback):
        calls.append((playlist_id, limit))
        callback([track('song', 'Playlist song')])
    recommendations.youtube_service.get_playlist_tracks = playlist
    assert fetch(recommendations.get_yt_playlist_tracks, 'PL_example', limit=2)[0]['title'] == 'Playlist song'
    assert calls == [('PL_example', 2)]


def test_metadata_resolution_rechecks_sources_and_keeps_local_library(tmp_db):
    from services.track_resolver import TrackResolver
    states = {'youtube_enabled': True, 'soundcloud_enabled': False}
    settings = SimpleNamespace(get=lambda category, key, default=None: states.get(key, default))
    calls = []
    def search(query, *, max_results, callback, error_callback):
        calls.append(query)
        callback([track('online', 'Song')])
    resolver = TrackResolver(db=tmp_db, settings=settings,
                             youtube_service=SimpleNamespace(search=search))
    assert resolver.resolve_track('Song', 'Artist')['source'] == 'youtube'
    states['youtube_enabled'] = False
    assert resolver.resolve_track('Song', 'Artist')['source'] == 'unknown'
    assert len(calls) == 1
    tid = tmp_db.add_track(title='Local', artist='Artist', source='youtube', source_id='local', file_path='C:/music/local.mp3')
    assert resolver.resolve_track('Local', 'Artist')['id'] == tid


def test_engine_does_not_reuse_disabled_online_source_but_keeps_downloads(tmp_path):
    from audio.engine import AudioEngine
    engine = AudioEngine()
    engine.app_core = SimpleNamespace(settings=SimpleNamespace(get=lambda category, key, default=None:
                                                              False if key == 'youtube_enabled' else default))
    engine._resolve_via_network = lambda *a, **kw: pytest.fail('Disabled source was resolved')
    assert engine.resolve_stream_url(track('online', 'Song')) is None
    path = tmp_path / 'download.wav'
    path.write_bytes(wave_bytes())
    assert engine.resolve_stream_url(track('downloaded', 'Song', file_path=str(path))) == str(path)


def test_deezer_audio_mapping_does_not_construct_disabled_providers():
    from services.deezer_service import DeezerService, DeezerError
    settings = SimpleNamespace(get=lambda category, key, default=None: False if key.endswith('_enabled') else default)
    service = DeezerService(settings=settings, providers=lambda source: pytest.fail('Disabled provider constructed'))
    service.get_track = lambda track_id: track('id', 'Song')
    with pytest.raises(DeezerError):
        list(service._audio_candidates('1'))
