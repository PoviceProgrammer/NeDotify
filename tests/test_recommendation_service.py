"""Personalized recommendations work without API keys and retain playable identity."""
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from services.base_service import BaseMusicService
from services.recommendation_service import RecommendationService
from services.taste_profile import UserTasteProfile


def track(sid, title, artist='Artist', source='youtube', **kwargs):
    return dict(source=source, source_id=sid, title=title, artist=artist, duration=180, **kwargs)


@pytest.fixture
def recommendations(monkeypatch):
    import services.recommendation_service as module
    monkeypatch.delenv('LASTFM_USERNAME', raising=False)
    def unexpected(*args, **kwargs):
        raise AssertionError('Last.fm must not be needed without a configured key')
    lastfm = SimpleNamespace(_resolve_api_keys=lambda: [],
                             artist=SimpleNamespace(getTopTracks=unexpected),
                             track=SimpleNamespace(getSimilar=unexpected))
    monkeypatch.setattr(module, 'LastFMService', lambda **kwargs: lastfm)
    with BaseMusicService._cache_lock:
        monkeypatch.setattr(BaseMusicService, '_search_cache', {})
    executor = ThreadPoolExecutor(max_workers=4)
    monkeypatch.setattr(RecommendationService, '_executor', executor)
    yt = SimpleNamespace(get_related_tracks_sync=lambda *a, **k: [],
                         search_sync=lambda *a, **k: [])
    sc = SimpleNamespace(get_related_tracks_sync=lambda *a, **k: [])
    service = RecommendationService(youtube_service=yt, soundcloud_service=sc)
    yield service
    executor.shutdown(wait=True)
    service._candidate_executor.shutdown(wait=True)


def fetch(method, *args, **kwargs):
    event, result = threading.Event(), {}
    method(*args, callback=lambda data: (result.update(data=data), event.set()),
           error_callback=lambda error: (result.update(error=error), event.set()), **kwargs)
    assert event.wait(3), 'Recommendation callback did not complete'
    assert 'error' not in result, result
    return result['data']


def test_feed_uses_history_related_tracks_without_lastfm_key(recommendations):
    seed = track('dQw4w9WgXcQ', 'Seed')
    calls = []
    def related(sid, **kwargs):
        calls.append(sid)
        return [seed, track('a' * 11, 'Discovery', 'Similar Artist'),
                track('b' * 11, 'Discovery (Official Audio)', 'similar artist'),
                track('', 'Broken', source='unknown')]
    recommendations.youtube_service.get_related_tracks_sync = related
    result = fetch(recommendations.get_feed, [seed], max_results=3)
    assert calls == ['dQw4w9WgXcQ']
    assert [t['title'] for t in result] == ['Discovery']
    assert result[0]['source_id'] == 'a' * 11


def test_local_tracks_keep_id_and_file_path_even_offline(recommendations, tmp_path):
    # Library fallback is an explicit familiar-mode choice. The default feed
    # now reserves its results for discoveries outside the saved library.
    recommendations.settings = SimpleNamespace(get=lambda category, key, default=None:
        'familiar' if key == 'recommendation_mode' else default)
    audio = tmp_path / 'liked.mp3'
    audio.write_bytes(b'audio')
    favorite = track('17', 'Local favorite', source='local', id=17,
                     file_path=str(audio), is_favorite=True, is_downloaded=True)
    current = track('c' * 11, 'Current', 'Other Artist')
    profile = UserTasteProfile()
    profile.favorite_tracks = [favorite]
    profile.top_tracks = [favorite]
    profile.recent_history = [current]
    recommendations._profile = lambda history=None: profile
    feed = fetch(recommendations.get_feed, max_results=5)
    assert feed[0]['id'] == 17 and feed[0]['file_path'] == str(audio)
    mixes = fetch(recommendations.get_mixes)
    assert any(t['file_path'] == str(audio) for mix in mixes for t in mix['tracks'])


def test_ranking_balances_artists_and_new_tracks(recommendations):
    profile = UserTasteProfile()
    profile.top_artists = [{'name': 'Artist', 'play_count': 30}]
    known = [track(str(i), f'Known {i}') for i in range(8)]
    profile.favorite_tracks = known
    candidates = known + [track(f'new{i}', f'New {i}', f'Artist {i % 3}') for i in range(9)]
    result = recommendations._rank_tracks(candidates, profile, 10)
    assert len(result) == 10
    assert sum(t['title'].startswith('Known') for t in result) <= 3
    assert len({t['artist'] for t in result}) >= 4


