"""Reconstruct training pairs from local exports of impressions and profile events."""

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

if __name__ == '__main__':
    sys.path[0] = str(Path(__file__).resolve().parents[1])

import numpy as np

from services.embedding_catalog import EmbeddingCatalog
from services.embedding_ranker import FEATURE_SCHEMA_VERSION, ProfileEvent, replay_profile
from services.recommendation_mlp import NOVELTY_MODES, SCALAR_FEATURES, UNIX_EPOCH, model_inputs


MAX_UTC_MINUTE = int((datetime(9999, 12, 31, 23, 59, tzinfo=timezone.utc) - UNIX_EPOCH).total_seconds()) // 60


def _label(outcome):
    if outcome.get('hidden') is True:
        return -1
    if outcome.get('liked') is True or outcome.get('added') is True:
        return 1
    if outcome.get('playback_error') is True or outcome.get('started') is not True:
        return 0
    fraction = outcome.get('listened_fraction')
    if type(fraction) not in (int, float) or not 0 <= fraction <= 1:
        return 0
    if fraction >= .7:
        return 1
    seconds = outcome.get('listened_seconds')
    if (outcome.get('manual_skip') is True and type(seconds) in (int, float)
            and 0 <= seconds < 10 and fraction < .1):
        return -1
    return 0


def prepare_pairs(impressions, events, catalog, validation_start):
    splits = {'train': [], 'validation': []}
    counts = Counter()
    for impression in impressions:
        if (impression.get('feature_schema_version') != FEATURE_SCHEMA_VERSION
                or impression.get('catalog_version') != catalog.version):
            counts['incompatible'] += 1
            continue
        evaluation_min = impression.get('evaluation_timestamp_min')
        state_hash = impression.get('profile_state_hash')
        session_id = impression.get('session_id')
        mode = impression.get('novelty_mode')
        if (type(evaluation_min) is not int or not 0 <= evaluation_min <= MAX_UTC_MINUTE
                or not isinstance(state_hash, str) or not state_hash
                or not isinstance(session_id, str) or not session_id
                or not isinstance(mode, str) or mode not in NOVELTY_MODES):
            counts['invalid_impression'] += 1
            continue
        try:
            profile = replay_profile(events, catalog, evaluation_timestamp_min=evaluation_min,
                                     session_id=session_id, event_seq_id=impression.get('event_seq_id'),
                                     profile_state_hash=state_hash)
        except ValueError:
            counts['unreplayable'] += 1
            continue
        if len(profile.long) < 3:
            counts['cold_start'] += 1
            continue
        outcomes = impression.get('outcomes')
        if not isinstance(outcomes, list) or not all(isinstance(row, dict) for row in outcomes):
            counts['invalid_impression'] += 1
            continue
        ids = [row.get('recording_id') for row in outcomes]
        if any(not isinstance(recording, str) for recording in ids) or len(ids) != len(set(ids)):
            counts['invalid_impression'] += 1
            continue
        labeled = [(recording, _label(row)) for recording, row in zip(ids, outcomes, strict=True)
                   if catalog.vector_index(recording) is not None]
        positives = [recording for recording, label in labeled if label > 0]
        negatives = [recording for recording, label in labeled if label < 0]
        if not positives or not negatives:
            counts['no_pairs'] += 1
            continue
        audio, scalars, present = model_inputs(profile, catalog, positives + negatives, mode)
        split = 'train' if evaluation_min < validation_start else 'validation'
        negative_indexes = range(len(positives), len(positives) + len(negatives))
        for positive, negative in product(range(len(positives)), negative_indexes):
            indexes = [positive, negative]
            splits[split].append((audio[indexes], scalars[indexes], present[indexes], evaluation_min))
        counts[f'{split}_impressions'] += 1
    return splits, counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--events', type=Path, required=True, help='JSON object with an events array for one installation')
    parser.add_argument('--impressions', type=Path, required=True, help='JSON Lines of joined impressions for the same installation')
    parser.add_argument('--validation-start', type=int, required=True, help='First UTC minute of the validation split')
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    catalog = EmbeddingCatalog.load(args.catalog)
    if catalog.vectors is None:
        parser.error('Catalog must include embeddings')
    events = [ProfileEvent(**row) for row in json.loads(args.events.read_text(encoding='utf-8'))['events']]
    with args.impressions.open(encoding='utf-8') as source:
        splits, counts = prepare_pairs((json.loads(line) for line in source if line.strip()), events, catalog,
                                       args.validation_start)
    for name, pairs in splits.items():
        counts[f'{name}_pairs'] = len(pairs)
    print(json.dumps(dict(counts), sort_keys=True))
    if not all(splits.values()):
        parser.error('Both splits require at least one replayable labeled pair')
    args.output_dir.mkdir(parents=True, exist_ok=False)
    for name, pairs in splits.items():
        audio, scalars, present, minutes = zip(*pairs, strict=True)
        np.savez(args.output_dir / f'{name}.npz', audio=np.stack(audio), scalars=np.stack(scalars),
                 present=np.stack(present), evaluation_timestamp_min=np.asarray(minutes, dtype=np.int64),
                 feature_schema_version=FEATURE_SCHEMA_VERSION, catalog_version=catalog.version,
                 scalar_features=SCALAR_FEATURES)


if __name__ == '__main__':
    main()
