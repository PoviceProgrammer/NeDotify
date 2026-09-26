"""
NeDotify - Background Downloader
Queues and manages downloading audio files and metadata.
"""

import os
import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

class DownloadManager:
    def __init__(self, app_core):
        self._core = app_core
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='download_worker')
        self._running = True
        self._queue = []
        self._queue_lock = threading.Lock()
        self._queue_event = threading.Event()
        self._lock = threading.Lock()  # guards batch counters (_batch_active/_batch_completed/_batch_total/_batch_failed)

        self._batch_total = 0
        self._batch_completed = 0
        self._batch_failed = 0
        self._batch_active = False
        self._futures = []
        self._futures_lock = threading.Lock()

        self._processor_thread = threading.Thread(target=self._process_queue, daemon=True)
        self._processor_thread.start()

        self._init_db_table()
        self._resume_pending_downloads()

    def _emit(self, event_name, data=None):
        """Emit via api._emit (same channel as download_complete)."""
        try:
            api = getattr(self._core, 'api', None)
            emitter = getattr(api, '_emit', None) if api else None
            if callable(emitter):
                emitter(event_name, data)
            elif api and hasattr(api, 'emit_event'):
                api.emit_event(event_name, data if isinstance(data, dict) else {})
        except Exception:
            logger.debug("downloader emit %s failed", event_name, exc_info=True)

    def start_batch(self, total: int):
        """Initialize batch download tracking."""
        with self._lock:
            self._batch_total = total
            self._batch_completed = 0
            self._batch_failed = 0
            self._batch_active = total > 0

    def _decrement_batch_total_for_dedup(self):
        """Shrink the batch denominator when a queued item turns out to be a duplicate."""
        with self._lock:
            if not self._batch_active:
                return
            if self._batch_total > 0:
                self._batch_total = max(0, self._batch_total - 1)
            if self._batch_total == 0 or self._batch_completed >= self._batch_total:
                if self._batch_total == 0:
                    self._batch_active = False
                    self._emit('batch_download_finished', {
                        'total': 0,
                        'completed': self._batch_completed,
                        'failed': self._batch_failed,
                    })

    def _on_batch_task_done(self, track_id, success: bool):
        """Account for one finished worker (success or failure) and emit progress."""
        with self._lock:
            if not self._batch_active:
                return
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
        """Cancel ongoing batch download and clear queue."""
        with self._queue_lock:
            self._queue.clear()
        with self._futures_lock:
            for fut in list(self._futures):
                try:
                    fut.cancel()
                except Exception:
                    pass
            self._futures.clear()
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
                        self._core.db.conn.execute("UPDATE download_queue SET status = 'cancelled' WHERE status = 'pending'")
        except Exception:
            pass
        self._emit('batch_download_cancelled', True)
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
                    self.queue_download(row['track_id'], row['source'], row['source_id'], from_db=True)
                else:
                    self.queue_download(row[0], row[1], row[2], from_db=True)
        except Exception as e:
            logger.error(f'Failed to resume downloads: {e}')

    def queue_download(self, track_id, source, source_id, from_db=False):
        """Queue a track for download (at most one row per track). Returns True if queued."""
        if not from_db:
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

        with self._queue_lock:
            if not any(item['track_id'] == track_id for item in self._queue):
                self._queue.append({
                    'track_id': track_id,
                    'source': source,
                    'source_id': source_id,
                })
                self._queue_event.set()
            else:
                # In-memory duplicate: shrink batch denominator so the batch can finish.
                self._decrement_batch_total_for_dedup()
                return False
        logger.info(f'Queued download for track {track_id} from {source}:{source_id}')
        return True

    def _process_queue(self):
        """Background thread checking the queue."""
        while self._running:
            item = None
            with self._queue_lock:
                if self._queue:
                    item = self._queue.pop(0)
                else:
                    self._queue_event.clear()

            if item:
                try:
                    fut = self._pool.submit(self._download_worker, item)
                    with self._futures_lock:
                        self._futures.append(fut)
                        # Prune finished futures so the list does not grow unbounded.
                        self._futures = [f for f in self._futures if not f.done()]
                except Exception as e:
                    logger.error(f'Failed to submit download worker: {e}')
                    self._on_batch_task_done(item.get('track_id'), success=False)
            else:
                self._queue_event.wait(timeout=1.0)

    def _download_spotify_track(self, source_id, track_id, download_dir):
        """Resolve a Spotify track to audio via YouTube and download it.

        Spotify tracks carry ``source_id="ytsearch1: Artist - Title"`` which
        ``YouTubeService.download_audio_sync`` already understands (yt-dlp
        ``ytsearch`` URL). Anything else (e.g. ``spotify_123`` or empty) is
        resolved via title/artist from the ``tracks`` table: first through
        ``TrackResolver``, falling back to a plain ``ytsearch1:`` query.
        """
        sid = str(source_id or '').strip()
        if sid.startswith('ytsearch'):
            return self._core.youtube.download_audio_sync(sid, download_dir)

        title, artist = '', ''
        try:
            if hasattr(self._core.db, '_write_lock'):
                with self._core.db._write_lock:
                    cursor = self._core.db.conn.cursor()
                    cursor.execute("SELECT title, artist FROM tracks WHERE id = ?", (track_id,))
                    row = cursor.fetchone()
            else:
                cursor = self._core.db.conn.cursor()
                cursor.execute("SELECT title, artist FROM tracks WHERE id = ?", (track_id,))
                row = cursor.fetchone()
            if row is not None:
                if hasattr(row, 'keys'):
                    title = row['title'] or ''
                    artist = row['artist'] or ''
                else:
                    title = row[0] or ''
                    artist = row[1] or ''
        except Exception as e:
            logger.debug(f'Spotify resolve: failed to load track {track_id} metadata: {e}')

        # If the queue payload had no usable title, try parsing "Artist - Title"
        # out of a non-ytsearch source_id before giving up.
        query_hint = sid
        if not title and sid and not sid.startswith('spotify_'):
            query_hint = sid

        # 1. Preferred path: TrackResolver (local -> soundcloud -> youtube).
        try:
            from services.track_resolver import TrackResolver
            resolver = TrackResolver(
                db=getattr(self._core, 'db', None),
                youtube_service=getattr(self._core, 'youtube', None),
            )
            resolved = resolver.resolve_track(title or query_hint, artist or '')
            if isinstance(resolved, dict):
                r_source = resolved.get('source')
                r_id = str(resolved.get('source_id') or '').strip()
                if r_source == 'youtube' and r_id:
                    return self._core.youtube.download_audio_sync(r_id, download_dir)
                if r_source == 'soundcloud' and r_id:
                    if str(r_id).startswith('http'):
                        sc_url = str(r_id)
                    elif str(r_id).isdigit():
                        sc_url = str(r_id)
                    else:
                        sc_url = f'https://soundcloud.com/{r_id}'
                    return self._core.soundcloud.download_audio_sync(sc_url, download_dir)
        except Exception as e:
            logger.debug(f'Spotify TrackResolver fallback for track {track_id}: {e}')

        # 2. Fallback: direct YouTube search, then download top hit.
        try:
            if title or artist:
                query = f"{artist} {title}".strip()
            else:
                query = query_hint.strip()
            if not query:
                raise Exception('No title/artist metadata to resolve Spotify track')
            results = self._core.youtube.search_sync(query, limit=1)
            if results:
                top_id = str(results[0].get('source_id') or '').strip()
                if top_id:
                    return self._core.youtube.download_audio_sync(top_id, download_dir)
            # Last resort: let yt-dlp handle the ytsearch query itself.
            return self._core.youtube.download_audio_sync(f"ytsearch1: {query}", download_dir)
        except Exception:
            raise

    def _download_worker(self, item):
        """Actual download execution."""
        track_id = item['track_id']
        source = item['source']
        source_id = item['source_id']

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

        download_dir = os.path.join(os.path.expanduser('~'), '.nedotify', 'downloads')
        os.makedirs(download_dir, exist_ok=True)

        try:
            file_path = None

            if source == 'youtube':

                file_path = self._core.youtube.download_audio_sync(source_id, download_dir)
            elif source == 'soundcloud':
                sid = str(source_id or '')
                if sid.startswith('http'):
                    sc_url = sid
                elif sid.isdigit():
                    sc_url = sid
                else:
                    sc_url = f'https://soundcloud.com/{sid}'
                file_path = self._core.soundcloud.download_audio_sync(sc_url, download_dir)
            elif source == 'yandex':
                file_path = self._core.yandex.download_audio_sync(source_id, download_dir)
            elif source in ('spotify', 'spotify_album'):
                file_path = self._download_spotify_track(source_id, track_id, download_dir)

            if file_path and os.path.exists(file_path):
                logger.info(f'Download complete: {file_path}')

                try:
                    self._core.db.mark_track_downloaded(track_id, file_path)
                except Exception as me:
                    logger.error(f'mark_track_downloaded failed for {track_id}: {me}')
                    with self._core.db._write_lock:
                        with self._core.db.conn:
                            self._core.db.conn.execute(
                                "UPDATE tracks SET is_downloaded = 1, file_path = ? WHERE id = ?",
                                (file_path, track_id),
                            )
                if hasattr(self._core.db, 'download_queue_set_status'):
                    self._core.db.download_queue_set_status(track_id, 'completed')
                else:
                    with self._core.db._write_lock:
                        with self._core.db.conn:
                            self._core.db.conn.execute("UPDATE download_queue SET status = 'completed' WHERE track_id = ?", (track_id,))

                self._emit('library_updated', True)
                self._emit('download_complete', {'track_id': track_id})
                self._on_batch_task_done(track_id, success=True)
            else:
                err_msg = 'Download returned None or file missing.'
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
                self._on_batch_task_done(track_id, success=False)

        except Exception as e:
            logger.error(f'Download worker failed for {track_id}: {e}')
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
            self._emit('download_failed', {'track_id': track_id, 'error': str(e)})
            self._on_batch_task_done(track_id, success=False)

    def stop(self):
        self._running = False
        self._queue_event.set()
        self._pool.shutdown(wait=False)