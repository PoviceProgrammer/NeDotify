"""
NeDotify - Watchdog Service
Monitors registered directories for new audio files.
"""

import os
import time
import logging
import threading

from utils.file_scanner import is_audio_file

logger = logging.getLogger(__name__)

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False
    logger.warning('watchdog module not available. Folder watching disabled.')
    Observer = object
    FileSystemEventHandler = object


class AudioFileHandler(FileSystemEventHandler):

    def __init__(self, callback):
        self.callback = callback
        self._pending_files = {}
        self._lock = threading.Lock()
        self._running = True
        self._processor_thread = threading.Thread(target=self._process_pending, daemon=True)
        self._processor_thread.start()

    def on_created(self, event):
        if not event.is_directory and is_audio_file(event.src_path):
            self._add_pending(event.src_path)

    def on_modified(self, event):
        if not event.is_directory and is_audio_file(event.src_path):
            self._add_pending(event.src_path)

    def on_moved(self, event):
        if not event.is_directory and is_audio_file(event.dest_path):
            self._add_pending(event.dest_path)

    def _add_pending(self, file_path):
        with self._lock:
            self._pending_files[file_path] = time.time()

    def _process_pending(self):
        while self._running:
            time.sleep(1)
            now = time.time()
            ready_files = []
            with self._lock:
                for path, timestamp in list(self._pending_files.items()):
                    if now - timestamp >= 3.0:
                        try:
                            with open(path, 'rb'):
                                ready_files.append(path)
                                del self._pending_files[path]
                        except IOError as e:
                            logger.debug(f'Watchdog: {path} still locked by the writer: {e}')
                            self._pending_files[path] = now
            for path in ready_files:
                try:
                    self.callback(path)
                except Exception as e:
                    logger.error(f'Watchdog import error for {path}: {e}', exc_info=True)

    def stop(self):
        self._running = False


class WatchdogService:

    def __init__(self, app_core):
        self._core = app_core
        self._watched_paths = set()
        if HAS_WATCHDOG:
            self.observer = Observer()
            self.handler = AudioFileHandler(self._on_new_file)
        else:
            self.observer = None
            self.handler = None

    def start(self):
        if not HAS_WATCHDOG:
            return None
        if not self.observer:
            return None
        self._sync_folders()
        self.observer.start()

    def stop(self):
        self.handler.stop()
        self.observer.stop()
        self.observer.join()

    def _sync_folders(self):
        folders = self._core.db.get_scan_folders()
        db_paths = set(f for f in folders if f.get('auto_scan'))
        for path in db_paths:
            if path not in self._watched_paths:
                if not os.path.isdir(path):
                    continue
                try:
                    self.observer.schedule(self.handler, path, recursive=True)
                    self._watched_paths.add(path)
                    logger.info(f'Watchdog watching: {path}')
                except Exception as e:
                    logger.warning(f'Failed to watch {path}: {e}')

    def _on_new_file(self, filepath):
        logger.info(f'Watchdog detected new audio file: {filepath}')
        if not hasattr(self._core, 'scanner'):
            return None
        track = self._core.scanner._import_file(filepath)
        if not track:
            return None
        if not hasattr(self._core, 'api'):
            return None
        if not getattr(self._core.api, '_emit', None):
            return None
        self._core.api._emit('library_updated', True)