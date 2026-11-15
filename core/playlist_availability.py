"""Background availability checks for the exact rows saved by playlist import."""

from concurrent.futures import ThreadPoolExecutor
import logging
import threading
import time

from core.offline import available_track


class PlaylistAvailability:
    def __init__(self, core, emit):
        self._core = core
        self._emit = emit
        self._lock = threading.Lock()
        self._jobs = {}
        self._closed = threading.Event()
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='PlaylistAudio')

    def start(self, playlist_id, tracks, job_id=None):
        pending = [track for track in tracks if track.get('availability') == 'pending']
        if not pending:
            if job_id is not None:
                self._emit('playlist_import_progress', {'job_id': job_id, 'stage': 'done'})
            return
        with self._lock:
            if self._closed.is_set():
                return
            job = self._jobs.setdefault(playlist_id, {
                'listeners': set(), 'scheduled': set(), 'total': 0,
                'checked': 0, 'available': 0, 'unavailable': 0, 'unknown': 0, 'last_emit': 0.0,
            })
            if job_id is not None:
                job['listeners'].add(job_id)
            for track in pending:
                if track['id'] in job['scheduled']:
                    continue
                job['scheduled'].add(track['id'])
                job['total'] += 1
                self._pool.submit(self._check, playlist_id, track)

    def _status(self, track):
        if available_track(self._core.db, track, stored_tracks={}):
            return 'available'
        source = track.get('source')
        if source == 'local':
            return 'unavailable'
        settings = getattr(self._core, 'settings', None)
        if settings and settings.get('services', source + '_enabled', True) is False:
            return 'unknown'
        resolver = getattr(self._core, 'resolver', None)
        track_id = track.get('source_id')
        probe = dict(track)
        probe.pop('id', None)
        probe.pop('file_path', None)
        url = self._core.engine.resolve_stream_url(probe, cancel_token=self._closed.is_set)
        if url:
            return 'available'
        if resolver is not None and resolver.is_unavailable(source, track_id):
            return 'unavailable'
        return 'unknown'

    def _check(self, playlist_id, track):
        if self._closed.is_set():
            return
        try:
            status = self._status(track)
        except Exception as exc:
            logging.getLogger(__name__).debug('Playlist audio check failed: %s', type(exc).__name__)
            status = 'unknown'
        if self._closed.is_set():
            return
        try:
            self._core.db.set_playlist_track_availability(playlist_id, track['id'], status)
        except Exception as exc:
            logging.getLogger(__name__).debug('Playlist status write failed: %s', type(exc).__name__)
            status = 'unknown'
        with self._lock:
            job = self._jobs[playlist_id]
            job['checked'] += 1
            job[status] += 1
            done = job['checked'] == job['total']
            now = time.monotonic()
            if not done and now - job['last_emit'] < .2:
                return
            job['last_emit'] = now
            update = {key: job[key] for key in ('total', 'checked', 'available', 'unavailable', 'unknown')}
            listeners = tuple(job['listeners'])
            if done:
                del self._jobs[playlist_id]
        for job_id in listeners:
            self._emit('playlist_import_progress', dict(update, job_id=job_id, playlist_id=playlist_id,
                                                        stage='done' if done else 'checking'))
        if done:
            self._emit('playlist_availability_updated', {'playlist_id': playlist_id})

    def close(self):
        with self._lock:
            self._closed.set()
            self._pool.shutdown(wait=False, cancel_futures=True)