def test_measured_skip_does_not_outrank_another_candidate(recommendations):
    profile = UserTasteProfile()
    skipped = track('skip', 'Skipped', duration_listened=2, completed=0)
    profile.recent_history = [skipped]
    result = recommendations._rank_tracks([skipped, track('new', 'New')], profile, 1)
    assert result[0]['title'] == 'New'


def test_wave_excludes_seed_versions_and_both_database_and_provider_queue_ids(recommendations):
    seed = track('dQw4w9WgXcQ', 'Seed', id=42)
    recommendations.youtube_service.get_related_tracks_sync = lambda *a, **k: [
        seed, track('alternate', 'Seed (Official Video)', 'artist'),
        track('queued-a', 'Queue by database', id=77),
        track('queued-b', 'Queue by provider', id=78),
        track('valid', 'New Track', 'Similar Artist'),
        track('duplicate', 'New Track', 'similar artist')]
    result = recommendations.get_wave_for_track(seed, limit=10, exclude_ids=['77', 'queued-b'])
    assert [t['source_id'] for t in result] == ['valid']


def test_content_exclusions_are_applied_before_wave_limit(recommendations):
    seed = track('dQw4w9WgXcQ', 'Seed')
    recommendations.youtube_service.get_related_tracks_sync = lambda *a, **k: [
        track('new-provider-id', 'Already queued'), track('valid', 'Discovery')]
    result = recommendations.get_wave_for_track(seed, limit=1, exclude_ids=['artist:already queued'])
    assert [t['source_id'] for t in result] == ['valid']


def test_provider_candidates_use_current_library_favorite_and_download_identity(recommendations):
    profile = UserTasteProfile()
    candidate = track('online-id', 'Favorite', is_favorite=False)
    favorite = track('online-id', 'Favorite', id=17, file_path='C:/music/favorite.webm',
                     is_favorite=True, is_downloaded=True)
    profile.favorite_tracks = [favorite]
    result = recommendations._rank_tracks([candidate, favorite], profile, 1)
    assert len(result) == 1
    assert result[0]['id'] == 17 and result[0]['is_favorite']
    assert result[0]['is_downloaded'] and result[0]['file_path'] == favorite['file_path']


def test_home_feed_and_mixes_share_candidate_fetches(recommendations):
    seed = track('dQw4w9WgXcQ', 'Seed')
    started, release = threading.Event(), threading.Event()
    calls, searches = [], []
    def related(sid, **kwargs):
        calls.append(sid)
        started.set()
        assert release.wait(2)
        return [track('new', 'Discovery', 'Similar Artist')]
    recommendations.youtube_service.get_related_tracks_sync = related
    recommendations.youtube_service.search_sync = lambda query, **kwargs: searches.append(query) or []
    complete = [threading.Event(), threading.Event()]
    recommendations.get_feed([seed], callback=lambda result: complete[0].set())
    assert started.wait(1)
    recommendations.get_mixes([seed], callback=lambda result: complete[1].set())
    release.set()
    assert all(event.wait(2) for event in complete)
    assert calls == ['dQw4w9WgXcQ']
    assert searches == ['Artist']


def test_provider_failure_is_reported_and_transient_failure_cache_expires(recommendations):
    seed = track('dQw4w9WgXcQ', 'Seed')
    def failure(*args, **kwargs):
        raise RuntimeError('Network unavailable')
    recommendations.youtube_service.get_related_tracks_sync = failure

    event, result = threading.Event(), {}
    recommendations.get_feed([seed], callback=lambda data: (result.update(data=data), event.set()),
                             error_callback=lambda error: (result.update(error=error), event.set()))
    assert event.wait(3), 'Recommendation callback did not complete'
    assert 'Network unavailable' in result.get('error', '')
    assert 'data' not in result

    # An outage is briefly negative-cached to protect home reloads from a
    # repeated provider fan-out. Once that short cooldown expires, retry.
    with BaseMusicService._cache_lock:
        for entry in recommendations._search_cache.values():
            if isinstance(entry.get('data'), dict) and entry['data'].get('error'):
                entry['ts'] -= 300
    recommendations.youtube_service.get_related_tracks_sync = lambda *a, **k: [track('new', 'Recovered')]
    assert fetch(recommendations.get_feed, [seed])[0]['title'] == 'Recovered'


