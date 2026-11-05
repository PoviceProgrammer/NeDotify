"""Source quality, discovery, explicit negative feedback, aliases and genre signals."""
from types import SimpleNamespace

from services.taste_profile import UserTasteProfile
from tests.helpers import recommendations, track, fetch


def configured(values):
    return SimpleNamespace(get=lambda category, key, default=None: values.get(key, default))


def test_radio_order_contributes_song_quality(recommendations):
    seed = track('dQw4w9WgXcQ', 'Seed')
    recommendations.youtube_service.get_related_tracks_sync = lambda *a, **k: [
        track('first', 'First'), track('second', 'Second'), track('third', 'Third')]
    result = recommendations.get_wave_for_track(seed)
    assert result[0]['recommendation_relevance'] > result[1]['recommendation_relevance'] > result[2]['recommendation_relevance']
    assert result[0]['recommendation_source'] == 'youtube_radio'


def test_lastfm_match_survives_resolution_and_changes_ranking(recommendations):
    recommendations.settings = configured({'lastfm_enabled': True})
    seed = track('dQw4w9WgXcQ', 'Seed')
    recommendations.lastfm._resolve_api_keys = lambda: ['configured']
    recommendations.lastfm.track.getSimilar = lambda *a, **k: [
        # Both clear eligibility; this test compares their ordering. Below-
        # threshold candidates are covered by the sparse-pool regression.
        {'name': 'Weak', 'artist': 'Artist', 'match': .3},
        {'name': 'Strong', 'artist': 'Artist', 'match': .95}]
    recommendations.resolver.resolve_tracks = lambda pairs, **k: [track(title, title, artist) for title, artist in pairs]
    result = recommendations.get_wave_for_track(seed, limit=2)
    assert [t['title'] for t in result] == ['Strong', 'Weak']
    assert result[0]['recommendation_source'] == 'lastfm_similar'


def test_stronger_metadata_evidence_enriches_existing_playable_result(recommendations):
    recommendations.settings = configured({'lastfm_enabled': True})
    recommendations.lastfm._resolve_api_keys = lambda: ['configured']
    recommendations.lastfm.track.getSimilar = lambda *a, **k: [{'name': 'Exact', 'artist': 'Artist', 'match': .95}]
    recommendations.youtube_service.search_sync = lambda *a, **k: [track('ready-id', 'Exact')]
    recommendations.resolver.resolve_tracks = lambda *a, **k: (_ for _ in ()).throw(AssertionError('Already playable'))
    result = recommendations.get_wave_for_track(track('dQw4w9WgXcQ', 'Seed'), limit=1)
    assert result[0]['source_id'] == 'ready-id'
    assert result[0]['recommendation_source'] == 'lastfm_similar'
    assert result[0]['recommendation_relevance'] > .9


def test_new_artist_exploration_has_places_without_promoting_weak_search_hits(recommendations):
    profile = UserTasteProfile()
    profile.top_artists = [{'name': 'Artist', 'play_count': 100}]
    known = [track(str(i), f'Known {i}', recommendation_relevance=.95) for i in range(10)]
    discoveries = [track(f'new{i}', f'New {i}', f'New Artist {i}', recommendation_relevance=.85) for i in range(3)]
    weak = track('weak', 'Unrelated', 'Random Artist', recommendation_relevance=.1)
    result = recommendations._rank_tracks(known + discoveries + [weak], profile, 10)
    assert len(result) == 10
    assert sum(t['artist'].startswith('New Artist') for t in result) >= 2
    assert 'Unrelated' not in [t['title'] for t in result]


def test_sparse_candidate_pool_never_backfills_weak_discovery_but_keeps_strong_exploration(recommendations):
    profile = UserTasteProfile()
    profile.top_artists = [{'name':'PHARAOH','play_count':100}]
    # Content is irrelevant to this boundary: a weak provider match must not
    # become eligible merely because fewer candidates were available.
    candidate = track('1582443743', 'I AM GREAT, TO PEOPLE WHO LOVE GOD O.',
                      'QUEEN BELEMZY MINISTRIES - SCHOOL OF POWER', source='soundcloud',
                      recommendation_source='soundcloud_related',
                      recommendation_seed_artists=['pharaoh'])
    weak = dict(candidate, recommendation_relevance=.1)
    strong = dict(candidate, recommendation_relevance=.9)
    assert recommendations._rank_tracks([weak],profile,12) == []
    result = recommendations._rank_tracks([strong],profile,12)
    assert [item['source_id'] for item in result] == ['1582443743'], 'strong exploration remains eligible without invented semantic exclusions'


