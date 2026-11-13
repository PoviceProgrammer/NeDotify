import hashlib
import math

import numpy as np
import pytest

from services.embedding_catalog import EmbeddingCatalog
from services.embedding_ranker import ProfileEvent, build_profile
from services.recommendation_mlp import FEATURE_SCHEMA_VERSION, SCALAR_FEATURES, RecommendationMLP, model_inputs, model_shapes
from tools.prepare_recommendation_pairs import prepare_pairs


def make_weights(architecture):
    arrays = {name: np.zeros(shape, dtype=np.float32) for name, shape in model_shapes(architecture).items()}
    arrays['scalar_scale'].fill(1)
    return arrays


@pytest.mark.parametrize('architecture, expected', [('compact', 203329), ('target', 1017473)])
def test_parameter_budget(architecture, expected):
    assert sum(math.prod(shape) for name, shape in model_shapes(architecture).items()
               if not name.startswith('scalar_')) == expected


def test_missing_audio_and_scalar_have_zero_features_even_with_bias(tmp_path):
    arrays = make_weights('compact')
    arrays['projection_bias'][0] = 2
    arrays['scalar_mean'][0] = 3
    arrays['scalar_scale'][0] = 2
    arrays['layer0_weight'][128, 0] = 1  # Short-term projection.
    arrays['layer0_weight'][512, 0] = 1  # First standardized scalar.
    for index in (1, 2, 3):
        arrays[f'layer{index}_weight'][0, 0] = 1

    path = tmp_path / 'ranker.npz'
    np.savez(path, **arrays, architecture='compact', catalog_version='test',
             feature_schema_version=FEATURE_SCHEMA_VERSION, scalar_features=SCALAR_FEATURES)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    model = RecommendationMLP.load(path, sha256=digest, catalog_version='test')
    audio = np.zeros((2, 3, 512), dtype=np.float32)
    scalars = np.zeros((2, 16), dtype=np.float32)
    present = np.zeros_like(scalars, dtype=bool)
    audio[1, 1, 0] = 1
    scalars[:, 0] = [np.nan, 7]
    present[1, 0] = True
    np.testing.assert_allclose(model.score_batch(audio, scalars, present), [0, math.sqrt(128) + 2], atol=1e-5)

    with pytest.raises(ValueError, match='catalog'):
        RecommendationMLP.load(path, sha256=digest, catalog_version='other')
    with pytest.raises(ValueError, match='checksum'):
        RecommendationMLP.load(path, sha256='0' * 64, catalog_version='test')


def test_feature_schema_uses_only_replayable_history_and_catalog_metadata():
    tracks = [dict(recording_id=str(i), vector_index=i, title=f'Track {i}', artist='Artist') for i in range(4)]
    tracks[3]['duration'] = 180
    catalog = EmbeddingCatalog('one', tracks, np.eye(4, 512, dtype=np.float16))
    events = [ProfileEvent(str(i), 10 + i, i + 1, 'previous', 2) for i in range(3)]
    profile = build_profile(events, catalog, evaluation_timestamp_min=20, session_id='new', event_seq_id=3)
    audio, values, present = model_inputs(profile, catalog, ['0', '3'], 'discovery')
    assert audio.shape == (2, 3, 512) and not audio[:, 1].any()
    idx = SCALAR_FEATURES.index
    assert values[:, idx('same_artist_strong')].tolist() == [3, 3]
    assert values[:, idx('known_recording')].tolist() == [1, 0]
    assert values[:, idx('novelty_mode')].tolist() == [2, 2]
    assert not present[:, idx('short_similarity')].any()
    assert present[:, idx('duration_seconds')].tolist() == [False, True]


def test_pair_preparation_replays_exact_profile_and_uses_explicit_outcomes():
    tracks = [dict(recording_id=str(i), vector_index=i, title=f'Track {i}', artist='Artist') for i in range(7)]
    catalog = EmbeddingCatalog('one', tracks, np.eye(7, 512, dtype=np.float16))
    events = [ProfileEvent(str(i), 10 + i, i + 1, 'session', 1) for i in range(3)]
    outcomes = [dict(recording_id='3', started=True, listened_fraction=.8),
                dict(recording_id='4', started=True, manual_skip=True, listened_seconds=2, listened_fraction=.05),
                dict(recording_id='5', started=False),
                dict(recording_id='6', started=True, playback_error=True, manual_skip=True,
                     listened_seconds=0, listened_fraction=0)]
    impressions = []
    for minute in (20, 25):
        profile = build_profile(events, catalog, evaluation_timestamp_min=minute, session_id='session', event_seq_id=3)
        impressions.append(dict(evaluation_timestamp_min=minute, session_id='session', event_seq_id=3,
                                profile_state_hash=profile.state_hash(), feature_schema_version=FEATURE_SCHEMA_VERSION,
                                catalog_version='one', novelty_mode='balanced', outcomes=outcomes))
    impressions.append(dict(impressions[0], profile_state_hash='wrong'))
    splits, counts = prepare_pairs(impressions, events, catalog, validation_start=25)
    assert counts == {'train_impressions': 1, 'validation_impressions': 1, 'unreplayable': 1}
    for split in splits.values():
        assert len(split) == 1
        np.testing.assert_array_equal(split[0][0][:, 2], np.eye(7, 512, dtype=np.float32)[[3, 4]])