def test_slow_scrobble_lookup_does_not_block_local_seeds(recommendations):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    calls = []
    def top_artists(username, **kwargs):
        calls.append(username)
        started.set()
        try:
            assert release.wait(2)
            return [{'name': 'Scrobbled Artist'}]
        finally:
            finished.set()
    recommendations.settings = SimpleNamespace(get=lambda category, key, default=None:
                                               'username' if key == 'lastfm_username' else True if key == 'lastfm_enabled' else default)
    recommendations.lastfm._resolve_api_keys = lambda: ['configured']
    recommendations.lastfm.user = SimpleNamespace(getTopArtists=top_artists)
    profile = UserTasteProfile()
    try:
        assert recommendations._get_merged_seed_artists(profile, limit=3)
        assert started.wait(1)
        assert recommendations._get_merged_seed_artists(profile, limit=3)
        assert calls == ['username']
    finally:
        release.set()
    assert finished.wait(1)
    recommendations._candidate_executor.shutdown(wait=True)
    assert recommendations._get_merged_seed_artists(profile, limit=3)[0] == 'Scrobbled Artist'


def test_empty_profile_has_real_playable_welcome_tracks_and_zero_limit_is_offline(recommendations):
    assert fetch(recommendations.get_feed, max_results=0) == []
    result = fetch(recommendations.get_feed, max_results=3)
    assert len(result) == 3
    assert all(t['source'] == 'youtube' and len(t['source_id']) == 11 for t in result)
    assert not any(t['title'].startswith('Popular Track') for t in result)


@pytest.mark.parametrize('duration', ['invalid', float('nan'), float('inf'), -2, None])
def test_recommendation_durations_are_serializable_and_nonnegative(recommendations, duration):
    candidate = track('id', 'Track')
    candidate['duration'] = duration
    assert recommendations._format_ui_track(candidate)['duration'] == 0


def test_daily_artist_plans_keep_multiple_artists_and_are_stable(recommendations, monkeypatch):
    profile=UserTasteProfile();profile.top_artists=[{'name':f'Artist {i}','play_count':20-i} for i in range(12)]
    monkeypatch.setattr(recommendations,'_get_merged_seed_artists',lambda *a,**k:[row['name'] for row in profile.top_artists])
    buckets=recommendations._daily_artist_buckets(profile)
    assert buckets==recommendations._daily_artist_buckets(profile)
    assert len(buckets)==5 and all(len(group)>=2 for group in buckets)
    assert len({name for group in buckets for name in group})==12


def test_known_playlist_tracks_are_never_labelled_as_discoveries(recommendations, monkeypatch):
    profile = UserTasteProfile()
    known = [track('saved-a', 'Saved A', 'Artist A'), track('saved-b', 'Saved B', 'Artist B')]
    profile.playlist_tracks = known
    profile.top_tracks = known
    profile.top_artists = [{'name':'Artist A','play_count':5},{'name':'Artist B','play_count':4}]
    monkeypatch.setattr(recommendations, '_profile', lambda history=None: profile)
    recommendations.youtube_service.search_sync = lambda *args, **kwargs: known
    recommendations.youtube_service.get_related_tracks_sync = lambda *args, **kwargs: known
    mixes = fetch(recommendations.get_mixes)
    assert not any(mix['title'] == 'Открытия для вас' for mix in mixes), 'replaying the saved playlist is not discovery'
    assert not any(mix['title'].startswith('Ежедневный микс') for mix in mixes), 'known-only playlists must not masquerade as generated daily discovery'


def test_imported_playlist_seeds_reach_real_related_discovery_without_api_keys(recommendations, monkeypatch):
    profile = UserTasteProfile()
    known = [track('ytsearch1: Artist A - Saved A', 'Saved A', 'Artist A', source='spotify'),
             track('ytsearch1: Artist B - Saved B', 'Saved B', 'Artist B', source='spotify')]
    profile.playlist_tracks = known
    profile.top_tracks = known
    profile.top_artists = [{'name':'Artist A','play_count':5},{'name':'Artist B','play_count':4}]
    monkeypatch.setattr(recommendations, '_profile', lambda history=None: profile)
    related_calls = []
    def search(query, **kwargs):
        for index, saved in enumerate(known):
            if saved['title'] in query and saved['artist'] in query:
                return [track('native-seed-' + str(index), saved['title'], saved['artist'])]
        return known
    def related(sid, **kwargs):
        related_calls.append(sid)
        return [track('new-' + sid, 'Unheard ' + sid, 'Artist A')]
    recommendations.youtube_service.search_sync = search
    recommendations.youtube_service.search = lambda query, callback, **kwargs: callback(search(query))
    recommendations.sc_service.search = lambda query, callback, **kwargs: callback([])
    recommendations.youtube_service.get_related_tracks_sync = related
    mixes = fetch(recommendations.get_mixes)
    discoveries = next((mix['tracks'] for mix in mixes if mix['title'] == 'Открытия для вас'), [])
    assert discoveries, 'imported playlist seeds must reach provider-related discovery, not only replay the playlist'
    assert all(t['source_id'].startswith('new-native-seed-') for t in discoveries)
    assert related_calls and all(sid.startswith('native-seed-') for sid in related_calls)


