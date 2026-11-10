"""Recommendation controls preserve collection context and correlated bridge results."""
from types import SimpleNamespace

import pytest

from core.bridge import BridgeApi
from services.taste_profile import UserTasteProfile
from tests.helpers import recommendations, track, fetch


def configured(values):
    return SimpleNamespace(get=lambda category, key, default=None: values.get(key, default))


def test_novelty_mode_changes_selection_without_admitting_weak_matches(recommendations):
    values = {'recommendation_mode': 'familiar'}
    recommendations.settings = configured(values)
    profile = UserTasteProfile()
    known = [track(f'known{i}', f'Known {i}', f'Favorite {i % 5}', recommendation_relevance=.8)
             for i in range(10)]
    profile.favorite_tracks = known
    profile.top_artists = [{'name': f'Favorite {i}', 'play_count': 50} for i in range(5)]
    new = [track(f'new{i}', f'New {i}', f'New Artist {i}', recommendation_relevance=.85)
           for i in range(10)]
    weak = track('weak', 'Weak', 'Unrelated', recommendation_relevance=.1)
    familiar = recommendations._rank_tracks(known + new + [weak], profile, 10)
    values['recommendation_mode'] = 'discovery'
    discovery = recommendations._rank_tracks(known + new + [weak], profile, 10)
    assert sum(t['source_id'].startswith('known') for t in familiar) > sum(
        t['source_id'].startswith('known') for t in discovery)
    assert all(t['source_id'] != 'weak' for t in familiar + discovery)


def test_mode_participates_in_feed_cache_identity(recommendations):
    values = {'recommendation_mode': 'familiar'}
    recommendations.settings = configured(values)
    seed = track('dQw4w9WgXcQ', 'Seed')
    recommendations.youtube_service.get_related_tracks_sync = lambda *a, **k: [track('new', 'New')]
    fetch(recommendations.get_feed, [seed])
    first_keys = {k for k in recommendations._search_cache if k.startswith('recommendation:feed:')}
    values['recommendation_mode'] = 'discovery'
    fetch(recommendations.get_feed, [seed])
    keys = {k for k in recommendations._search_cache if k.startswith('recommendation:feed:')}
    assert len(keys - first_keys) == 1


def test_reasons_describe_seed_evidence_and_do_not_invent_similarity(recommendations):
    profile = UserTasteProfile()
    profile.favorite_tracks = [track('liked', 'Liked', 'Loved Artist')]
    candidates = [track('related', 'Related', 'New Artist', recommendation_relevance=.8,
                        recommendation_seed_artists=['loved artist']),
                  track('no-evidence', 'No evidence', 'Other Artist')]
    result = recommendations._rank_tracks(candidates, profile, 5)
    reasons = {t['source_id']: t['recommendation_reason'] for t in result}
    assert reasons['related'] == 'По музыке Loved Artist'
    assert reasons['no-evidence'] == ''


def test_recommended_local_track_preserves_cover_path_for_proxy(recommendations):
    profile = UserTasteProfile()
    local = track('local-1', 'Local', source='local', id=1,
                  file_path='C:/music/local.flac', cover_path='C:/music/local.jpg')
    profile.favorite_tracks = [local]
    result = recommendations._rank_tracks([local], profile, 1)
    assert result[0]['cover_path'] == local['cover_path']


def test_wave_reasons_include_selected_seed_before_history_records_it(recommendations):
    seed = track('dQw4w9WgXcQ', 'Seed', 'Selected Artist')
    recommendations.youtube_service.get_related_tracks_sync = lambda *a, **kw: [
        track('related', 'Related', 'New Artist')]
    result = recommendations.get_wave_for_track(seed)
    assert result[0]['recommendation_reason'] == 'По музыке Selected Artist'


@pytest.mark.parametrize('collection', ['favorites', 7])
def test_collection_suggestions_use_collection_context_and_fresh_exclusions(recommendations, collection):
    rows = [track(f'seed{i}', f'Seed {i}', f'Playlist Artist {i}') for i in range(12)]
    current = list(rows)
    recommendations.db = SimpleNamespace(get_playlist_tracks=lambda pid: current,
        get_favorite_tracks=lambda: current, data_revision=1)
    values = {'blocked_artists': ['Blocked'], 'disliked_tracks': [{'artist': 'Disliked', 'title': 'No'}]}
    recommendations.settings = configured(values)
    observed = []

    def candidates(profile, seeds, artists, limit):
        observed.append((profile, seeds, artists))
        added = track('added-during-request', 'Just added', 'Playlist Artist 0')
        current.append(added)
        return [dict(rows[0], source_id='alternate-upload'), added,
                track('blocked', 'Blocked', 'Blocked'), track('disliked', 'No', 'Disliked'),
                track('valid', 'Suggested', 'New Artist', recommendation_relevance=.9,
                      recommendation_seed_artists=['playlist artist 0'])]

    recommendations._collect_candidates = candidates
    result = fetch(recommendations.get_playlist_recommendations, collection)
    assert [t['source_id'] for t in result] == ['valid']
    assert result[0]['recommendation_origin'] == 'playlist'
    assert result[0]['recommendation_reason'] == 'По музыке Playlist Artist 0'
    profile, seeds, artists = observed[0]
    assert not profile.favorite_tracks and not profile.recent_history
    assert len(seeds) == len({t['artist'] for t in seeds}) == 5
    assert any(int(t['source_id'][4:]) >= 9 for t in seeds), 'sampling reaches the end of a collection'
    assert set(artists) <= {t['artist'] for t in rows}


