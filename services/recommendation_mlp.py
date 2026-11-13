"""NumPy inference for the versioned recommendation model artifact."""

import hashlib
from datetime import datetime, timedelta, timezone

import numpy as np

from services.embedding_ranker import FEATURE_SCHEMA_VERSION, normalized


LAYERS = {'compact': (544, 192, 128, 64, 1), 'target': (544, 768, 640, 64, 1)}
PROJECTION_SIZE = 128
LAYER_NORM_EPSILON = 1e-5
SCALAR_FEATURES = (
    'max_similarity', 'top5_mean_similarity', 'short_similarity', 'long_similarity',
    'long_recordings', 'short_recordings', 'long_span_days', 'latest_positive_age_days',
    'same_artist_long', 'same_artist_short', 'same_artist_strong', 'same_artist_latest_age_days',
    'duration_seconds', 'release_age_years', 'known_recording', 'novelty_mode',
)
NOVELTY_MODES = {'familiar': 0, 'balanced': 1, 'discovery': 2}
SCALAR_COUNT = len(SCALAR_FEATURES)
UNIX_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def model_inputs(profile, catalog, recording_ids, novelty_mode):
    recordings = [catalog.recording(recording_id) for recording_id in recording_ids]
    if any(record is None or record.vector_index is None for record in recordings):
        raise ValueError('Model candidates must have a vector in the active catalog')
    indexes = [record.vector_index for record in recordings]
    audio_features, audio_present, audio = profile.audio_inputs(catalog.vectors[indexes], catalog)
    scalars = np.zeros((len(recordings), SCALAR_COUNT), dtype=np.float32)
    present = np.ones(scalars.shape, dtype=bool)
    scalars[:, :4], present[:, :4] = audio_features, audio_present
    minute = profile.evaluation_timestamp_min
    year = (UNIX_EPOCH + timedelta(minutes=minute)).year
    long = profile.long
    short = profile.short
    scalars[:, 4:6] = len(long), len(short)
    if long:
        scalars[:, 6:8] = (long[0][1] - long[-1][1]) / 1440, (minute - long[0][1]) / 1440
    else:
        present[:, 6:8] = False
    long_artists = [catalog.recording(entry[0]).artist_key for entry in long]
    short_artists = [catalog.recording(entry[0]).artist_key for entry in short]
    known = {row[0] for row in long} | {row[0] for row in short}
    for index, recording in enumerate(recordings):
        artist = recording.artist_key
        related = [row for row, key in zip(long, long_artists, strict=True) if artist and key == artist]
        scalars[index, 8:12] = (len(related), short_artists.count(artist) if artist else 0,
                                sum(row[3] == 2 for row in related), (minute - related[0][1]) / 1440 if related else 0)
        present[index, 8:12] = bool(artist), bool(artist), bool(artist), bool(related)
        scalars[index, 12:16] = (recording.duration, max(0, year - recording.release_year) if recording.release_year else 0,
                                 recording.id in known, NOVELTY_MODES[novelty_mode])
        present[index, 12:14] = bool(recording.duration), recording.release_year is not None
    return audio, scalars, present


def model_shapes(architecture):
    sizes = LAYERS[architecture]
    shapes = {'projection_weight': (512, PROJECTION_SIZE), 'projection_bias': (PROJECTION_SIZE,)}
    for index, (input_size, output_size) in enumerate(zip(sizes[:-1], sizes[1:], strict=True)):
        shapes[f'layer{index}_weight'] = (input_size, output_size)
        shapes[f'layer{index}_bias'] = (output_size,)
    shapes['scalar_mean'] = (SCALAR_COUNT,)
    shapes['scalar_scale'] = (SCALAR_COUNT,)
    return shapes


class RecommendationMLP:
    def __init__(self, architecture, arrays):
        self.architecture = architecture
        self.arrays = {}
        for name, shape in model_shapes(architecture).items():
            value = np.asarray(arrays[name], dtype=np.float32)
            if value.shape != shape or not np.isfinite(value).all():
                raise ValueError(f'Invalid model array: {name}')
            self.arrays[name] = value
        if (self.arrays['scalar_scale'] <= 0).any():
            raise ValueError('Scalar scales must be positive')

    @classmethod
    def load(cls, path, *, sha256, catalog_version):
        with open(path, 'rb') as source:
            if hashlib.file_digest(source, 'sha256').hexdigest() != sha256:
                raise ValueError('Model checksum differs')
            source.seek(0)
            with np.load(source, allow_pickle=False) as data:
                if (data['feature_schema_version'].item() != FEATURE_SCHEMA_VERSION
                        or data['catalog_version'].item() != catalog_version
                        or data['scalar_features'].tolist() != list(SCALAR_FEATURES)):
                    raise ValueError('Incompatible model schema or catalog')
                return cls(data['architecture'].item(), data)

    def score_batch(self, audio, scalars, present):
        """Score batches of [long, short, track] vectors and 16 ordered scalar features."""
        audio = np.asarray(audio, dtype=np.float32)
        scalars = np.asarray(scalars, dtype=np.float32)
        present = np.asarray(present, dtype=bool)
        if audio.ndim != 3 or audio.shape[1:] != (3, 512):
            raise ValueError('Expected audio shape (N, 3, 512)')
        if scalars.shape != (len(audio), SCALAR_COUNT) or present.shape != scalars.shape:
            raise ValueError('Expected scalar and presence shapes (N, 16)')
        if not np.isfinite(audio).all() or not np.isfinite(scalars[present]).all():
            raise ValueError('Model inputs must be finite')

        arrays = self.arrays
        audio_present = np.linalg.norm(audio, axis=-1, keepdims=True) > 1e-12
        projected = normalized(audio @ arrays['projection_weight'] + arrays['projection_bias'])
        projected = np.where(audio_present, projected, 0)
        interaction = projected[:, 0] * projected[:, 2]
        centered = interaction - interaction.mean(axis=1, keepdims=True)
        variance = (centered * centered).mean(axis=1, keepdims=True)
        interaction = np.clip(centered / np.sqrt(variance + LAYER_NORM_EPSILON), -4, 4)
        scalars = np.where(present, (scalars - arrays['scalar_mean']) / arrays['scalar_scale'], 0)
        features = np.concatenate((projected.reshape(len(audio), 3 * PROJECTION_SIZE) * np.float32(PROJECTION_SIZE ** .5),
                                   interaction, scalars, present), axis=1)
        layers = len(LAYERS[self.architecture]) - 1
        for index in range(layers):
            features = features @ arrays[f'layer{index}_weight'] + arrays[f'layer{index}_bias']
            if index < layers - 1:
                np.maximum(features, 0, out=features)
        scores = features[:, 0]
        if not np.isfinite(scores).all():
            raise ValueError('Model returned nonfinite scores')
        return scores
