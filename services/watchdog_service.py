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
        self._stop = threading.Event()
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
            try:
                stat = os.stat(file_path)
                self._pending_files[file_path] = (time.monotonic(), (stat.st_size, stat.st_mtime_ns))
            except OSError:
                pass

    def _process_pending(self):
        while self._running:
            if self._stop.wait(1):
                break
            now = time.monotonic()
            ready_files = []
            with self._lock:
                for path, (timestamp, signature) in list(self._pending_files.items()):
                    if now - timestamp >= 3.0:
                        try:
                            stat = os.stat(path)
                            current = (stat.st_size, stat.st_mtime_ns)
                            if current != signature:
                                self._pending_files[path] = (now, current)
                                continue
                            with open(path, 'rb'):
                                ready_files.append(path)
                                del self._pending_files[path]
                        except IOError as e:
                            logger.debug(f'Watchdog: {path} still locked by the writer: {e}')
                            self._pending_files.pop(path, None)
            for path in ready_files:
                try:
                    self.callback(path)
                except Exception as e:
                    logger.error(f'Watchdog import error for {path}: {e}', exc_info=True)

    def stop(self):
        self._running = False
        self._stop.set()
        if self._processor_thread is not threading.current_thread():
            self._processor_thread.join(timeout=2)


class WatchdogService:

    def __init__(self, app_core):
        self._core = app_core
        self._watched_paths = set()
        self._started = False
        if HAS_WATCHDOG:
            self.observer = Observer()
            self.handler = None
        else:
            self.observer = None
            self.handler = None

    def start(self):
        if not HAS_WATCHDOG:
            return None
        if not self.observer:
            return None
        if self._started:
            return None
        if not self._core.db.get_scan_folders():
            return None
        self.handler = AudioFileHandler(self._on_new_file)
        self._sync_folders()
        self.observer.start()
        self._started = True

    def stop(self):
        if self.handler:
            self.handler.stop()
        if self.observer and self._started:
            self.observer.stop()
            self.observer.join(timeout=3)
            self._started = False

    def _sync_folders(self):
        folders = self._core.db.get_scan_folders()
        db_paths = {f['folder_path'] for f in folders if f.get('auto_scan')}
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
        lufs = getattr(self._core, 'lufs_scanner', None)
        if lufs is not None:
            lufs.enqueue_path(filepath)
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