def test_empty_playlist_does_not_fall_back_to_unrelated_global_taste(recommendations):
    recommendations.db = SimpleNamespace(get_playlist_tracks=lambda pid: [], data_revision=1)
    recommendations._collect_candidates = lambda *a, **kw: pytest.fail('No seeds to discover from')
    assert fetch(recommendations.get_playlist_recommendations, 1) == []


def test_playlist_context_is_not_overridden_by_global_favorite_genres(recommendations):
    seed = track('seed', 'Seed', 'Playlist Artist', genre='Ambient')
    recommendations.settings = configured({'favorite_genres': ['Metal']})
    recommendations.db = SimpleNamespace(get_playlist_tracks=lambda pid: [seed], data_revision=1)
    recommendations._collect_candidates = lambda *a, **kw: [
        track('first', 'First', 'Playlist Artist', recommendation_relevance=.8),
        track('metal', 'Metal', 'Playlist Artist', genre='Metal', recommendation_relevance=.8)]
    result = fetch(recommendations.get_playlist_recommendations, 1, max_results=1)
    assert result[0]['source_id'] == 'first'


def test_playlist_bridge_correlates_favorites_success_and_errors(api, core_ns, emitted):
    def complete(playlist_id, *, max_results, callback, error_callback):
        assert playlist_id == 'favorites' and max_results == 2
        callback([{'source_id': str(i)} for i in range(4)])
    core_ns.recommendations = SimpleNamespace(get_playlist_recommendations=complete)
    bridge = BridgeApi(api)
    assert bridge.get_playlist_recommendations('favorites', 2, 'favorites-request') == {
        'status': 'pending', 'request_id': 'favorites-request'}
    assert emitted == [('playlist_recommendations_ready', {'playlist_id': 'favorites',
        'request_id': 'favorites-request', 'tracks': [{'source_id': '0'}, {'source_id': '1'}]})]
    emitted.clear()
    bridge.get_playlist_recommendations('not-a-playlist', 2, 'bad-request')
    name, payload = emitted[0]
    assert name == 'playlist_recommendations_ready'
    assert payload['playlist_id'] == 'not-a-playlist' and payload['request_id'] == 'bad-request'
    assert payload['tracks'] == [] and payload['error']


def test_collection_completion_keeps_each_request_id_out_of_order(api, core_ns, emitted):
    pending = []
    core_ns.recommendations = SimpleNamespace(get_playlist_recommendations=lambda pid, **kw: pending.append(kw))
    api.get_playlist_recommendations(1, 2, 'old')
    api.get_playlist_recommendations(2, 2, 'new')
    pending[1]['callback']([{'source_id': 'new'}])
    pending[0]['error_callback']('network failure')
    assert [p['request_id'] for _, p in emitted] == ['new', 'old']
    assert [p['playlist_id'] for _, p in emitted] == [2, 1]


def test_recommendation_mode_setting_rejects_unknown_values(api, core_ns):
    assert api.save_setting('recommendation_mode', 'familiar', 'personalization') is True
    assert api.save_setting('recommendation_mode', 'anything', 'personalization') is False
    assert core_ns.settings.get('personalization', 'recommendation_mode') == 'familiar'


def test_suggested_track_with_provider_id_can_be_added_to_local_playlist(api, tmp_db, emitted):
    pid = tmp_db.create_playlist('Suggestions')
    candidate = track('provider-id', 'Suggested', id='yt_provider-id', cover_url='https://example.com/cover.jpg')
    assert api.add_to_playlist(pid, candidate)
    added = tmp_db.get_playlist_tracks(pid)
    assert len(added) == 1 and isinstance(added[0]['id'], int)
    assert added[0]['source_id'] == 'provider-id' and added[0]['cover_url'] == candidate['cover_url']


def test_guarded_wave_append_rejects_replaced_queue_without_mutation(api, core_ns, emitted):
    core_ns.engine.queue.set_tracks([track('seed', 'Seed', entry_id='current')])
    snapshot = api.get_queue()
    assert api.add_tracks_to_queue([track('a', 'Next')], 'current', snapshot['queue_revision'])['success']
    after = api.get_queue()
    assert api.add_tracks_to_queue([track('b', 'Stale')], 'current', snapshot['queue_revision']) == {
        'success': False, 'code': 'stale_queue'}
    assert api.get_queue() == after
    assert api.add_tracks_to_queue([track('b', 'Wrong entry')], 'replaced', after['queue_revision'])['success'] is False


