"""
NeDotify - Background Downloader
Queues and manages downloading audio files and metadata.
"""

import os
import logging
import threading
import time
import inspect
import math
import random
import uuid
import json
from contextlib import nullcontext
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from core.download_store import DownloadStore
from core.download_transfer import DownloadContext, DownloadInterrupted, IncompleteDownload
from core.user_errors import describe_error, redact_download_error
from core.download_processing import OutputPolicy, download_directory, process_download, fetch_cover
from services.recording_selection import remembered_video_id
from utils.url_safety import is_safe_media_url

logger = logging.getLogger(__name__)

# Provider threads: kept in sync with the pool width so the queue processor can
# apply backpressure (a bounded number of accepted-but-unfinished tasks).
_MAX_INFLIGHT = 2
_MAX_WORKERS = 4

# Sources ``_download_worker`` knows how to fetch. Anything else (e.g. 'vk',
# which has no download provider yet) fails with a source-specific error
# instead of the generic "returned None or file missing" one.
_SUPPORTED_SOURCES = frozenset({'youtube', 'soundcloud', 'yandex', 'spotify', 'spotify_album', 'deezer'})

# A downloaded file that is not one of these, is below the floor, or is a
# leftover .part is not audio. Providers can hand back such a path, and
# accepting it marks the track as downloaded with nothing to play.
_AUDIO_DOWNLOAD_EXTS = ('.m4a', '.mp3', '.opus', '.webm', '.aac', '.ogg',
                        '.mp4', '.flac', '.wav')
_MIN_AUDIO_BYTES = 4 * 1024


def _downloaded_file_defect(path: str, expected_duration=0) -> str:
    """Why *path* is not a usable download, or '' when it looks fine."""
    if not path or not os.path.isfile(path):
        return 'файл не найден'
    name = os.path.basename(path)
    if name.endswith('.part'):
        return f'незавершённая загрузка ({name})'
    if os.path.splitext(name)[1].lower() not in _AUDIO_DOWNLOAD_EXTS:
        return f'скачан не аудиофайл ({name})'
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        return f'не удаётся прочитать файл: {exc}'
    if size < _MIN_AUDIO_BYTES:
        return f'файл повреждён ({size} байт)'
    try:
        from utils.audio_validation import audio_duration
        duration = audio_duration(path)
        if not math.isfinite(duration) or duration <= 0:
            return 'аудиоконтейнер повреждён или не содержит аудио'
        expected = float(expected_duration or 0)
        if expected > 0:
            # Two-sided gate (BUG-A1-008): "shorter than expected" alone let an
            # extended mix / 1-hour version / live recording pass as "the"
            # download. Beyond the fork the file is simply a different record.
            if duration < expected - max(5.0, expected * .05):
                return 'аудиофайл обрезан'
            if duration > expected * 1.25 + 5.0:
                return 'скачана не та запись (длительность не совпадает)'
    except Exception:
        return 'не удалось проверить аудиоконтейнер'
    return ''


def _is_403_error(error):
    if not error:
        return False
    response = getattr(error, 'response', None)
    status = getattr(error, 'code', None) or getattr(response, 'status_code', None)
    if status == 403:
        return True
    low = str(error).lower()
    return '403' in low and ('forbidden' in low or 'http' in low)


class _RetryLater(Exception):
    def __init__(self, error, delay):
        self.error, self.delay = error, delay
        super().__init__(str(error))


