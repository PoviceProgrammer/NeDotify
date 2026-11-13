"""Deterministic audio ranking and replayable profile features for the beta."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from services.embedding_catalog import EmbeddingCatalog


RANKER_VERSION = 'openl3_cosine_v0'
FEATURE_SCHEMA_VERSION = 1
HISTORY_MINUTES = 90 * 24 * 60
HALF_LIFE_MINUTES = 14 * 24 * 60


@dataclass(frozen=True, slots=True)
class ProfileEvent:
    recording_id: str
    timestamp_min: int
    event_seq_id: int
    session_id: str
    weight: int

    def __post_init__(self):
        if (not isinstance(self.recording_id, str) or not self.recording_id
                or not isinstance(self.session_id, str) or not self.session_id
                or type(self.timestamp_min) is not int or self.timestamp_min < 0
                or type(self.event_seq_id) is not int or self.event_seq_id < 1
                or type(self.weight) is not int or self.weight not in (1, 2)):
            raise ValueError('Invalid positive recommendation event')


def normalized(rows):
    norms = np.linalg.norm(rows, axis=-1, keepdims=True)
    return np.divide(rows, norms, out=np.zeros_like(rows), where=norms > 1e-12)


def _collapse_events(events, limit):
    latest = {}
    weights = {}
    for event in events:
        record = event.recording_id
        latest.setdefault(record, event)
        weights[record] = max(weights.get(record, 0), event.weight)
    return tuple((record, event.timestamp_min, event.event_seq_id, weights[record])
                 for record, event in list(latest.items())[:limit])


@dataclass(frozen=True, slots=True)
class ProfileInputs:
    long: tuple
    short: tuple
    evaluation_timestamp_min: int
    session_id: str
    catalog_version: str

    def state_hash(self):
        payload = (FEATURE_SCHEMA_VERSION, self.catalog_version, self.evaluation_timestamp_min,
                   self.session_id, self.long, self.short)
        return hashlib.sha256(json.dumps(payload, ensure_ascii=True, separators=(',', ':')).encode('ascii')).hexdigest()

    def audio_features(self, candidates, catalog):
        """Return max, top-5 mean, session and long-term cosine, plus masks."""
        values, present, _ = self.audio_inputs(candidates, catalog)
        return values, present

    def audio_inputs(self, candidates, catalog):
        """Return cosine features, masks, and the three vectors in model order."""
        if catalog.version != self.catalog_version:
            raise ValueError('Profile and catalog versions differ')
        candidates = normalized(np.asarray(candidates, dtype=np.float32))
        values = np.zeros((len(candidates), 4), dtype=np.float32)
        present = np.zeros(values.shape, dtype=bool)
        vectors = np.zeros((len(candidates), 3, 512), dtype=np.float32)
        vectors[:, 2] = candidates
        if self.long:
            history, weights = self._vectors_and_weights(self.long, catalog, decay=True)
            similarities = candidates @ history.T
            values[:, 0] = similarities.max(axis=1)
            top_count = min(5, len(history))
            top = np.partition(similarities, len(history) - top_count, axis=1)[:, -top_count:]
            values[:, 1] = top.mean(axis=1)
            present[:, :2] = True
            centroid = normalized(weights @ history)
            vectors[:, 0] = centroid
            values[:, 3] = candidates @ centroid
            present[:, 3] = bool(centroid.any())
        if self.short:
            history, weights = self._vectors_and_weights(self.short, catalog, decay=False)
            centroid = normalized(weights @ history)
            vectors[:, 1] = centroid
            values[:, 2] = candidates @ centroid
            present[:, 2] = bool(centroid.any())
        return np.clip(values, -1, 1), present, vectors

    def _vectors_and_weights(self, records, catalog, *, decay):
        indexes = [catalog.vector_index(record) for record, _, _, _ in records]
        if None in indexes:
            raise ValueError('Profile record has no vector in this catalog')
        weights = np.array([weight * 2 ** (-(self.evaluation_timestamp_min - minute) / HALF_LIFE_MINUTES)
                            if decay else weight for _, minute, _, weight in records], dtype=np.float32)
        return normalized(catalog.vectors[indexes].astype(np.float32)), weights


def build_profile(events, catalog, *, evaluation_timestamp_min, session_id, event_seq_id):
    eligible = sorted((event for event in events if event.event_seq_id <= event_seq_id
                       and 0 <= evaluation_timestamp_min - event.timestamp_min <= HISTORY_MINUTES
                       and catalog.vector_index(event.recording_id) is not None),
                      key=lambda event: (event.timestamp_min, event.event_seq_id), reverse=True)
    long = _collapse_events(eligible, 100)
    short = _collapse_events((event for event in eligible if event.session_id == session_id), 10)
    return ProfileInputs(long, short, evaluation_timestamp_min, session_id, catalog.version)


def replay_profile(events, catalog, *, evaluation_timestamp_min, session_id, event_seq_id,
                   profile_state_hash=None):
    if type(event_seq_id) is not int or event_seq_id < 0:
        raise ValueError('Invalid event prefix length')
    prefix = [event for event in events if event.event_seq_id <= event_seq_id]
    if len(prefix) != event_seq_id or len({event.event_seq_id for event in prefix}) != event_seq_id:
        raise ValueError('Profile replay requires the complete event prefix')
    profile = build_profile(prefix, catalog, evaluation_timestamp_min=evaluation_timestamp_min,
                            session_id=session_id, event_seq_id=event_seq_id)
    if profile_state_hash is not None and profile.state_hash() != profile_state_hash:
        raise ValueError('Replayed profile state hash differs')
    return profile


def _hazen(scores):
    count = len(scores)
    result = np.empty(count, dtype=np.float64)
    order = np.argsort(-scores, kind='stable')
    sorted_scores = scores[order]
    boundaries = np.r_[0, np.flatnonzero(sorted_scores[1:] != sorted_scores[:-1]) + 1, count]
    for start, stop in zip(boundaries[:-1], boundaries[1:], strict=True):
        result[order[start:stop]] = (count - (start + stop) / 2) / count
    return result


def blend_order(count, scored_positions, scores):
    if not count:
        return []
    scored_count = len(scored_positions)
    coverage = scored_count / count
    alpha = .5 * np.clip((coverage - .25) / .25, 0, 1) * np.clip((scored_count - 5) / 10, 0, 1)
    if not alpha:
        return list(range(count))
    blended = (count - np.arange(count) - .5) / count
    blended[scored_positions] += .2 * alpha * (_hazen(np.asarray(scores)) - .5)
    return np.argsort(-blended, kind='stable').tolist()


class AudioDiscoveryRanker:
    def __init__(self, catalog, profile, model=None):
        self.catalog = catalog
        self.profile = profile
        self.model = model

    @classmethod
    def load_local_preview(cls, catalog_path, evaluation_timestamp_min):
        """Replay a local beta event snapshot alongside its catalog manifest."""
        path = Path(catalog_path)
        catalog = EmbeddingCatalog.load(path)
        snapshot = json.loads(path.with_suffix('.events.json').read_text(encoding='utf-8'))
        if snapshot['catalog_version'] != catalog.version:
            raise ValueError('Event snapshot and catalog versions differ')
        events = [ProfileEvent(**event) for event in snapshot['events']]
        profile = replay_profile(events, catalog, evaluation_timestamp_min=evaluation_timestamp_min,
                                 session_id=snapshot['session_id'], event_seq_id=snapshot['event_seq_id'])
        model = None
        model_path = path.with_suffix('.model.json')
        if model_path.is_file():
            from services.recommendation_mlp import RecommendationMLP

            manifest = json.loads(model_path.read_text(encoding='utf-8'))
            model = RecommendationMLP.load(path.with_suffix('.npz'), sha256=manifest['weights_sha256'],
                                           catalog_version=catalog.version)
        return cls(catalog, profile, model)

    def order(self, candidates, *, novelty_mode='balanced'):
        if len(self.profile.long) < 3:
            return list(range(len(candidates)))
        positions, recordings = [], []
        for position, candidate in enumerate(candidates[:200]):
            recording = self.catalog.match(candidate)
            if recording and recording.vector_index is not None:
                positions.append(position)
                recordings.append(recording)
        if not positions:
            return list(range(len(candidates)))
        if self.model is None:
            indexes = [recording.vector_index for recording in recordings]
            audio, _ = self.profile.audio_features(self.catalog.vectors[indexes], self.catalog)
            scores = audio[:, :2].mean(axis=1)
        else:
            from services.recommendation_mlp import model_inputs

            inputs = model_inputs(self.profile, self.catalog, [recording.id for recording in recordings], novelty_mode)
            scores = self.model.score_batch(*inputs)
        count = min(len(candidates), 200)
        return blend_order(count, positions, scores) + list(range(count, len(candidates)))
