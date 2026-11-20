"""Background availability checks for album tracklists.

Mirrors :class:`core.playlist_availability.PlaylistAvailability`: every track
carries an ``availability`` status — ``available`` / ``unavailable`` /
``unknown`` / ``pending``. Local files and known catalogue state resolve
synchronously, the rest are probed in a worker pool and republished through
``album_availability_updated`` events. Albums have no database rows of their
own, so statuses live on the emitted track dicts instead of a table.
"""

from concurrent.futures import ThreadPoolExecutor
import logging
import threading
import time

from core.offline import available_track


class AlbumAvailability:
    def __init__(self, core, emit):
        self._core = core
        self._emit = emit
        self._lock = threading.Lock()
        self._jobs = {}
        self._closed = threading.Event()
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='AlbumAudio')

    def start(self, tracks, request_id=None):
        """Annotate ``tracks`` in place, then probe every 'pending' one."""
        pending = []
        for track in tracks or []:
            track['availability'] = self._quick_status(track)
            if track['availability'] == 'pending':
                pending.append(track)
        if not pending:
            return
        with self._lock:
            if self._closed.is_set():
                return
            job = self._jobs.setdefault(request_id, {
                'total': 0, 'checked': 0, 'available': 0,
                'unavailable': 0, 'unknown': 0, 'last_emit': 0.0,
            })
            for track in pending:
                job['total'] += 1
                self._pool.submit(self._check, request_id, tracks, track)

    def _quick_status(self, track):
        """Cheap synchronous pass: local files and known catalogue state."""
        if available_track(self._core.db, track, stored_tracks={}):
            return 'available'
        source = track.get('source')
        if source == 'local':
            return 'unavailable'
        if not source or not track.get('source_id'):
            return 'unknown'
        settings = getattr(self._core, 'settings', None)
        if settings and settings.get('services', source + '_enabled', True) is False:
            return 'unknown'
        resolver = getattr(self._core, 'resolver', None)
        if resolver is None:
            return 'pending'
        if resolver.is_unavailable(source, track.get('source_id')):
            return 'unavailable'
        if resolver.get_cached_url(source, track['source_id']):
            return 'available'
        return 'pending'

    def _probe_status(self, track):
        """Network probe with the same semantics as PlaylistAvailability._status."""
        source = track.get('source')
        settings = getattr(self._core, 'settings', None)
        if settings and settings.get('services', source + '_enabled', True) is False:
            return 'unknown'
        resolver = getattr(self._core, 'resolver', None)
        track_id = track.get('source_id')
        probe = dict(track)
        probe.pop('id', None)  # Playback may update a library row's metadata.
        probe.pop('file_path', None)
        url = self._core.engine.resolve_stream_url(probe, cancel_token=self._closed.is_set)
        if url:
            return 'available'
        if resolver is not None and resolver.is_unavailable(source, track_id):
            return 'unavailable'
        return 'unknown'

    def _check(self, request_id, tracks, track):
        if self._closed.is_set():
            return
        try:
            status = self._probe_status(track)
        except Exception as exc:
            logging.getLogger(__name__).debug('Album audio check failed: %s', type(exc).__name__)
            status = 'unknown'
        with self._lock:
            job = self._jobs.get(request_id)
            if job is None or self._closed.is_set():
                return
            track['availability'] = status
            job['checked'] += 1
            job[status] += 1
            done = job['checked'] == job['total']
            now = time.monotonic()
            if not done and now - job['last_emit'] < .2:
                return
            job['last_emit'] = now
            update = {key: job[key] for key in ('total', 'checked', 'available', 'unavailable', 'unknown')}
            snapshot = [dict(item) for item in tracks]
            if done:
                del self._jobs[request_id]
        self._emit('album_availability_updated',
                   dict(update, request_id=request_id, stage='done' if done else 'checking', tracks=snapshot))

    def close(self):
        with self._lock:
            self._closed.set()
            self._pool.shutdown(wait=False, cancel_futures=True)
