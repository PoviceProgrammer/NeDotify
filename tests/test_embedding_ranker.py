import hashlib
import json

import numpy as np
import pytest

from services.embedding_catalog import ENCODER, EmbeddingCatalog
from services.embedding_ranker import (
    HISTORY_MINUTES,
    AudioDiscoveryRanker,
    ProfileEvent,
    blend_order,
    build_profile,
    replay_profile,
)
from services.recommendation_mlp import SCALAR_FEATURES, model_shapes
from tests.helpers import fetch, recommendations, track


def catalog_with_axes(count):
    return EmbeddingCatalog('test-v1', [dict(recording_id=str(i), vector_index=i) for i in range(count)],
                            np.eye(count, 512, dtype=np.float16))


def test_catalog_requires_a_unique_recording_and_keeps_versions_distinct():
    rows = [dict(recording_id='a', title='Song', artist='Artist', duration=180, isrc='FRXX11100001'),
            dict(recording_id='b', title='Song', artist='Artist', duration=181, mbid='b'),
            dict(recording_id='live', title='Song (Live)', artist='Artist', duration=180)]
    catalog = EmbeddingCatalog('one', rows)
    assert catalog.match(dict(title='Song', artist='Artist', duration=180)) is None
    assert catalog.match(dict(title='Song (Live)', artist='Artist', duration=180)).id == 'live'
    assert catalog.match(dict(metadata_json='{"isrc":"FR-XX1-11-00001"}')).id == 'a'
    assert catalog.match(dict(mbid='b', isrc='FRXX11100001')) is None


def test_profile_preserves_likes_and_orders_minute_ties_after_catalog_filter():
    minute = 2 * HISTORY_MINUTES
    events = [ProfileEvent('0', minute - HISTORY_MINUTES, 1, 'old', 2),
              ProfileEvent('0', minute, 2, 'current', 1)]
    events.extend(ProfileEvent(str(i), minute, i + 2, 'current', 1) for i in range(1, 110))
    events.extend([ProfileEvent('0', minute, 112, 'current', 1),
                   ProfileEvent('local', minute, 113, 'current', 2)])
    catalog = catalog_with_axes(110)
    params = dict(evaluation_timestamp_min=minute, session_id='current', event_seq_id=113)
    profile = build_profile(events, catalog, **params)
    assert [row[0] for row in profile.long] == ['0', *map(str, range(109, 10, -1))]
    assert [row[0] for row in profile.short] == ['0', *map(str, range(109, 100, -1))]
    assert profile.long[0] == ('0', minute, 112, 2)
    assert profile.short[0] == ('0', minute, 112, 1)
    assert build_profile(reversed(events), catalog, **params).state_hash() == profile.state_hash()
    assert build_profile(events[1:], catalog, **params).state_hash() != profile.state_hash()
    assert build_profile(events, catalog, **(params | {'evaluation_timestamp_min': minute + 1})).long[0][3] == 1


def test_two_interests_and_empty_short_profile_are_replayable():
    catalog = catalog_with_axes(3)
    events = [ProfileEvent(str(i), 10, i + 1, 'previous', 1) for i in range(3)]
    profile = build_profile(events, catalog, evaluation_timestamp_min=11, session_id='new', event_seq_id=3)
    values, present = profile.audio_features(catalog.vectors[:2], catalog)
    np.testing.assert_allclose(values, [[1, 1 / 3, 0, 1 / np.sqrt(3)]] * 2, atol=1e-5)
    assert present.tolist() == [[True, True, False, True]] * 2


def test_replay_rejects_wrong_hash_and_ignores_events_after_cutoff():
    catalog = catalog_with_axes(3)
    events = [ProfileEvent(str(i), 10, i + 1, 's', 1) for i in range(3)]
    params = dict(evaluation_timestamp_min=10, session_id='s', event_seq_id=2)
    expected = build_profile(events[:2], catalog, **params).state_hash()
    assert replay_profile(events, catalog, **params, profile_state_hash=expected).state_hash() == expected
    changed = [ProfileEvent('0', 10, 1, 's', 2), *events[1:]]
    with pytest.raises(ValueError, match='hash differs'):
        replay_profile(changed, catalog, **params, profile_state_hash=expected)


