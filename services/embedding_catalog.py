"""Recording identities and a versioned OpenL3 catalog shared by ranking and audit."""

import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from services.artist_identity import track_key


ENCODER = 'openl3:music:mel128:512'


def duration_seconds(track):
    try:
        value = float(track.get('duration') or 0)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return value if math.isfinite(value) and value > 0 else 0.0


def recording_ids(track):
    metadata = track.get('metadata_json') or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except ValueError:
            metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    mbid = str(track.get('mbid') or track.get('musicbrainz_recording_id')
               or metadata.get('mbid') or metadata.get('musicbrainz_recording_id') or '').strip().lower()
    isrc = str(track.get('isrc') or metadata.get('isrc') or '').strip().replace('-', '').upper()
    return mbid, isrc


@dataclass(frozen=True, slots=True)
class Recording:
    id: str
    duration: float
    vector_index: int | None
    artist_key: str
    release_year: int | None


class EmbeddingCatalog:
    def __init__(self, version, tracks, vectors=None):
        if not isinstance(version, str) or not version.strip():
            raise ValueError('Catalog version is required')
        self.version = version
        self.vectors = vectors
        self._identities = defaultdict(list)
        self._metadata = defaultdict(list)
        self._recordings = {}
        for track in tracks:
            record_id = track['recording_id']
            if not isinstance(record_id, str) or not record_id.strip() or record_id in self._recordings:
                raise ValueError('Catalog recording IDs must be nonempty and unique')
            index = track.get('vector_index')
            if index is not None and (vectors is None or type(index) is not int or not 0 <= index < len(vectors)):
                raise ValueError('Catalog vector index is out of range')
            key = track_key(track)
            year = track.get('release_year')
            entry = Recording(record_id, duration_seconds(track), index, key[0],
                              year if type(year) is int and 1000 <= year <= 9999 else None)
            self._recordings[record_id] = entry
            for kind, value in zip(('mbid', 'isrc'), recording_ids(track), strict=True):
                if value:
                    self._identities[kind, value].append(entry)
            if all(key):
                self._metadata[key].append(entry)

    @classmethod
    def load(cls, path):
        manifest_path = Path(path)
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if manifest.get('encoder') != ENCODER or not isinstance(manifest.get('tracks'), list):
            raise ValueError('Unsupported embedding catalog format')
        vectors = None
        vector_digest = manifest.get('vectors_sha256')
        if vector_digest is not None:
            import hashlib
            import numpy as np

            with manifest_path.with_suffix('.npy').open('rb') as source:
                if hashlib.file_digest(source, 'sha256').hexdigest() != vector_digest:
                    raise ValueError('Catalog vectors SHA-256 does not match manifest')
                source.seek(0)
                vectors = np.load(source, allow_pickle=False)
            if (not isinstance(vectors, np.ndarray) or vectors.dtype != np.float16
                    or vectors.ndim != 2 or vectors.shape[1] != 512
                    or not np.isfinite(vectors).all() or not np.any(vectors, axis=1).all()):
                raise ValueError('Expected nonzero finite FP16 catalog vectors with dimension 512')
            vectors.setflags(write=False)
        return cls(manifest['version'], manifest['tracks'], vectors)

    def vector_index(self, recording_id):
        entry = self.recording(recording_id)
        return entry.vector_index if entry else None

    def recording(self, recording_id):
        return self._recordings.get(recording_id)

    def __len__(self):
        return len(self._recordings)

    def match(self, track):
        duration = duration_seconds(track)
        mbid, isrc = recording_ids(track)
        mbid_matches = self._identities.get(('mbid', mbid), ())
        isrc_matches = self._identities.get(('isrc', isrc), ())
        if mbid_matches and isrc_matches:
            candidates = set(mbid_matches).intersection(isrc_matches)
        elif mbid_matches or isrc_matches:
            candidates = mbid_matches or isrc_matches
        elif duration:
            # Require both duration and an exact artist/title key for metadata
            # fallback. The key retains remix, live and version qualifiers.
            candidates = [entry for entry in self._metadata.get(track_key(track), ()) if entry.duration]
        else:
            return None
        matches = [entry for entry in candidates if not duration or not entry.duration
                   or abs(entry.duration - duration) <= min(5, duration * .03)]
        return matches[0] if len(matches) == 1 else None
