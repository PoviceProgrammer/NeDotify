"""
NeDotify - File Scanner
Recursively scans directories for audio files and adds them to the database.
"""

import os
import threading
import logging
from typing import Callable, Optional

from utils.tag_parser import SUPPORTED_FORMATS, parse_tags, save_cover_to_file
from core.database import DatabaseManager

logger = logging.getLogger(__name__)

# Single source of truth for "is this file playable audio?".
# Built on top of utils.tag_parser.SUPPORTED_FORMATS (never duplicated here) plus
# the container formats mutagen can still read but tag_parser does not list.
AUDIO_EXTENSIONS = frozenset(SUPPORTED_FORMATS) | frozenset({'.opus', '.alac', '.aiff'})


def is_audio_file(path: str) -> bool:
    """Return True when `path` has a supported audio extension."""
    if not path:
        return False
    return os.path.splitext(str(path).lower())[1] in AUDIO_EXTENSIONS


class FileScanner:
    """Scans folders for audio files and imports them into the database."""

    def __init__(self, db: DatabaseManager):
        self.db = db
        self._scanning = False
        self._stopped = False
        self._scan_generation = 0
        self._scanning_lock = threading.Lock()
        self._scan_thread: Optional[threading.Thread] = None
        self._on_progress: Optional[Callable] = None
        self._on_complete: Optional[Callable] = None
        self._on_file_found: Optional[Callable] = None
        # Store covers inside ~/.nedotify/covers to prevent write-permission errors in packaged builds
        self._covers_dir = os.path.join(os.path.expanduser("~"), ".nedotify", "covers")
        os.makedirs(self._covers_dir, exist_ok=True)

    def scan_files(self, file_paths: list) -> list:
        """Import specific files. Returns list of added track dicts."""
        added = []
        for filepath in file_paths:
            if not is_audio_file(filepath):
                continue
            track = self._import_file(filepath)
            if track:
                added.append(track)
        return added

    def scan_single_file(self, filepath: str) -> Optional[dict]:
        """Scan and import a single audio file into the database."""
        if not is_audio_file(filepath):
            return None
        return self._import_file(filepath)

    def scan_folder(self, folder_path: str, recursive: bool = True) -> bool:
        """Start a background folder scan; return whether it was accepted.

        Progress callbacks receive ``(current, None, filepath)`` because the
        folder is enumerated as a stream and its total is intentionally unknown.
        """
        if not isinstance(folder_path, (str, os.PathLike)) or not os.path.isdir(folder_path):
            return False
        folder_path = os.path.abspath(os.fspath(folder_path))
        with self._scanning_lock:
            active_thread = self._scan_thread
            if self._stopped or self._scanning or (active_thread is not None and active_thread.is_alive()):
                return False
            self._scanning = True
            self._scan_generation += 1
            generation = self._scan_generation

        def _scan():
            try:
                added = []
                current = 0
                for filepath in self._iter_audio_files(folder_path, recursive, generation):
                    if not self._is_generation_active(generation):
                        return
                    track = self._import_file(filepath)
                    # _import_file may spend time decoding tags and writing to
                    # SQLite. A cancellation that arrived during that work must
                    # not publish progress or a stale item callback afterward.
                    if not self._is_generation_active(generation):
                        return
                    current += 1
                    if track:
                        added.append(track)
                        if self._on_file_found:
                            self._on_file_found(track)
                    if self._on_progress:
                        self._on_progress(current, None, filepath)

                # Serialize the terminal database updates against cancel_scan:
                # either cancellation wins and no completed folder is recorded,
                # or the scan commits its completion before cancellation begins.
                with self._scanning_lock:
                    if not self._scanning or self._scan_generation != generation:
                        return
                    self.db.add_scan_folder(folder_path)
                    self.db.update_scan_time(folder_path)
                if self._on_complete:
                    self._on_complete(added)
            except Exception:
                logger.warning("Folder scan failed for %s", folder_path, exc_info=True)
            finally:
                with self._scanning_lock:
                    if generation == self._scan_generation:
                        self._scanning = False
                self.db.close_thread_connection()

        thread = threading.Thread(target=_scan, daemon=True, name="FileScanner")
        with self._scanning_lock:
            # Keep the reservation until start() succeeds; another caller cannot
            # race between marking the scanner active and publishing its thread.
            self._scan_thread = thread
        try:
            thread.start()
        except Exception:
            with self._scanning_lock:
                if generation == self._scan_generation:
                    self._scanning = False
                    self._scan_thread = None
            logger.exception("Could not start folder scan")
            return False
        return True

    def _is_generation_active(self, generation: int) -> bool:
        with self._scanning_lock:
            return self._scanning and self._scan_generation == generation

    def _iter_audio_files(self, folder_path: str, recursive: bool, generation: int):
        """Yield audio paths without retaining an unbounded directory listing."""
        if recursive:
            for root, dirs, filenames in os.walk(folder_path):
                if not self._is_generation_active(generation):
                    return
                # Do not follow symlinked directory trees outside the selected
                # folder or revisit cycles.
                dirs[:] = [name for name in dirs
                           if not os.path.islink(os.path.join(root, name))]
                for filename in filenames:
                    if not self._is_generation_active(generation):
                        return
                    filepath = os.path.join(root, filename)
                    if is_audio_file(filepath):
                        yield filepath
        else:
            try:
                with os.scandir(folder_path) as entries:
                    for entry in entries:
                        if not self._is_generation_active(generation):
                            return
                        if entry.is_file(follow_symlinks=False) and is_audio_file(entry.name):
                            yield entry.path
            except OSError:
                logger.warning("Could not enumerate folder %s", folder_path, exc_info=True)

    def _import_file(self, filepath: str) -> Optional[dict]:
        """Import a single audio file. Returns track dict or None if already exists."""
        # Check if already in database
        existing = self.db.get_track_by_path(filepath)
        if existing:
            return None

        # Parse tags
        tags = parse_tags(filepath)

        # Save cover art
        cover_path = None
        if tags.get("cover_data"):
            # We'll save cover after getting the track ID
            pass

        # Add to database
        track_id = self.db.add_track(
            title=tags["title"],
            artist=tags["artist"],
            album=tags["album"],
            duration=tags["duration"],
            file_path=filepath,
            source="local",
            bitrate=tags["bitrate"],
            format_=tags["format"],
            genre=tags["genre"],
            year=tags["year"],
        )

        # Save cover art with track ID
        if tags.get("cover_data"):
            cover_path = save_cover_to_file(
                tags["cover_data"], tags["cover_mime"],
                self._covers_dir, track_id
            )
            if cover_path:
                self.db.update_track(track_id, cover_path=cover_path)

        # Return the full track record
        return self.db.get_track(track_id)

    def rescan_all_folders(self):
        """Rescan all registered folders."""
        folders = self.db.get_scan_folders()
        for folder in folders:
            if folder.get("auto_scan"):
                self.scan_folder(folder["folder_path"])

    def cancel_scan(self, timeout: float = 5.0) -> bool:
        """Cancel a scan and join its worker up to ``timeout`` seconds."""
        with self._scanning_lock:
            self._scanning = False
            self._scan_generation += 1
            thread = self._scan_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(max(0.0, float(timeout)))
            return not thread.is_alive()
        return True

    def stop(self, timeout: float = 5.0) -> bool:
        """Shutdown hook: prevent new work and wait for the scan worker to exit."""
        with self._scanning_lock:
            self._stopped = True
        return self.cancel_scan(timeout=timeout)

    # ─── Event Binding ───

    def on_progress(self, callback: Callable):
        """callback(current: int, total: int, filepath: str)"""
        self._on_progress = callback

    def on_complete(self, callback: Callable):
        """callback(added_tracks: list)"""
        self._on_complete = callback

    def on_file_found(self, callback: Callable):
        """callback(track: dict)"""
        self._on_file_found = callback