def test_daily_mix_keeps_related_artist_provenance_and_new_cover_tracks(recommendations, monkeypatch):
    profile = UserTasteProfile()
    known = [track('saved-' + str(i), 'Saved ' + str(i), 'Artist ' + str(i)) for i in range(6)]
    profile.playlist_tracks = known
    profile.top_tracks = known
    profile.top_artists = [{'name':t['artist'],'play_count':20-i} for i,t in enumerate(known)]
    monkeypatch.setattr(recommendations, '_profile', lambda history=None: profile)
    recommendations.youtube_service.search_sync = lambda *args, **kwargs: known
    recommendations.youtube_service.get_related_tracks_sync = lambda sid, **kwargs: [
        track('new-' + sid, 'New ' + sid, 'Related ' + sid)]
    mixes = fetch(recommendations.get_mixes)
    daily = [mix for mix in mixes if mix['title'].startswith('Ежедневный микс')]
    assert daily, 'related songs must populate actual daily buckets'
    for mix in daily:
        assert mix['tracks'][0]['source_id'].startswith('new-'), 'the cover/queue must start with real unheard material'
        assert any(track['recommendation_seed_artists'] for track in mix['tracks']), 'related-artist provenance must survive grouping'


def test_discoveries_exclude_credited_reupload_but_preserve_versions_and_other_artists(recommendations, monkeypatch):
    known = track('141', 'G Sound - На душе', 'Uploader 141', source='soundcloud')
    profile = UserTasteProfile()
    profile.playlist_tracks = [known]
    profile.top_tracks = [known]
    monkeypatch.setattr(recommendations, '_profile', lambda history=None: profile)
    recommendations.sc_service.get_track_metadata = lambda sid: dict(known)
    recommendations.sc_service.get_related_tracks_sync = lambda *args, **kwargs: [
        track('same-composition', 'На душе', 'G Sound'),
        track('genuine-remix', 'На душе (Club Remix)', 'G Sound'),
        track('different-artist', 'На душе', 'Other Artist')]
    mixes = fetch(recommendations.get_mixes)
    discoveries = next(mix['tracks'] for mix in mixes if mix['title'] == 'Открытия для вас')
    ids = {t['source_id'] for t in discoveries}
    assert 'same-composition' not in ids, 'a credited cross-source reupload is already known'
    assert {'genuine-remix','different-artist'} <= ids, 'versions and genuine different credits stay distinct'


@pytest.mark.parametrize('metadata,allowed', [
    ({'title': 'FELLOWSHIP WITH THE HOLY SPIRIT/POWERFUL TESTIMONY',
      'artist': 'QUEEN BELEMZY MINISTRIES', 'duration': 6896.118}, False),
    ({'title': 'Blinding Lights', 'artist': 'The Weeknd', 'duration': 6896}, False),
    ({'title': 'Blinding Lights', 'artist': 'The Weeknd', 'duration': 200}, True),
    ({'title': 'The Weeknd - Blinding Lights', 'artist': 'Reuploader', 'duration': 201}, True),
    ({'title': 'Blinding Lights', 'artist': 'Reuploader', 'duration': 200}, True),
    ({'title': 'Blinding Lights (Remix)', 'artist': 'The Weeknd', 'duration': 200}, False),
    ({}, False),
])
def test_soundcloud_seed_identity_is_checked_before_related_graph(recommendations, metadata, allowed):
    seed = track('715124080', 'Blinding Lights', 'The Weeknd', source='soundcloud')
    seed['duration'] = 200
    calls = []
    recommendations.sc_service.get_track_metadata = lambda sid: dict(metadata)
    recommendations.sc_service.get_related_tracks_sync = lambda sid, **kwargs: (
        calls.append(sid) or [track('related', 'Actual related song')])
    recommendations._radio_seed_resolver.resolve_tracks = lambda *args, **kwargs: []
    result = recommendations._collect_uncached_candidates([seed], [], 10)
    assert bool(calls) is allowed, 'an unrelated stored ID must never supply recommendation evidence'
    assert bool(result) is allowed


