"""Report aggregate catalog coverage from a read-only library snapshot."""

import argparse
import csv
import io
import json
import re
import sqlite3
import sys
import time
import zipfile
from collections import defaultdict
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.embedding_catalog import EmbeddingCatalog


FMA_LICENSE = re.compile(
    r'(?:https?://creativecommons\.org/(?:licenses/by/[\d.]+|publicdomain/zero/1\.0)/?'
    r'|(?:Creative Commons )?Attribution(?: [\d.]+(?: [\w :]+)?)?|CC0 1\.0 Universal)', re.I)
CYRILLIC = re.compile('[А-Яа-яЁё]')


def fma_catalog(path):
    with zipfile.ZipFile(path) as archive, archive.open('fma_metadata/tracks.csv') as source:
        reader = csv.reader(io.TextIOWrapper(source, encoding='utf-8', newline=''))
        columns = list(zip(next(reader), next(reader), strict=True))
        next(reader)  # Index name row.
        license_col = columns.index(('track', 'license'))
        title_col = columns.index(('track', 'title'))
        artist_col = columns.index(('artist', 'name'))
        duration_col = columns.index(('track', 'duration'))
        language_col = columns.index(('track', 'language_code'))
        tracks = [dict(recording_id='fma:' + row[0], title=row[title_col], artist=row[artist_col],
                       duration=row[duration_col], language=row[language_col]) for row in reader
                  if row and FMA_LICENSE.fullmatch(row[license_col].strip())]
    return EmbeddingCatalog('fma-metadata', tracks)


def coverage(tracks, catalog):
    groups = defaultdict(lambda: dict(total=0, matched=0, vector=0, vector_playback_checked=0,
                                     vector_and_playable=0))
    groups['all']
    groups['cyrillic_metadata']
    for track in tracks:
        entry = catalog.match(track)
        vector = entry is not None and entry.vector_index is not None
        labels = ['all', 'source:' + str(track.get('source') or 'unknown')]
        if CYRILLIC.search(str(track.get('artist') or '') + str(track.get('title') or '')):
            labels.append('cyrillic_metadata')
        for label in labels:
            counts = groups[label]
            counts['total'] += 1
            counts['matched'] += entry is not None
            counts['vector'] += vector
            counts['vector_playback_checked'] += vector and type(track.get('playback_verified')) is bool
            counts['vector_and_playable'] += vector and track.get('playback_verified') is True
    return dict(groups)


def library_rows(path):
    uri = path.resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True)) as source, closing(sqlite3.connect(':memory:')) as snapshot:
        source.backup(snapshot)
        snapshot.row_factory = sqlite3.Row
        return [dict(row) for row in snapshot.execute(
            'SELECT title, artist, duration, source, metadata_json FROM tracks')]


def discover_candidates(path):
    import tempfile

    from core.database import DatabaseManager
    from services.recommendation_service import RecommendationService
    from services.soundcloud_service import SoundCloudService
    from services.youtube_service import YouTubeService

    with tempfile.TemporaryDirectory(prefix='nedotify-coverage-') as folder:
        copy = Path(folder) / 'library.db'
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as source:
            with closing(sqlite3.connect(copy)) as snapshot:
                source.backup(snapshot)
        db = DatabaseManager(str(copy))
        service = RecommendationService(db=db, youtube_service=YouTubeService(), soundcloud_service=SoundCloudService())
        try:
            profile = service._profile()
            deadline = time.monotonic() + 17
            feed = service._feed_tracks(profile, 30, deadline=deadline)
            candidates = service._daily_mix_candidates(profile, service._daily_artist_buckets(profile),
                                                        feed, service._known_content_keys(profile), deadline)
            known = service._known_content_keys(profile)
            seen = set(known)
            discoveries = []
            for track in candidates:
                key = service._content_key(track)
                if key not in seen and service._playable(track):
                    seen.add(key)
                    discoveries.append(track)
            return discoveries
        finally:
            service._candidate_executor.shutdown(wait=True, cancel_futures=True)
            service.shutdown_executor()
            db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument('--catalog', type=Path, help='OpenL3 JSON manifest')
    sources.add_argument('--fma-metadata', type=Path, help='Official fma_metadata.zip')
    candidates_arg = parser.add_mutually_exclusive_group()
    candidates_arg.add_argument('--candidates', type=Path, help='JSON list of candidate track metadata')
    candidates_arg.add_argument('--live-candidates', action='store_true', help='Collect fresh discovery metadata')
    args = parser.parse_args()
    report = {}
    if args.fma_metadata:
        catalog = fma_catalog(args.fma_metadata)
    else:
        catalog = EmbeddingCatalog.load(args.catalog)
    report['catalog_recordings'] = len(catalog)
    report['catalog_version'] = catalog.version
    report['library'] = coverage(library_rows(args.db), catalog)
    if args.live_candidates:
        report['candidates'] = coverage(discover_candidates(args.db), catalog)
    if args.candidates:
        candidates = json.loads(args.candidates.read_text(encoding='utf-8'))
        if not isinstance(candidates, list) or not all(isinstance(track, dict) for track in candidates):
            parser.error('--candidates requires a JSON list of track objects')
        report['candidates'] = coverage(candidates, catalog)
    print(json.dumps(report, indent=2, ensure_ascii=True))


if __name__ == '__main__':
    main()
