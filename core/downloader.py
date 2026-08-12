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


        self._processor_thread = threading.Thread(target=self._process_queue, daemon=True)
        self._processor_thread.start()


        self._init_db_table()
        self._resume_pending_downloads()

    def _init_db_table(self):
        """Create download queue table if missing."""
        try:
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
            self._core.db.conn.commit()
        except Exception as e:
            logger.error(f'Failed to init download_queue table: {e}')

    def _resume_pending_downloads(self):
        try:
            cursor = self._core.db.conn.cursor()
            cursor.execute("SELECT track_id, source, source_id FROM download_queue WHERE status IN ('pending', 'downloading')")
            for row in cursor.fetchall():
                self.queue_download(row['track_id'], row['source'], row['source_id'], from_db=True)
        except Exception as e:
            logger.error(f'Failed to resume downloads: {e}')

    def queue_download(self, track_id, source, source_id, from_db=False):
        """Queue a track for download."""
        if not from_db:
            try:
                self._core.db.conn.execute(
                    'INSERT INTO download_queue (track_id, source, source_id) VALUES (?, ?, ?)',
                    (track_id, source, source_id),
                )
                self._core.db.conn.commit()
            except Exception as e:
                logger.error(f'Failed to insert download queue record: {e}')

        with self._queue_lock:

            if not any(item['track_id'] == track_id for item in self._queue):
                self._queue.append({
                    'track_id': track_id,
                    'source': source,
                    'source_id': source_id,
                })
        logger.info(f'Queued download for track {track_id} from {source}:{source_id}')

    def _process_queue(self):
        """Background thread checking the queue."""
        while self._running:
            item = None
            with self._queue_lock:
                if self._queue:
                    item = self._queue.pop(0)

            if item:

                self._pool.submit(self._download_worker, item)

            time.sleep(1)

    def _download_worker(self, item):
        """Actual download execution."""
        track_id = item['track_id']
        source = item['source']
        source_id = item['source_id']

        try:
            self._core.db.conn.execute("UPDATE download_queue SET status = 'downloading' WHERE track_id = ?", (track_id,))
            self._core.db.conn.commit()
        except: pass

        logger.info(f'Starting download for track {track_id}...')

        download_dir = os.path.join(os.path.expanduser('~'), '.nedotify', 'downloads')
        os.makedirs(download_dir, exist_ok=True)

        try:
            file_path = None

            if source == 'youtube':

                file_path = self._core.youtube.download_audio_sync(source_id, download_dir)
            elif source == 'soundcloud':
                sc_url = f'https://soundcloud.com/{source_id}' if not str(source_id).isdigit() else str(source_id)
                file_path = self._core.soundcloud.download_audio_sync(sc_url, download_dir)
            elif source == 'yandex':
                file_path = self._core.yandex.download_audio_sync(source_id, download_dir)

            if file_path and os.path.exists(file_path):
                logger.info(f'Download complete: {file_path}')

                self._core.db.conn.execute(
                    "UPDATE tracks SET is_downloaded = 1, file_path = ? WHERE id = ?",
                    (file_path, track_id),
                )
                self._core.db.conn.execute("UPDATE download_queue SET status = 'completed' WHERE track_id = ?", (track_id,))
                self._core.db.conn.commit()

                if hasattr(self._core, 'api') and getattr(self._core.api, '_emit', None):
                    self._core.api._emit('library_updated', True)
                    self._core.api._emit('download_complete', {'track_id': track_id})
            else:
                raise Exception('Download returned None or file missing.')

        except Exception as e:
            logger.error(f'Download worker failed for {track_id}: {e}')
            try:
                self._core.db.conn.execute("UPDATE download_queue SET status = 'failed' WHERE track_id = ?", (track_id,))
                self._core.db.conn.commit()
            except: pass

    def stop(self):
        self._running = False
        self._pool.shutdown(wait=False)