def test_real_genre_match_is_a_soft_bonus_missing_genre_is_neutral(recommendations):
    profile = UserTasteProfile()
    profile.genre_distribution = {'Rock': .8, 'Pop': .2}
    candidates = [track('none', 'Unknown genre'), track('pop', 'Pop', genre='pop'), track('rock', 'Rock', genre='rock')]
    result = recommendations._rank_tracks(candidates, profile, 3)
    assert [t['source_id'] for t in result] == ['rock', 'pop', 'none']


def test_explicit_feedback_filters_all_aliases_versions_and_cached_feeds(recommendations):
    values = {'blocked_artists': [], 'disliked_tracks': []}
    recommendations.settings = configured(values)
    seed = track('dQw4w9WgXcQ', 'Seed', 'Other')
    recommendations.youtube_service.get_related_tracks_sync = lambda *a, **k: [
        track('blocked', 'Song', 'Фараон'), track('valid', 'Another', 'Other')]
    assert any(t['source_id'] == 'blocked' for t in fetch(recommendations.get_feed, [seed]))
    values['blocked_artists'] = ['PHARAOH']
    assert all(t['source_id'] != 'blocked' for t in fetch(recommendations.get_feed, [seed]))
    values['blocked_artists'] = []
    values['disliked_tracks'] = [{'artist': 'PHARAOH', 'title': 'Song (Official Audio)'}]
    assert all(t['source_id'] != 'blocked' for t in fetch(recommendations.get_feed, [seed]))


def test_profile_aliases_merge_artist_scores_and_soft_artist_limits(recommendations, tmp_db):
    one = tmp_db.add_track(title='One', artist='Фараон', source='youtube', source_id='1')
    two = tmp_db.add_track(title='Two', artist='PHARAOH', source='youtube', source_id='2')
    tmp_db.toggle_favorite(one)
    tmp_db.toggle_favorite(two)
    profile = UserTasteProfile().build_from_db(tmp_db)
    assert len(profile.top_artists) == 1 and profile.top_artists[0]['play_count'] == 6
    candidates = [track(str(i), f'Song{i}', 'Фараон' if i % 2 else 'PHARAOH') for i in range(8)]
    candidates += [track(f'o{i}', f'Other{i}', f'Other{i}') for i in range(8)]
    result = recommendations._rank_tracks(candidates, profile, 10)
    assert sum(t['artist'] in ('Фараон', 'PHARAOH') for t in result) <= 2


def test_feedback_bridge_is_reversible_and_does_not_change_library(api, tmp_db):
    tid = tmp_db.add_track(title='Song', artist='PHARAOH', source='youtube', source_id='id')
    candidate = tmp_db.get_track(tid)
    assert api.set_recommendation_feedback(candidate, 'artist')['artist'] is True
    assert api.get_recommendation_feedback({'artist': 'Фараон', 'title': 'Song'})['artist'] is True
    assert api.set_recommendation_feedback(candidate, 'artist', False)['artist'] is False
    assert api.set_recommendation_feedback(candidate, 'track')['track'] is True
    variant = dict(candidate, title='Song (Official Video)', artist='Фараон')
    assert api.get_recommendation_feedback(variant)['track'] is True
    assert api.set_recommendation_feedback(variant, 'track', False)['track'] is False
    assert tmp_db.get_track(tid)['is_favorite'] == 0
    assert tmp_db.get_track(tid)['title'] == 'Song'


def test_manual_alias_configuration_rejects_cycles(api):
    assert api.set_artist_alias('Alias', 'Canonical')['success']
    assert api.set_artist_alias('Canonical', 'Alias')['success'] is False