def test_continuous_wave_expands_from_recent_evidenced_seeds_with_anchor_and_shared_filters(recommendations):
    import time
    recommendations.settings = configured({'blocked_artists': ['Blocked'], 'soundcloud_enabled': False,
        'disliked_tracks': [{'artist': 'Disliked', 'title': 'No'}]})
    anchor = track('anchor', 'Anchor', 'Original Artist')
    def generated(sid, artist, **kw):
        return track(sid, sid, artist, recommendation_origin='wave', recommendation_relevance=.9,
                     recommendation_seed_artists=['original artist'], **kw)
    older = generated('older', 'Older Artist')
    first = generated('first', 'First Neighbor')
    second = generated('second', 'Second Neighbor')
    invalid = [generated('blocked', 'Blocked'), generated('off', 'Off', source='soundcloud'),
               dict(generated('no', 'Disliked'), title='No'),
               dict(generated('weak', 'Weak'), recommendation_relevance=.1),
               dict(generated('manual', 'Manual'), recommendation_origin='')]
    calls = []
    def collect(profile, seeds, artists, limit, deadline):
        calls.append((seeds, artists, limit, deadline))
        return [track('anchored', 'Anchored', 'New A', recommendation_relevance=.9,
                      recommendation_seed_artists=['original artist']),
                track('fresh', 'Fresh', 'New B', recommendation_relevance=.9,
                      recommendation_seed_artists=['second neighbor']),
                track('queued', 'Queued', 'New C', recommendation_relevance=.9,
                      recommendation_seed_artists=['original artist']),
                track('unrelated', 'Unrelated', 'New D', recommendation_relevance=.9,
                      recommendation_seed_artists=['outside artist']),
                track('unsupported', 'Unsupported', 'New E', recommendation_relevance=.1,
                      recommendation_seed_artists=['second neighbor']),
                track('block-result', 'Result', 'Blocked', recommendation_relevance=.9,
                      recommendation_seed_artists=['original artist'])]
    recommendations._collect_candidates = collect
    before = time.monotonic()
    result = recommendations.get_wave_for_track(anchor, exclude_ids=['new c:queued'],
        continuation_tracks=[older, first, second] + invalid)
    seeds, artists, limit, deadline = calls[0]
    assert [t['source_id'] for t in seeds] == ['anchor', 'second', 'first']
    assert artists == ['Original Artist'] and limit >= 30
    assert before <= deadline <= time.monotonic() + 12
    assert {t['source_id'] for t in result} == {'anchored', 'fresh'}
    by_id = {t['source_id']: t for t in result}
    assert by_id['anchored']['recommendation_relevance'] > by_id['fresh']['recommendation_relevance']
    assert by_id['fresh']['recommendation_reason'] == 'По музыке Second Neighbor'


def test_wave_bridge_passes_optional_continuation_without_changing_legacy_calls(api, core_ns, emitted):
    calls = []
    core_ns.recommendations = SimpleNamespace(get_wave_for_track=lambda seed, **kw: calls.append(kw))
    seed = track('seed', 'Seed')
    continuation = dict(track('next', 'Next'), recommendation_origin='wave', recommendation_relevance=.9,
                        recommendation_seed_artists=['artist'])
    api.get_track_wave(seed, 15, [], 'continuation', [continuation])
    assert calls[0]['continuation_tracks'] == [continuation]
    api.get_track_wave(seed, 15, [], 'legacy')
    assert 'continuation_tracks' not in calls[1]


def test_exhausted_anchor_pool_can_discover_fresh_tracks_through_played_neighbor(recommendations):
    anchor = track('dQw4w9WgXcQ', 'Anchor', 'Original Artist')
    first = track('a' * 11, 'First neighbor', 'First Artist')
    second = track('b' * 11, 'Fresh discovery', 'Second Artist')
    calls = []
    def related(sid, **kw):
        calls.append(sid)
        return [first] if sid == anchor['source_id'] else [second] if sid == first['source_id'] else []
    recommendations.youtube_service.get_related_tracks_sync = related
    initial = recommendations.get_wave_for_track(anchor)
    assert [t['source_id'] for t in initial] == [first['source_id']]
    assert recommendations.get_wave_for_track(anchor, exclude_ids=[first['source_id']]) == []
    continued = recommendations.get_wave_for_track(anchor, exclude_ids=[first['source_id']],
        continuation_tracks=initial)
    assert [t['source_id'] for t in continued] == [second['source_id']]
    assert first['source_id'] in calls, 'a played related track supplies fresh provider candidates'