def test_blend_preserves_unscored_leader_from_midpool_and_ties():
    positions = list(range(1, 18))
    assert blend_order(18, positions, np.ones(len(positions))) == list(range(18))
    assert blend_order(200, list(range(60, 160)), np.arange(100))[:9] == list(range(9))
    assert blend_order(200, list(range(1, 200)), np.arange(199)[::-1])[0] == 1


def preview_files(path, minute):
    tracks = [dict(recording_id=str(i), vector_index=i, title=f'Track {i}', artist=f'Artist {i}', duration=180)
              for i in range(30)]
    vectors = np.eye(30, 512, dtype=np.float16)
    vectors[4] = vectors[0]
    with path.with_suffix('.npy').open('wb') as output:
        np.save(output, vectors, allow_pickle=False)
    digest = hashlib.sha256(path.with_suffix('.npy').read_bytes()).hexdigest()
    path.write_text(json.dumps(dict(encoder=ENCODER, version='v1', tracks=tracks, vectors_sha256=digest)),
                    encoding='utf-8')
    events = [dict(recording_id=str(i), event_seq_id=i + 1, timestamp_min=minute, session_id='s', weight=1)
              for i in range(3)]
    path.with_suffix('.events.json').write_text(json.dumps(dict(catalog_version='v1', session_id='s',
                                                                event_seq_id=3, events=events)), encoding='utf-8')


def test_preview_rejects_event_gap_and_vector_digest_mismatch(tmp_path):
    path = tmp_path / 'catalog.json'
    preview_files(path, 30)
    assert len(AudioDiscoveryRanker.load_local_preview(path, 30).profile.long) == 3
    event_path = path.with_suffix('.events.json')
    snapshot = json.loads(event_path.read_text(encoding='utf-8'))
    snapshot['events'].pop(1)
    event_path.write_text(json.dumps(snapshot), encoding='utf-8')
    with pytest.raises(ValueError, match='complete event prefix'):
        AudioDiscoveryRanker.load_local_preview(path, 30)
    with path.with_suffix('.npy').open('ab') as file:
        file.write(b'changed')
    with pytest.raises(ValueError, match='SHA-256'):
        AudioDiscoveryRanker.load_local_preview(path, 30)


def test_openings_preview_changes_order_and_falls_back(recommendations, monkeypatch, tmp_path):
    import time

    path = tmp_path / 'catalog.json'
    preview_files(path, int(time.time()) // 60)
    pool = [track(str(i), f'Track {i}', f'Artist {i}') for i in range(3, 30)]
    monkeypatch.setattr(recommendations, '_feed_tracks', lambda *args, **kwargs: pool)

    def openings():
        mixes = fetch(recommendations.get_mixes)
        return next(mix['tracks'] for mix in mixes if mix['title'] == 'Открытия для вас')

    base = openings()
    monkeypatch.setenv('NEDOTIFY_DISCOVERY_PREVIEW_CATALOG', str(path))
    assert [row['title'] for row in base[:2]] == ['Track 3', 'Track 4']
    assert openings()[0]['title'] == 'Track 4'
    path.with_suffix('.events.json').write_text('{}', encoding='utf-8')
    assert openings() == base


def test_openings_uses_matching_mlp_checkpoint(recommendations, monkeypatch, tmp_path):
    import time

    path = tmp_path / 'catalog.json'
    preview_files(path, int(time.time()) // 60)
    pool = [track(str(i), f'Track {i}', f'Artist {i}') for i in range(3, 30)]
    monkeypatch.setattr(recommendations, '_feed_tracks', lambda *args, **kwargs: pool)
    monkeypatch.setenv('NEDOTIFY_DISCOVERY_PREVIEW_CATALOG', str(path))
    arrays = {name: np.zeros(shape, dtype=np.float32) for name, shape in model_shapes('compact').items()}
    arrays['scalar_scale'].fill(1)
    weights = path.with_suffix('.npz')
    np.savez(weights, **arrays, architecture='compact', catalog_version='v1', feature_schema_version=1,
             scalar_features=SCALAR_FEATURES)
    path.with_suffix('.model.json').write_text(json.dumps(dict(weights_sha256=hashlib.sha256(
        weights.read_bytes()).hexdigest())), encoding='utf-8')
    mixes = fetch(recommendations.get_mixes)
    openings = next(mix['tracks'] for mix in mixes if mix['title'] == 'Открытия для вас')
    assert openings[0]['title'] == 'Track 3'  # Equal MLP scores leave the base order intact.