def test_wrong_soundcloud_seed_can_recover_verified_catalogue_radio(recommendations):
    seed = track('715124080', 'Blinding Lights', 'The Weeknd', source='soundcloud')
    recommendations.sc_service.get_track_metadata = lambda sid: {'title': 'Other recording', 'duration': 6896}
    recommendations.sc_service.get_related_tracks_sync = lambda *args, **kwargs: pytest.fail('wrong graph queried')
    recommendations._radio_seed_resolver.resolve_tracks = lambda *args, **kwargs: [
        track('correct-video', 'Blinding Lights', 'The Weeknd')]
    recommendations.youtube_service.get_related_tracks_sync = lambda sid, **kwargs: [track('new', 'New music')]
    result = recommendations._collect_uncached_candidates([seed], [], 10)
    assert [row['source_id'] for row in result] == ['new']


def test_daily_cover_prefix_does_not_pull_familiar_tracks_between_new_tracks(recommendations, monkeypatch):
    profile = UserTasteProfile()
    known = [track('a','Saved A','Artist A'),track('b','Saved B','Artist B')]
    profile.playlist_tracks = known
    profile.top_tracks = known
    profile.top_artists = [{'name':'Artist A','play_count':5},{'name':'Artist B','play_count':4}]
    monkeypatch.setattr(recommendations,'_profile',lambda history=None:profile)
    recommendations.youtube_service.get_related_tracks_sync = lambda sid, **kwargs: (
        [track('new-'+str(i),'Unheard '+str(i),'Related Artist') for i in range(4)] if sid=='a' else [])
    mixes = fetch(recommendations.get_mixes)
    daily = next(mix for mix in mixes if mix['title'].startswith('Ежедневный микс'))
    assert all(t['source_id'].startswith('new-') for t in daily['tracks'][:4]), 'all four covers must show available unheard recordings'


def test_cached_catalogue_discovery_honors_deezer_and_audio_optouts(recommendations, monkeypatch):
    values = {'deezer_enabled':True,'youtube_enabled':True,'soundcloud_enabled':True}
    recommendations.settings = SimpleNamespace(get=lambda category,key,default=None:values.get(key,default))
    known = track('saved','Saved','Artist')
    profile = UserTasteProfile()
    profile.top_tracks = [known]
    monkeypatch.setattr(recommendations,'_profile',lambda history=None:profile)
    recommendations._discovery = SimpleNamespace(get_candidates=lambda *args,**kwargs:[
        track('123','Catalogue discovery','Related Artist',source='deezer',
              recommendation_source='deezer_radio',recommendation_relevance=.75,
              recommendation_seed_artists=['artist'])])
    assert any(t['source']=='deezer' for t in fetch(recommendations.get_feed))
    values['deezer_enabled'] = False
    assert not any(t['source']=='deezer' for t in fetch(recommendations.get_feed))
    values.update(deezer_enabled=True,youtube_enabled=False,soundcloud_enabled=False)
    assert not fetch(recommendations.get_feed), 'catalogue rows need an enabled full-audio source'


def test_full_known_identity_snapshot_excludes_saved_tracks_beyond_taste_payload_limit(recommendations, monkeypatch):
    import sqlite3
    import services.taste_profile as taste
    monkeypatch.setattr(taste,'HISTORY_LIMIT',2)
    db = sqlite3.connect(':memory:')
    try:
        db.executescript('''
            CREATE TABLE tracks(id INTEGER PRIMARY KEY,title TEXT,artist TEXT,source TEXT,source_id TEXT);
            CREATE TABLE playlist_tracks(playlist_id INTEGER,track_id INTEGER);
        ''')
        for index in range(5):
            db.execute('INSERT INTO tracks VALUES(?,?,?,?,?)',(index+1,'Saved '+str(index),'Artist','youtube','saved-'+str(index)))
            db.execute('INSERT INTO playlist_tracks VALUES(1,?)',(index+1,))
        profile = UserTasteProfile().build_from_db(db)
        assert len(profile.playlist_tracks)==2
        assert recommendations._content_key(track('saved-4','Saved 4','Artist')) in recommendations._known_content_keys(profile)
        monkeypatch.setattr(recommendations,'_profile',lambda history=None:profile)
        recommendations.youtube_service.get_related_tracks_sync = lambda *args,**kwargs:[track('reupload','Saved 4','Artist')]
        mixes = fetch(recommendations.get_mixes)
        assert not any(mix['title']=='Открытия для вас' for mix in mixes), 'payload truncation cannot make a saved song new'
    finally:
        db.close()
