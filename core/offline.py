"""Local-only availability checks shared by playback and library views."""

import os
import stat
import time
import copy
from urllib.parse import urlparse


_AUDIO_EXTENSIONS = frozenset(('.mp3', '.m4a', '.aac', '.flac', '.wav', '.ogg', '.opus', '.webm', '.mp4', '.wma', '.aiff'))


def _local_file(path, cached=False):
    if not isinstance(path, str) or not path or urlparse(path).scheme in ('http', 'https'):
        return None
    if os.path.splitext(path)[1].lower() not in _AUDIO_EXTENSIONS:
        return None
    try:
        info = os.stat(path)
        return path if stat.S_ISREG(info.st_mode) and info.st_size >= (4096 if cached else 1) else None
    except OSError:
        return None


def _with_file(track, path):
    result = dict(track, file_path=path, offline_available=True)
    result.pop('stream_url', None)
    result.pop('_offline_cached_path', None)
    return result


def available_track(db, track, cached_paths=None, stored_tracks=None):
    if not isinstance(track, dict):
        return None
    path = _local_file(track.get('file_path'))
    if path:
        return _with_file(track, path)
    source, source_id = track.get('source'), track.get('source_id')
    stored = None
    identifier = track.get('track_id') or track.get('id')
    if identifier is not None:
        try:
            stored = stored_tracks.get(int(identifier)) if stored_tracks is not None else db.get_track(int(identifier))
        except (TypeError, ValueError):
            pass
    if stored:
        path = _local_file(stored.get('file_path'))
        if path:
            return _with_file(dict(stored, **track), path)
        source, source_id = stored.get('source') or source, stored.get('source_id') or source_id
    if source and source_id:
        cached = ({'cached_file_path': cached_paths.get((source, str(source_id)))} if cached_paths is not None
                  else db.get_cached_stream(source, str(source_id), max_age_seconds=2 ** 31 - 1))
        path = _local_file(cached.get('cached_file_path'), cached=True) if cached else None
        if path:
            return _with_file(track, path)
    return None


def available_tracks(db, tracks, cached_paths=None):
    tracks = list(tracks)
    cached = cached_paths if cached_paths is not None else {(row['source'], str(row['source_id'])): row['cached_file_path']
              for row in db.conn.execute('SELECT source, source_id, cached_file_path FROM stream_cache WHERE cached_file_path IS NOT NULL')}
    identifiers = []
    for track in tracks:
        try:
            identifiers.append(int(track.get('track_id') or track.get('id')))
        except (AttributeError, TypeError, ValueError):
            pass
    stored = {}
    for start in range(0, len(identifiers), 500):
        batch = identifiers[start:start + 500]
        for row in db.conn.execute('SELECT * FROM tracks WHERE id IN (' + ','.join('?' for _ in batch) + ')', batch):
            stored[row['id']] = dict(row)
    result = []
    for track in tracks:
        if not isinstance(track, dict):
            continue
        available = available_track(db, track, cached_paths=cached, stored_tracks=stored)
        if available:
            result.append(available)
    return result


def offline_library(db):
    return offline_library_page(db)[0]


# Page calls reuse only compact identity/path data; metadata is read for the
# requested page. Directory mutations are noticed immediately via directory mtime.
# Stale/missing files without directory events are lazily reconciled on page query
# and during playback (play_track), eliminating linear periodic disk storms.
AVAILABILITY_RECHECK_SECONDS = 0


class _AvailabilityIndex:
    def __init__(self, db):
        self.revision = db.availability_revision
        self.entries = [dict(row) for row in db.conn.execute('''
            SELECT t.id,t.file_path,c.cached_file_path FROM tracks t
            LEFT JOIN stream_cache c ON c.source=t.source AND c.source_id=t.source_id
            ORDER BY t.added_at DESC''')]
        self.directories = {}
        self.paths = {}
        self.checked_at = 0
        self.refresh(force=True)

    @staticmethod
    def _directory_stamp(directory):
        try:
            return os.stat(directory).st_mtime_ns
        except OSError:
            return None

    def refresh(self, force=False):
        now = time.monotonic()
        changed = {directory for directory, stamp in self.directories.items()
                   if self._directory_stamp(directory) != stamp}
        if not force and not changed:
            return self
        # Published snapshots are immutable. Build the next one without holding
        # the database write lock, including all potentially slow disk checks.
        if not force:
            result = copy.copy(self)
            result.paths = dict(self.paths)
            result.directories = dict(self.directories)
            return result._refresh_entries(now, changed, force=False)
        return self._refresh_entries(now, changed, force=True)

    def _refresh_entries(self, now, changed, force=False):
        visited_directories = set()
        for entry in self.entries:
            candidates = (entry['file_path'], entry['cached_file_path'])
            directories = {os.path.dirname(path) or '.' for path in candidates if isinstance(path, str) and path}
            if force or directories & changed:
                path = _local_file(candidates[0]) or _local_file(candidates[1], cached=True)
                if path:
                    self.paths[entry['id']] = path
                else:
                    self.paths.pop(entry['id'], None)
            visited_directories.update(directories)
        for directory in visited_directories:
            if force or directory in changed:
                self.directories[directory] = self._directory_stamp(directory)
        self.ids = [entry['id'] for entry in self.entries if entry['id'] in self.paths]
        self.checked_at = now
        return self


def _availability_index(db):
    while True:
        revision = db.availability_revision
        old = getattr(db, '_offline_availability_index', None)
        candidate = _AvailabilityIndex(db) if old is None or old.revision != revision else old.refresh()
        with db._write_lock:
            if revision != db.availability_revision:
                continue
            db._offline_availability_index = candidate
            return candidate


def offline_library_ids(db):
    return list(_availability_index(db).ids)


def offline_library_page(db, limit=None, offset=0):
    index = _availability_index(db)
    # A returned file is always revalidated, even during the reconciliation
    # interval. Refill a page if a file vanished without a directory event.
    while True:
        ids = index.ids[offset:] if limit is None else index.ids[offset:offset + limit]
        stored = {}
        for start in range(0, len(ids), 500):
            batch = ids[start:start + 500]
            stored.update((row['id'], dict(row)) for row in db.conn.execute(
                'SELECT * FROM tracks WHERE id IN (' + ','.join('?' for _ in batch) + ')', batch))
        tracks, missing = [], set()
        for identifier in ids:
            track = stored.get(identifier)
            local = available_track(db, track) if track else None
            if local:
                tracks.append(local)
            else:
                missing.add(identifier)
        if not missing:
            return tracks, len(index.ids)
        replacement = copy.copy(index)
        replacement.ids = [identifier for identifier in index.ids if identifier not in missing]
        replacement.paths = {identifier: path for identifier, path in index.paths.items() if identifier not in missing}
        with db._write_lock:
            if getattr(db, '_offline_availability_index', None) is index:
                db._offline_availability_index = replacement
        index = replacement


def invalidate_offline_track(db, track_id):
    """Lazily evict a track from the availability index if its file is missing or invalid."""
    try:
        tid = int(track_id)
    except (TypeError, ValueError):
        return
    index = getattr(db, '_offline_availability_index', None)
    if index is None:
        return
    if tid in index.paths or tid in index.ids:
        replacement = copy.copy(index)
        replacement.ids = [i for i in index.ids if i != tid]
        replacement.paths = {i: p for i, p in index.paths.items() if i != tid}
        with db._write_lock:
            if getattr(db, '_offline_availability_index', None) is index:
                db._offline_availability_index = replacement