class DownloadManager:
    def __init__(self, app_core):
        self._core = app_core
        self._pool = ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix='download_worker')
        self._artwork_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='download_cover')
        self._running = True
        self._queue = []
        self._queue_lock = threading.Lock()
        self._queue_event = threading.Event()
        self._lock = threading.Lock()  # guards batch counters (_batch_active/_batch_completed/_batch_total/_batch_failed)

        # Cooperative cancellation: cancel_batch()/stop() bump the epoch, so every
        # task queued *before* that bump is recognised as stale and aborts instead
        # of downloading (ThreadPoolExecutor.Future.cancel cannot stop a task the
        # pool has already accepted).
        self._cancel_epoch = 0

        self._batch_total = 0
        self._batch_completed = 0
        self._batch_failed = 0
        self._batch_active = False
        self._batch_done_ids = set()
        self._paused_track_ids = set()
        self._track_generations = {}
        self._progress_state = {}
        self._worker_context = threading.local()
        self._futures = []
        self._active_track_ids = set()  # guarded by _futures_lock
        self._futures_lock = threading.Lock()

        self._init_db_table()
        self._store = DownloadStore(self._core.db)
        self._store.recover()
        self._cleanup_orphaned_part_files()
        self._resume_pending_downloads()
        self._processor_thread = threading.Thread(target=self._process_queue, daemon=True)
        self._processor_thread.start()

    def _invalidate_stream_cache(self, source, source_id):
        if not source or not source_id:
            return
        if hasattr(self._core, 'resolver') and self._core.resolver:
            try:
                self._core.resolver.invalidate(source, str(source_id))
            except Exception as e:
                logger.debug(f'Resolver cache invalidation failed: {e}')
        if hasattr(self._core, 'db') and self._core.db:
            try:
                self._core.db.invalidate_cached_stream(source, str(source_id))
            except Exception as e:
                logger.debug(f'Database cache invalidation failed: {e}')
        provider_name = {'youtube': 'youtube', 'spotify': 'youtube', 'soundcloud': 'soundcloud'}.get(source, source)
        provider = getattr(self._core, provider_name, None)
        invalidator = getattr(provider, 'invalidate_stream_url', None)
        if callable(invalidator):
            try:
                invalidator(source_id)
            except Exception as e:
                logger.debug(f'Provider stream cache invalidation failed: {e}')

    @staticmethod
    def _cleanup_orphaned_part_files(download_dir=None):
        """Purge lingering .part.json files that have no corresponding .part file."""
        if not download_dir:
            download_dir = os.path.join(os.path.expanduser('~'), '.nedotify', 'downloads')
        if not os.path.isdir(download_dir):
            return
        try:
            for fname in os.listdir(download_dir):
                if fname.endswith('.part.json'):
                    part_file = os.path.join(download_dir, fname[:-5])  # strip .json -> .part
                    if not os.path.isfile(part_file):
                        try:
                            os.remove(os.path.join(download_dir, fname))
                        except OSError:
                            pass
        except Exception as e:
            logger.debug(f'Cleanup of orphaned .part.json files failed: {e}')

    def get_downloads(self):
        return self._store.rows()

    def cancel_download(self, track_id):
        """Cancel a single task, including its active provider/postprocessor."""
        targets = [row for row in self._store.rows(limit=5000) if str(row['track_id']) == str(track_id)
                   and row['status'] in ('pending', 'downloading', 'paused')]
        for row in targets:
            target = row['track_id']
            with self._lock:
                self._track_generations[target] = self._track_generations.get(target, 0) + 1
                self._paused_track_ids.discard(target)
            with self._queue_lock:
                self._queue = [item for item in self._queue if item['track_id'] != target]
            self._store.update(target, status='cancelled', resume_on_restart=0)
            self._on_batch_task_done(target, success=False)
            self._emit('download_queue_updated', {'track_id': target, 'status': 'cancelled'})
        self._queue_event.set()
        return {'success': True, 'count': len(targets)}

    def retry_download(self, track_id):
        rows = [row for row in self._store.rows(('failed', 'cancelled')) if str(row['track_id']) == str(track_id)]
        queued = sum(int(self.queue_download(row['track_id'], row['source'], row['source_id'])) for row in rows)
        return {'success': True, 'count': queued}

    def pause_download(self, track_id=None):
        rows = self._store.rows(('pending', 'downloading'), limit=5000)
        targets = [row['track_id'] for row in rows if track_id is None or str(row['track_id']) == str(track_id)]
        with self._lock:
            for target in targets:
                self._paused_track_ids.add(target)
                self._track_generations[target] = self._track_generations.get(target, 0) + 1
        with self._queue_lock:
            self._queue = [item for item in self._queue if item['track_id'] not in targets]
        for target in targets:
            self._store.update(target, status='paused', resume_on_restart=0)
            self._on_batch_task_done(target, success=False)
        self._emit('download_queue_updated', {'status': 'paused'})
        return {'success': True, 'count': len(targets)}

    def resume_download(self, track_id=None):
        rows = self._store.rows(('paused',), limit=5000)
        targets = [row for row in rows if track_id is None or str(row['track_id']) == str(track_id)]
        count = 0
        for row in targets:
            target = row['track_id']
            with self._lock:
                self._paused_track_ids.discard(target)
            self._store.update(target, status='pending', error='', resume_on_restart=0)
            count += int(self.queue_download(target, row['source'], row['source_id'], from_db=True))
        self._emit('download_queue_updated', {'status': 'pending'})
        return {'success': True, 'count': count}

    def retry_failed_downloads(self):
        rows = self._store.rows(('failed',), limit=5000)
        count = 0
        for row in rows:
            count += int(self.queue_download(row['track_id'], row['source'], row['source_id']))
        self._emit('download_queue_updated', {'status': 'pending'})
        return {'success': True, 'count': count}

    def _call_provider(self, provider, source_id, download_dir):
        context = getattr(self._worker_context, 'context', None)
        tools = getattr(context, 'tools', {}) if context else {}
        if tools.get('yt_dlp_path') and (tools.get('prefer_executable') or not tools.get('yt_dlp_module', True)):
            if provider is getattr(self._core, 'youtube', None):
                from services.youtube_service import _is_allowed_youtube_target
                target = str(source_id)
                if target.startswith('http') and not _is_allowed_youtube_target(target):
                    raise ValueError('Недопустимый адрес YouTube')
                if not target.startswith(('http', 'ytsearch')):
                    target = 'https://www.youtube.com/watch?v=' + target
                return context.download_executable(target, download_dir)
            if provider is getattr(self._core, '_soundcloud', None):
                target = str(source_id)
                if not target.startswith('http'):
                    target = ('https://api-v2.soundcloud.com/tracks/' if target.isdigit() else 'https://soundcloud.com/') + target
                return context.download_executable(target, download_dir)
        method = provider.download_audio_sync
        try:
            accepts_context = 'download_context' in inspect.signature(method).parameters
        except (TypeError, ValueError):
            accepts_context = False
        if context and accepts_context:
            context.checkpoint()
            return method(source_id, download_dir, download_context=context)
        return method(source_id, download_dir)

    def _checkpoint_transfer(self):
        context = getattr(self._worker_context, 'context', None)
        if context:
            context.checkpoint()

    def _record_progress(self, track_id, downloaded, total, force=False):
        now = time.monotonic()
        with self._lock:
            state = self._progress_state.setdefault(track_id, {})
            previous_bytes = state.get('downloaded_bytes', 0)
            previous_time = state.get('sample_at', now)
            state.update(downloaded_bytes=max(0, int(downloaded)), total_bytes=max(0, int(total)), sample_at=now)
            if downloaded > previous_bytes and now > previous_time:
                state['bytes_per_second'] = (downloaded - previous_bytes) / (now - previous_time)
            if not force and now - state.get('emitted_at', 0) < 0.2:
                return
            state['emitted_at'] = now
            payload = {name: state[name] for name in ('downloaded_bytes', 'total_bytes')}
        self._store.update(track_id, phase='downloading', **payload)
        payload.update(track_id=track_id, percent=(min(99, round(payload['downloaded_bytes'] * 100 / payload['total_bytes']))
                                                  if payload['total_bytes'] else None))
        payload['stage'] = 'downloading'
        payload['bytes_per_second'] = round(state.get('bytes_per_second', 0))
        payload['eta_seconds'] = round(max(0, payload['total_bytes'] - payload['downloaded_bytes']) / payload['bytes_per_second']) if payload['bytes_per_second'] and payload['total_bytes'] else None
        self._emit('download_progress', payload)

    def _emit(self, event_name, data=None):
        """Emit via api._emit (same channel as download_complete)."""
        try:
            if event_name == 'download_failed' and isinstance(data, dict):
                data = dict(data)
                details = ({key: data[key] for key in ('code', 'message', 'action') if key in data}
                           if data.get('code') in ('missing_yt_dlp', 'missing_ffmpeg', 'missing_ffprobe', 'dependencies_busy', 'lossy_source')
                           else describe_error(data.get('error'), 'download'))
                data.update(details, method='download_track')
                # The event crosses the UI boundary. Keep the raw provider
                # detail in DownloadStore for retry classification, but expose
                # only the safe, actionable message to frontend listeners.
                data['error'] = details['message']
            api = getattr(self._core, 'api', None)
            emitter = getattr(api, '_emit', None) if api else None
            if callable(emitter):
                emitter(event_name, data)
            elif api and hasattr(api, 'emit_event'):
                api.emit_event(event_name, data if isinstance(data, dict) else {})
        except Exception:
            logger.warning("downloader emit %s failed", event_name, exc_info=True)

    def start_batch(self, total: int):
        """Initialize batch download tracking."""
        with self._lock:
            self._batch_total = total
            self._batch_completed = 0
            self._batch_failed = 0
            self._batch_active = total > 0
            self._batch_done_ids = set()

    def _decrement_batch_total_for_dedup(self):
        """Shrink the batch denominator when a queued item turns out to be a duplicate."""
        finished_payload = None
        with self._lock:
            if not self._batch_active:
                return
            if self._batch_total > 0:
                self._batch_total = max(0, self._batch_total - 1)
            if self._batch_total == 0 or self._batch_completed >= self._batch_total:
                self._batch_active = False
                finished_payload = {
                    'total': self._batch_total,
                    'completed': self._batch_completed,
                    'failed': self._batch_failed,
                }
        # Emit outside both _lock and (when called from queue_download) _queue_lock:
        # _emit crosses the pywebview bridge and must not run under our locks.
        if finished_payload is not None:
            self._emit('batch_download_finished', finished_payload)

    def _on_batch_task_done(self, track_id, success: bool):
        """Account for one finished worker (success or failure) and emit progress."""
        with self._lock:
            if not self._batch_active:
                return
            if track_id in self._batch_done_ids:
                return
            self._batch_done_ids.add(track_id)
            self._batch_completed += 1
            if not success:
                self._batch_failed += 1
            percent = round((self._batch_completed / max(1, self._batch_total)) * 100)
            total = self._batch_total
            completed = self._batch_completed
            failed = self._batch_failed
            finished = completed >= total
            if finished:
                self._batch_active = False
        self._emit('batch_download_progress', {
            'current': completed,
            'total': total,
            'percent': percent,
            'track_id': track_id
        })
        if finished:
            self._emit('batch_download_finished', {
                'total': total,
                'completed': completed,
                'failed': failed,
            })

    def cancel_batch(self):
        """Cancel ongoing batch download and clear queue.

        The pool cannot cancel work it has already accepted, so cancellation is
        cooperative: the epoch bump marks every already-queued task as stale and
        the workers abort at their next stage check. Tasks queued *after* this
        call carry the new epoch and run normally.
        """
        self._cancel_epoch += 1
        with self._queue_lock:
            self._queue.clear()
        with self._futures_lock:
            snapshot = list(self._futures)
        # Cancel outside _futures_lock: a cancelled future runs its done-callback
        # synchronously, and that callback takes the same lock.
        cancelled = set()
        for fut in snapshot:
            try:
                if fut.cancel():
                    cancelled.add(fut)  # never started: drop it from the in-flight list
            except Exception:
                pass
        with self._futures_lock:
            # Keep accepted-but-unfinished futures so backpressure and stop()
            # still see the downloads that are really running.
            self._futures = [f for f in self._futures if f not in cancelled]
        with self._lock:
            self._batch_active = False
            self._batch_total = 0
            self._batch_completed = 0
            self._batch_failed = 0
        try:
            if hasattr(self._core.db, 'download_queue_cancel_pending'):
                self._core.db.download_queue_cancel_pending()
            else:
                with self._core.db._write_lock:
                    with self._core.db.conn:
                        columns = {row[1] for row in self._core.db.conn.execute(
                            "PRAGMA table_info(download_queue)"
                        )}
                        resume_reset = ", resume_on_restart=0" if "resume_on_restart" in columns else ""
                        self._core.db.conn.execute(
                            "UPDATE download_queue SET status='cancelled'" + resume_reset +
                            " WHERE status IN ('pending','downloading')"
                        )
        except Exception:
            pass
        self._emit('batch_download_cancelled', True)
        self._emit('download_queue_updated', {'status': 'cancelled'})
        return True

    def _init_db_table(self):
        """Create download queue table if missing and enforce one row per track."""
        try:
            if hasattr(self._core.db, 'ensure_download_queue_table'):
                self._core.db.ensure_download_queue_table()
                return
        except Exception as e:
            logger.error(f'Failed to init download_queue table: {e}')
            return
        # Fallback for DB managers without the helper (thread-safe via _write_lock).
        try:
            with self._core.db._write_lock:
                with self._core.db.conn:
                    self._core.db.conn.execute("""
                        CREATE TABLE IF NOT EXISTS download_queue (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            track_id INTEGER NOT NULL,
                            source TEXT,
                            source_id TEXT,
                            status TEXT DEFAULT 'pending',
                            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
        except Exception as e:
            logger.error(f'Failed to init download_queue table: {e}')

        # Older databases accumulated duplicate rows per track (dedup was only
        # in-memory), so a plain UNIQUE constraint cannot be retrofitted onto the
        # table. Collapse duplicates first (keep the newest attempt), then add a
        # unique index that holds for both old and new databases.
        try:
            with self._core.db._write_lock:
                with self._core.db.conn:
                    self._core.db.conn.execute("""
                        DELETE FROM download_queue
                        WHERE id NOT IN (
                            SELECT MAX(id) FROM download_queue GROUP BY track_id
                        )
                    """)
                    self._core.db.conn.execute(
                        "CREATE UNIQUE INDEX IF NOT EXISTS ux_download_queue_track "
                        "ON download_queue(track_id)"
                    )
        except Exception as e:
            logger.error(f'Failed to enforce unique download_queue.track_id: {e}')

    def _resume_pending_downloads(self):
        try:
            if hasattr(self._core.db, 'download_queue_get_pending'):
                rows = self._core.db.download_queue_get_pending()
            else:
                cursor = self._core.db.conn.cursor()
                cursor.execute("SELECT track_id, source, source_id FROM download_queue WHERE status IN ('pending', 'downloading')")
                rows = cursor.fetchall()
            for row in rows:
                if isinstance(row, dict) or hasattr(row, 'keys'):
                    track_id, source, source_id = row['track_id'], row['source'], row['source_id']
                else:
                    track_id, source, source_id = row[0], row[1], row[2]
                with self._queue_lock:
                    if any(item['track_id'] == track_id for item in self._queue):
                        continue
                with self._futures_lock:
                    if track_id in self._active_track_ids:
                        continue
                self.queue_download(track_id, source, source_id, from_db=True)
        except Exception as e:
            logger.error(f'Failed to resume downloads: {e}')

    def queue_download(self, track_id, source, source_id, from_db=False):
        """Queue a track for download (at most one row per track). Returns True if queued."""
        if not isinstance(track_id, int) or isinstance(track_id, bool) or track_id <= 0:
            self._decrement_batch_total_for_dedup()
            return False
        if not from_db:
            old = self._store.get(track_id)
            if old.get('status') == 'completed':
                track = self._core.db.get_track(track_id) or {}
                if not os.path.isfile(str(track.get('file_path') or '')):
                    with self._core.db._write_lock, self._core.db.conn:
                        self._core.db.conn.execute("UPDATE download_queue SET status = 'failed' WHERE track_id = ? AND status = 'completed'", (track_id,))
                        self._core.db.conn.execute('UPDATE tracks SET is_downloaded = 0 WHERE id = ?', (track_id,))
            if hasattr(self._core.db, 'download_queue_add'):
                added = self._core.db.download_queue_add(track_id, source, source_id)
            else:
                added = True
                try:
                    with self._core.db._write_lock:
                        with self._core.db.conn:
                            self._core.db.conn.execute(
                                'INSERT INTO download_queue (track_id, source, source_id) VALUES (?, ?, ?)',
                                (track_id, source, source_id),
                            )
                except Exception as e:
                    # Unique index: the track already has a queue row - nothing to add.
                    logger.debug(f'Download queue insert skipped for track {track_id}: {e}')
                    added = False
            if not added:
                self._decrement_batch_total_for_dedup()
                return False

        options = {'error': '', 'error_code': '', 'phase': 'queued', 'warning': ''}
        if not from_db:
            from dataclasses import asdict
            options.update(job_id=uuid.uuid4().hex, options=json.dumps({
                **asdict(OutputPolicy.from_settings(getattr(self._core, 'settings', None))),
                'directory': download_directory(getattr(self._core, 'settings', None)),
            }))
        self._store.update(track_id, **options)

        with self._lock:
            generation = self._track_generations.get(track_id, 0)

        duplicate = False
        with self._queue_lock:
            if not any(item['track_id'] == track_id for item in self._queue):
                self._queue.append({
                    'track_id': track_id,
                    'source': source,
                    'source_id': source_id,
                    # Cancellation generation: items queued before a cancel_batch()
                    # bump must abort instead of downloading.
                    'epoch': self._cancel_epoch,
                    'generation': generation,
                })
                self._queue_event.set()
            else:
                duplicate = True
        if duplicate:
            # In-memory duplicate: shrink the batch denominator so the batch can
            # finish. Called outside _queue_lock because it emits an event.
            self._decrement_batch_total_for_dedup()
            return False
        logger.info('Queued download for track %s from %s', track_id, source)
        self._emit('download_queue_updated', {'track_id': track_id, 'status': 'pending'})
        return True

    def _release_track_id(self, track_id):
        with self._futures_lock:
            self._active_track_ids.discard(track_id)
        self._queue_event.set()

    def _running_futures(self):
        """Prune finished futures and return the ones still in flight."""
        with self._futures_lock:
            self._futures = [f for f in self._futures if not f.done()]
            return list(self._futures)

    def _wait_for_free_slot(self):
        """Backpressure: never let more than _MAX_INFLIGHT tasks wait in the pool.

        Without this the processor drains the whole queue into the pool as fast
        as it can, so a large batch keeps downloading even after a cancel.
        """
        while self._running:
            pending = self._running_futures()
            limit = OutputPolicy.from_settings(getattr(self._core, 'settings', None)).max_concurrent
            if len(pending) < limit:
                return
            # Wait for the next completion instead of polling; the timeout only
            # bounds the wait so stop() is noticed promptly.
            wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)

    def _process_queue(self):
        """Background thread checking the queue."""
        while self._running:
            # Clear BEFORE inspecting the queue: an enqueue between inspection
            # and wait must remain signalled, otherwise startup stalls for 1s.
            self._queue_event.clear()
            self._wait_for_free_slot()
            if not self._running:
                break
            item = None
            with self._futures_lock:
                active_ids = set(self._active_track_ids)
            with self._queue_lock:
                if self._queue:
                    for index, queued in enumerate(self._queue):
                        if queued['track_id'] not in active_ids and queued.get('ready_at', 0) <= time.monotonic():
                            item = self._queue.pop(index)
                            break

            if item:
                try:
                    with self._futures_lock:
                        self._active_track_ids.add(item['track_id'])
                    fut = self._pool.submit(self._download_worker, item)
                    with self._futures_lock:
                        self._futures.append(fut)
                        # Prune finished futures so the list does not grow unbounded.
                        self._futures = [f for f in self._futures if not f.done()]
                    fut.add_done_callback(lambda _f, tid=item['track_id']: self._release_track_id(tid))
                except Exception as e:
                    self._release_track_id(item['track_id'])
                    logger.error(f'Failed to submit download worker: {e}')
                    self._on_batch_task_done(item.get('track_id'), success=False)
            else:
                with self._queue_lock:
                    due = [max(.01, row.get('ready_at', 0) - time.monotonic()) for row in self._queue if row['track_id'] not in active_ids]
                self._queue_event.wait(timeout=min(due, default=1.0))

    def _download_spotify_track(self, source_id, track_id, download_dir):
        """Resolve a Spotify track to audio via YouTube and download it.

        Spotify tracks carry ``source_id="ytsearch1: Artist - Title"`` which
        ``YouTubeService.download_audio_sync`` already understands (yt-dlp
        ``ytsearch`` URL). The recording that textual identity maps to must be
        verified (BUG-A1-003): the persisted video id from the playback
        cascade is preferred, every search fallback selects through
        ``recording_selection`` and the resolver is restricted to the YouTube
        provider so a SoundCloud substitute never lands in the library
        (BUG-A1-012).
        """
        self._checkpoint_transfer()
        settings = getattr(self._core, 'settings', None)
        if settings and settings.get('services', 'youtube_enabled', True) is False:
            raise ValueError('Источник YouTube отключён. Включите его для скачивания записи Spotify.')
        sid = str(source_id or '').strip()

        title, artist, duration = '', '', 0
        try:
            if hasattr(self._core.db, '_write_lock'):
                with self._core.db._write_lock:
                    cursor = self._core.db.conn.cursor()
                    cursor.execute("SELECT title, artist, duration FROM tracks WHERE id = ?", (track_id,))
                    row = cursor.fetchone()
            else:
                cursor = self._core.db.conn.cursor()
                cursor.execute("SELECT title, artist, duration FROM tracks WHERE id = ?", (track_id,))
                row = cursor.fetchone()
            if row is not None:
                if hasattr(row, 'keys'):
                    title = row['title'] or ''
                    artist = row['artist'] or ''
                    duration = float(row['duration'] or 0)
                else:
                    title = row[0] or ''
                    artist = row[1] or ''
                    duration = float(row[2] or 0)
        except Exception as e:
            logger.debug(f'Spotify resolve: failed to load track {track_id} metadata: {e}')

        # Query used when the DB has no title/artist: the queue source_id itself
        # (e.g. "Artist - Title" for a non-ytsearch payload). A "spotify_<id>"
        # payload carries no searchable text, so it is useless as a query.
        query_hint = '' if sid.startswith('spotify_') else (sid.split(':', 1)[1].strip() if sid.startswith('ytsearch') and ':' in sid else sid)

        wanted = {'title': title or query_hint, 'artist': artist, 'duration': duration}

        # 0. A recording verified by a previous playback cascade is authoritative.
        persisted = remembered_video_id(getattr(self._core, 'settings', None), 'spotify', sid)
        if not persisted and (title or artist):
            persisted = remembered_video_id(
                getattr(self._core, 'settings', None), 'spotify',
                f"ytsearch1: {artist} - {title}".strip())
        if persisted:
            try:
                self._checkpoint_transfer()
                return self._call_provider(self._core.youtube, persisted, download_dir)
            except Exception as exc:
                self._checkpoint_transfer()
                logger.debug(f'Persisted recording download failed for track {track_id}: {exc}')

        # 1. Preferred path: TrackResolver, YouTube only. The catalogue promised
        # an Apple/YouTube recording; a "plausible" SoundCloud cover is not one.
        try:
            from services.track_resolver import TrackResolver
            resolver = TrackResolver(
                db=getattr(self._core, 'db', None),
                soundcloud_service=None,
                youtube_service=getattr(self._core, 'youtube', None),
                # Without settings the resolver cannot build its own
                # SoundCloud/YouTube fallbacks (no cookies, no client config).
                settings=getattr(self._core, 'settings', None),
                providers=('youtube',),
            )
            self._checkpoint_transfer()
            resolved = resolver.resolve_track(title or query_hint, artist or '', expected_duration=duration)
            self._checkpoint_transfer()
            if isinstance(resolved, dict):
                r_source = resolved.get('source')
                r_id = str(resolved.get('source_id') or '').strip()
                if r_source == 'youtube' and r_id:
                    return self._call_provider(self._core.youtube, r_id, download_dir)
        except Exception as e:
            self._checkpoint_transfer()
            logger.debug(f'Spotify TrackResolver fallback for track {track_id}: {e}')

        # 2. Fallback: verified YouTube search (BUG-A1-003) — never the top hit
        # without a metadata check.
        if title or artist:
            query = f"{artist} {title}".strip()
        else:
            query = query_hint.strip()
        if not query:
            raise Exception('No title/artist metadata to resolve Spotify track')
        self._checkpoint_transfer()
        yt = getattr(self._core, 'youtube', None)
        if hasattr(yt, 'search_sync'):
            results = yt.search_sync(query, limit=5) or []
            self._checkpoint_transfer()
            from services.recording_selection import select_recording
            verified = select_recording(wanted, results)
            if verified:
                top_id = str(verified.get('source_id') or '').strip()
                if top_id:
                    return self._call_provider(self._core.youtube, top_id, download_dir)
            raise Exception('Не найдено подходящей записи трека на YouTube (проверка совпадения не пройдена)')
        elif sid.startswith('ytsearch'):
            return self._call_provider(self._core.youtube, sid, download_dir)
        raise Exception('YouTube provider does not support search')

    def _mark_queue_cancelled(self, track_id):
        """Flag a queue row as cancelled so it never stays 'downloading' forever."""
        try:
            if hasattr(self._core.db, 'download_queue_set_status'):
                self._core.db.download_queue_set_status(track_id, 'cancelled')
                return
        except Exception:
            return
        try:
            with self._core.db._write_lock:
                with self._core.db.conn:
                    self._core.db.conn.execute(
                        "UPDATE download_queue SET status = 'cancelled' "
                        "WHERE track_id = ? AND status != 'completed'",
                        (track_id,),
                    )
        except Exception:
            pass

    def _is_cancelled(self, epoch) -> bool:
        """True when this task belongs to a cancelled generation.

        Items queued before cancel_batch()/stop() carry an older epoch and abort
        at every stage boundary instead of downloading.
        """
        return epoch != self._cancel_epoch

    def _abort_cancelled(self, track_id, epoch, stage):
        """Abort a stale task: unblock the batch accounting, close the queue row."""
        context = getattr(self._worker_context, 'context', None)
        if context:
            try:
                context.checkpoint()
            except DownloadInterrupted:
                if not self._is_cancelled(epoch):
                    with self._lock:
                        paused = track_id in self._paused_track_ids
                    if paused:
                        self._store.update(track_id, status='paused')
                    self._on_batch_task_done(track_id, success=False)
                    return True
        if not self._is_cancelled(epoch):
            return False
        logger.info(f'Download for track {track_id} aborted at stage "{stage}" (cancelled)')
        self._mark_queue_cancelled(track_id)
        # Account for the batch. Right after a cancel_batch() the batch is already
        # closed (_batch_active False), so this is a no-op and emits nothing: the
        # single progress terminator stays batch_download_cancelled.
        self._on_batch_task_done(track_id, success=False)
        return True

    # Transient provider failures. Everything else (bad URL, DRM, missing
    # source) is permanent: retrying it just burns the same request again.
    # Auth failures (401/403: expired token, DRM) do NOT heal by waiting
    # (BUG-A1-019), so 'unauthorized'/'forbidden' are deliberately absent.
    _RETRYABLE_MARKS = (
        'page needs to be reloaded', 'unable to download webpage',
        'unable to download api page', 'unable to download json metadata',
        'http error 408', 'http error 429', 'http error 500', 'http error 502', 'http error 503', 'http error 504',
        'timed out', 'timeout', 'connection', 'temporarily unavailable',
        'rate limit', 'rate-limited', 'try again later', 'ssl', 'handshake',
    )
    _RETRY_ATTEMPTS = 3
    _RETRY_BASE_DELAY = 2.0  # seconds; bounded attempts, jitter and Retry-After below

    def _is_retryable_error(self, message) -> bool:
        if not message:
            return False
        explicit = getattr(message, 'retryable', None)
        if isinstance(explicit, bool):
            return explicit
        if isinstance(message, DownloadInterrupted):
            return False
        import socket
        import http.client
        import requests
        if isinstance(message, (TimeoutError, ConnectionError, socket.gaierror, http.client.IncompleteRead,
                                requests.exceptions.Timeout, requests.exceptions.ConnectionError,
                                requests.exceptions.ChunkedEncodingError)):
            return True
        response = getattr(message, 'response', None)
        status = getattr(message, 'code', None) or getattr(response, 'status_code', None)
        if status in (408, 429, 500, 502, 503, 504):
            return True
        if status in (400, 404, 410):
            return False
        low = str(message).lower()
        import re
        if re.search(r'\bhttp(?: error)?\s+(408|429|500|502|503|504)\b', low):
            return True
        if any(mark in low for mark in ('404', '410', 'not found', 'deleted', 'removed', 'drm')):
            return False
        cause = getattr(message, '__cause__', None)
        if cause is not None:
            return self._is_retryable_error(cause)
        return any(mark in low for mark in self._RETRYABLE_MARKS)

    def _fetch_from_provider(self, source, source_id, download_dir, track_id):
        """One attempt at fetching a track from its provider."""
        settings = getattr(self._core, 'settings', None)
        if source in ('youtube', 'soundcloud') and settings and settings.get('services', source + '_enabled', True) is False:
            raise ValueError(f'Источник {source} отключён в настройках')
        if source not in _SUPPORTED_SOURCES:
            # No provider is wired for this source (e.g. vk). Saying so is more
            # useful than blaming a provider for not returning a file.
            raise Exception(f"No download provider for source '{source}'.")

        file_path = None

        if source == 'youtube':
            if str(source_id or '').startswith('http') and not is_safe_media_url(str(source_id)):
                raise Exception('Unsafe media URL rejected')
            file_path = self._call_provider(self._core.youtube, source_id, download_dir)
        elif source == 'soundcloud':
            sid = str(source_id or '')
            if sid.startswith('http'):
                sc_url = sid
            elif sid.isdigit():
                sc_url = sid
            else:
                sc_url = f'https://soundcloud.com/{sid}'
            if sc_url.startswith('http') and not is_safe_media_url(sc_url):
                raise Exception('Unsafe media URL rejected')
            file_path = self._call_provider(self._core.soundcloud, sc_url, download_dir)
        elif source == 'yandex':
            file_path = self._call_provider(self._core.yandex, source_id, download_dir)
        elif source == 'deezer':
            file_path = self._call_provider(self._core.deezer, source_id, download_dir)
        elif source in ('spotify', 'spotify_album'):
            file_path = self._download_spotify_track(source_id, track_id, download_dir)

        # A provider returning no file is not a transient error: it means the
        # track is unavailable, and waiting would only postpone the same result.
        if not file_path or not os.path.exists(file_path):
            raise Exception(f"Провайдер {source or '?'} не вернул файл")
        return file_path

    def _fetch_with_retry(self, source, source_id, download_dir, track_id, epoch):
        """One admitted attempt; delayed retries return their worker slot."""
        item = getattr(self._worker_context, 'item', {})
        attempt = int(item.get('attempt', 0)) + 1
        self._store.update(track_id, attempt=attempt)
        try:
            file_path = self._fetch_from_provider(source, source_id, download_dir, track_id)
            if file_path and os.path.isfile(file_path):
                track = self._core.db.get_track(track_id)
                defect = _downloaded_file_defect(file_path, (track or {}).get('duration'))
                if defect:
                    self._remove_download_orphan(file_path)
                    raise IncompleteDownload(defect)
            return file_path
        except Exception as error:
            if self._abort_cancelled(track_id, epoch, 'provider-interrupted'):
                return None
            if _is_403_error(error):
                self._invalidate_stream_cache(source, source_id)
            if attempt >= self._RETRY_ATTEMPTS or not self._is_retryable_error(error):
                raise
            item['attempt'] = attempt
            delay = self._RETRY_BASE_DELAY * (2 ** (attempt - 1))
            delay *= random.uniform(1, 1.15)
            # Respect a provider's rate-limit window without occupying a worker.
            response = getattr(error, 'response', None)
            headers = getattr(error, 'headers', None) or getattr(response, 'headers', {}) or {}
            try:
                value = headers.get('Retry-After', 0)
                try:
                    retry_after = float(value)
                except (ValueError, TypeError):
                    from email.utils import parsedate_to_datetime
                    retry_after = parsedate_to_datetime(value).timestamp() - time.time()
                if math.isfinite(retry_after):
                    delay = max(delay, min(300, retry_after))
            except (TypeError, ValueError):
                pass
            raise _RetryLater(error, delay) from error

    def _download_worker(self, item):
        track_id = item['track_id']
        epoch = int(item.get('epoch', 0) or 0)
        generation = int(item.get('generation', 0) or 0)

        def checkpoint():
            if self._is_cancelled(epoch):
                raise DownloadInterrupted()
            with self._lock:
                paused = track_id in self._paused_track_ids
                stale = generation != self._track_generations.get(track_id, 0)
            if paused or stale:
                raise DownloadInterrupted()

        self._worker_context.item = item
        self._worker_context.context = DownloadContext(
            track_id, item['source'], item['source_id'], checkpoint,
            lambda downloaded, total: self._record_progress(track_id, downloaded, total),
        )
        self._worker_context.context.policy = OutputPolicy.from_settings(getattr(self._core, 'settings', None))
        self._worker_context.context.settings = getattr(self._core, 'settings', None)
        try:
            saved = json.loads(self._store.get(track_id).get('options') or '{}')
            if isinstance(saved, dict) and saved:
                from types import SimpleNamespace
                snapshot = SimpleNamespace(get=lambda category, key, default=None: saved.get(key, default))
                self._worker_context.context.policy = OutputPolicy.from_settings(snapshot)
                self._worker_context.context.directory = download_directory(snapshot)
        except (ValueError, TypeError):
            pass
        try:
            self._execute_download_worker(item)
        finally:
            with self._lock:
                state = self._progress_state.pop(track_id, None)
            if state and self._core.db.download_queue_get_status(track_id) != 'completed':
                self._record_progress(track_id, state['downloaded_bytes'], state['total_bytes'], force=True)
                with self._lock:
                    self._progress_state.pop(track_id, None)
            self._worker_context.context = None

    def _execute_download_worker(self, item):
        """Actual download execution, with retries for transient failures."""
        track_id = item['track_id']
        source = item['source']
        source_id = item['source_id']
        epoch = int(item.get('epoch', 0) or 0)

        if self._abort_cancelled(track_id, epoch, 'before-start'):
            return

        try:
            if hasattr(self._core.db, 'download_queue_get_status'):
                status = self._core.db.download_queue_get_status(track_id)
            else:
                with self._core.db._write_lock:
                    cursor = self._core.db.conn.cursor()
                    cursor.execute("SELECT status FROM download_queue WHERE track_id = ?", (track_id,))
                    row = cursor.fetchone()
                    status = (row['status'] if isinstance(row, dict) or hasattr(row, 'keys') else row[0]) if row else None
            if status == 'completed':
                # Already done: still account for the batch so it can finish.
                self._on_batch_task_done(track_id, success=True)
                return
            if self._abort_cancelled(track_id, epoch, 'before-db-mark'):
                return
            if hasattr(self._core.db, 'download_queue_set_downloading'):
                self._core.db.download_queue_set_downloading(track_id)
            else:
                with self._core.db._write_lock:
                    with self._core.db.conn:
                        self._core.db.conn.execute(
                            "UPDATE download_queue SET status = 'downloading' "
                            "WHERE track_id = ? AND status != 'completed'",
                            (track_id,),
                        )
        except Exception:
            pass

        logger.info(f'Starting download for track {track_id}...')
        self._store.update(track_id, error='')
        if self._abort_cancelled(track_id, epoch, 'after-db-mark'):
            return
        self._emit('download_queue_updated', {'track_id': track_id, 'status': 'downloading'})

        if self._abort_cancelled(track_id, epoch, 'before-provider'):
            return

        try:
            download_dir = getattr(self._worker_context.context, 'directory', None) or download_directory(getattr(self._core, 'settings', None))
            os.makedirs(download_dir, exist_ok=True)
            file_path = self._fetch_and_process(source, source_id, download_dir, track_id, epoch)

            if self._abort_cancelled(track_id, epoch, 'after-provider'):
                self._remove_download_orphan(file_path)
                return

            if file_path and os.path.exists(file_path):
                # Integrity gate before the row is marked downloaded. A provider
                # can return a path to a 0-byte, partial or non-audio file (see
                # _require_audio_file), and os.path.exists() alone accepted it:
                # the track then appeared in the library with no audio in it
                # while is_downloaded=1 and download_complete already fired.
                logger.info(f'Download complete: {file_path}')

                with self._lock, self._core.db._write_lock, self._core.db.conn:
                    status = self._core.db.download_queue_get_status(track_id)
                    if self._is_cancelled(epoch) or status not in ('pending', 'downloading'):
                        self._remove_download_orphan(file_path)
                        return
                    cursor = self._core.db.conn.execute('UPDATE tracks SET is_downloaded=1,file_path=? WHERE id=?', (file_path,track_id))
                    if cursor.rowcount != 1:
                        raise ValueError('Трек удалён из библиотеки')
                    self._core.db.conn.execute("UPDATE download_queue SET status='completed' WHERE track_id=?",(track_id,))

                self._emit('library_updated', True)
                self._store.update(track_id, status='completed', error='', resume_on_restart=0,
                                   downloaded_bytes=os.path.getsize(file_path), total_bytes=os.path.getsize(file_path))
                self._emit('download_queue_updated', {'track_id': track_id, 'status': 'completed'})
                self._emit('download_complete', {'track_id': track_id})
                self._on_batch_task_done(track_id, success=True)
            else:
                if source in _SUPPORTED_SOURCES:
                    err_msg = 'Download returned None or file missing.'
                else:
                    # No download provider is wired for this source yet (e.g. vk):
                    # say so instead of blaming the provider for a missing file.
                    err_msg = f"No download provider for source '{source}'."
                logger.error(f'Download worker failed for {track_id}: {err_msg}')
                if hasattr(self._core.db, 'download_queue_set_status'):
                    self._core.db.download_queue_set_status(track_id, 'failed')
                else:
                    try:
                        with self._core.db._write_lock:
                            with self._core.db.conn:
                                self._core.db.conn.execute("UPDATE download_queue SET status = 'failed' WHERE track_id = ?", (track_id,))
                    except Exception:
                        pass
                self._emit('download_failed', {'track_id': track_id, 'error': err_msg})
                self._store.update(track_id, error=err_msg, resume_on_restart=0)
                self._emit('download_queue_updated', {'track_id': track_id, 'status': 'failed'})
                self._on_batch_task_done(track_id, success=False)

        except _RetryLater as retry:
            if self._abort_cancelled(track_id, epoch, 'retry-scheduled'):
                return
            self._store.update(track_id, status='pending', error=redact_download_error(retry.error))
            item['ready_at'] = time.monotonic() + retry.delay
            with self._queue_lock:
                self._queue.append(dict(item))
                self._queue_event.set()
            self._emit('download_queue_updated', {'track_id': track_id, 'status': 'pending'})
        except Exception as e:
            if self._abort_cancelled(track_id, epoch, 'worker-interrupted'):
                return
            if _is_403_error(e):
                self._invalidate_stream_cache(source, source_id)
            logger.error('Download worker failed for %s: %s', track_id, type(e).__name__)
            self._remove_download_orphan(locals().get('file_path'))
            if hasattr(self._core.db, 'download_queue_set_status'):
                try:
                    self._core.db.download_queue_set_status(track_id, 'failed')
                except Exception:
                    pass
            else:
                try:
                    with self._core.db._write_lock:
                        with self._core.db.conn:
                            self._core.db.conn.execute("UPDATE download_queue SET status = 'failed' WHERE track_id = ?", (track_id,))
                except Exception:
                    pass
            details = describe_error(e, 'download')
            self._emit('download_failed', {'track_id': track_id, 'error': details['message'], **details})
            self._store.update(track_id, error=redact_download_error(e), error_code=details['code'], resume_on_restart=0)
            self._emit('download_queue_updated', {'track_id': track_id, 'status': 'failed'})
            self._on_batch_task_done(track_id, success=False)

    def _fetch_and_process(self, source, source_id, directory, track_id, epoch):
        context = self._worker_context.context
        policy = context.policy
        track = self._core.db.get_track(track_id) or {'id': track_id}
        cached_audio = self._complete_cache_path(source, source_id, track, policy)
        setup = getattr(self._core, 'setup', None)
        lease = setup.acquire_download_tools(require_ffmpeg=policy.format != 'source', require_yt_dlp=not cached_audio and source in ('youtube', 'soundcloud', 'spotify', 'spotify_album')) if setup else nullcontext({})
        with lease as tools:
            context.tools = tools
            context.checkpoint()
            self._store.update(track_id, phase='resolving')
            self._emit('download_queue_updated', {'track_id': track_id, 'stage': 'resolving', 'status': 'downloading'})
            cover = self._artwork_pool.submit(fetch_cover, track, context.checkpoint) if policy.embed_cover else None
            path = None
            try:
                # Riff handleDownload also transcodes a complete stream cache:
                # the chosen output format should not require another transfer.
                path = self._reuse_complete_cache(source, source_id, track, directory, context)
                if not path:
                    path = self._fetch_with_retry(source, source_id, directory, track_id, epoch)
                if not path:
                    return None
                context.checkpoint()
                self._store.update(track_id, phase='processing')
                self._emit('download_queue_updated', {'track_id': track_id, 'stage': 'processing', 'status': 'downloading'})
                def artwork():
                    if not cover:
                        return None
                    deadline = time.monotonic() + 7
                    while True:
                        context.checkpoint()
                        try:
                            return cover.result(timeout=max(0, min(.1, deadline - time.monotonic())))
                        except TimeoutError:
                            if cover.done() or time.monotonic() >= deadline:
                                return None
                # Conversion does not need artwork. Let its IO finish in
                # parallel and wait only when the tag writer actually needs it.
                path, warnings = process_download(path, track, policy, context, directory, artwork)
                self._store.update(track_id, warning='; '.join(warnings))
                return path
            except Exception:
                # Pause retains resumable .part files. Published/intermediate
                # audio from a cancelled postprocess must not remain orphaned.
                if path:
                    self._remove_download_orphan(path)
                raise
            finally:
                if cover:
                    cover.cancel()

    def _reuse_complete_cache(self, source, source_id, track, directory, context):
        """Reuse complete native audio, never a temporary URL or partial cache."""
        path = self._complete_cache_path(source, source_id, track, getattr(context, 'policy', None))
        if not path:
            return None
        target = os.path.join(directory, context.stem + os.path.splitext(path)[1])
        complete = False
        try:
            # Cooperative copy keeps pause/cancel responsive for large lossless
            # caches, and never modifies the immutable playback cache itself.
            with open(path, 'rb') as original, open(target, 'wb') as copied:
                while True:
                    context.checkpoint()
                    chunk = original.read(1024 * 1024)
                    if not chunk:
                        break
                    copied.write(chunk)
            context.checkpoint()
            context.progress(os.path.getsize(target), os.path.getsize(target))
            complete = True
            return target
        except (OSError, ValueError, TypeError):
            return None
        finally:
            if not complete:
                try:
                    os.remove(target)
                except OSError:
                    pass

    def _complete_cache_path(self, source, source_id, track, policy=None):
        """Inspect before acquiring tools: cached audio needs no extractor."""
        lookup = getattr(self._core.db, 'get_cached_stream', None)
        if not lookup:
            return None
        try:
            cached = lookup(source, str(source_id), max_age_seconds=2 ** 31 - 1) or {}
            path = cached.get('cached_file_path') or ''
            from utils.cache_manager import stream_cache_stem
            if os.path.splitext(os.path.basename(path))[0] != stream_cache_stem(source, source_id):
                return None
            if getattr(policy, 'format', None) == 'flac' and os.path.splitext(path)[1].lower() not in ('.wav', '.flac'):
                return None
            if _downloaded_file_defect(path, track.get('duration')):
                return None
            return path
        except (OSError, ValueError, TypeError):
            return None

    def _remove_download_orphan(self, path):
        context = getattr(self._worker_context, 'context', None)
        root = getattr(context, 'directory', None) or download_directory(getattr(self._core, 'settings', None))
        self._remove_managed_orphan(path, root)

    @staticmethod
    def _remove_managed_orphan(path, root=None):
        if not path:
            return
        root = os.path.realpath(root or os.path.expanduser('~/.nedotify/downloads'))
        target = os.path.realpath(path)
        try:
            candidates = [target]
            if not target.endswith('.part'):
                candidates.extend([target + '.part', target + '.part.json'])
            else:
                candidates.extend([target + '.json', target[:-5]])
            if target.endswith('.part.json'):
                candidates.extend([target[:-5], target[:-10]])
            for candidate in set(candidates):
                if os.path.isfile(candidate) and os.path.commonpath([root, os.path.realpath(candidate)]) == root:
                    try:
                        os.remove(candidate)
                    except OSError:
                        pass
        except (OSError, ValueError):
            logger.warning('Could not remove cancelled download', exc_info=True)

    def stop(self, drain_timeout: float = 5.0):
        """Stop the queue processor and shut the download pool down.

        ``core/app.py`` closes the database right after this call, so queued work
        is cancelled cooperatively (epoch bump) and already running workers get a
        bounded window to finish their database bookkeeping instead of writing to
        a closed connection.
        """
        self._store.preserve_shutdown()
        self._running = False
        self._cancel_epoch += 1
        self._queue_event.set()
        with self._queue_lock:
            self._queue.clear()
        self._pool.shutdown(wait=False, cancel_futures=True)
        self._artwork_pool.shutdown(wait=False, cancel_futures=True)
        deadline = time.monotonic() + max(0.0, float(drain_timeout))
        for fut in self._running_futures():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                fut.result(timeout=remaining)
            except Exception as e:
                logger.debug(f'Download worker did not finish before shutdown: {e}')
        processor = getattr(self, '_processor_thread', None)
        if processor and processor is not threading.current_thread():
            processor.join(timeout=max(0.0, deadline-time.monotonic()))
        return not self._running_futures()
