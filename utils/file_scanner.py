"""
NeDotify - File Scanner
Recursively scans directories for audio files and adds them to the database.
"""

import os
import math
import threading
from typing import Callable, Optional

from utils.tag_parser import SUPPORTED_FORMATS, parse_tags, save_cover_to_file
from core.database import DatabaseManager

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
        for filepath in file_paths or []:
            if not filepath or not isinstance(filepath, str):
                continue
            norm_path = os.path.normpath(os.path.abspath(filepath))
            try:
                if not os.path.isfile(norm_path) or not is_audio_file(norm_path):
                    continue
            except OSError:
                continue
            track = self._import_file(norm_path)
            if track:
                added.append(track)
        return added

    def scan_single_file(self, filepath: str) -> Optional[dict]:
        """Scan and import a single audio file into the database."""
        if not filepath or not isinstance(filepath, str):
            return None
        norm_path = os.path.normpath(os.path.abspath(filepath))
        try:
            if not os.path.isfile(norm_path) or not is_audio_file(norm_path):
                return None
        except OSError:
            return None
        return self._import_file(norm_path)

    def scan_folder(self, folder_path: str, recursive: bool = True):
        """Scan a folder for audio files (runs in background thread)."""
        if self._scanning:
            return
        if not folder_path or not isinstance(folder_path, str):
            return
        folder_path = os.path.normpath(os.path.abspath(folder_path))
        if not os.path.isdir(folder_path):
            return

        def _scan():
            self._scanning = True
            try:
                files = []

                def _on_walk_error(err):
                    pass

                # Collect all audio files
                if recursive:
                    for root, dirs, filenames in os.walk(folder_path, onerror=_on_walk_error):
                        for fname in filenames:
                            fpath = os.path.normpath(os.path.abspath(os.path.join(root, fname)))
                            try:
                                if os.path.isfile(fpath) and is_audio_file(fpath):
                                    files.append(fpath)
                            except OSError:
                                continue
                else:
                    try:
                        entries = os.listdir(folder_path)
                    except OSError:
                        entries = []
                    for fname in entries:
                        fpath = os.path.normpath(os.path.abspath(os.path.join(folder_path, fname)))
                        try:
                            if os.path.isfile(fpath) and is_audio_file(fpath):
                                files.append(fpath)
                        except OSError:
                            continue

                total = len(files)
                added = []

                for i, filepath in enumerate(files):
                    if not self._scanning:
                        break

                    track = self._import_file(filepath)
                    if track:
                        added.append(track)
                        if self._on_file_found:
                            self._on_file_found(track)

                    if self._on_progress:
                        self._on_progress(i + 1, total, filepath)

                # Update scan folder record
                if getattr(self, "db", None) is not None:
                    self.db.add_scan_folder(folder_path)
                    self.db.update_scan_time(folder_path)

                self._scanning = False
                if self._on_complete:
                    self._on_complete(added)
            finally:
                if getattr(self, "db", None) is not None:
                    try:
                        self.db.close_thread_connection()
                    except Exception:
                        pass

        self._scan_thread = threading.Thread(target=_scan, daemon=True)
        self._scan_thread.start()

    def _import_file(self, filepath: str) -> Optional[dict]:
        """Import a single audio file. Returns track dict or None if already exists."""
        if not filepath or not isinstance(filepath, str):
            return None
        filepath = os.path.normpath(os.path.abspath(filepath))
        try:
            if not os.path.isfile(filepath):
                return None
        except OSError:
            return None

        # Check if already in database
        existing = self.db.get_track_by_path(filepath)
        if existing:
            return None

        # Parse tags
        try:
            tags = parse_tags(filepath)
        except Exception:
            tags = None

        if not tags or not isinstance(tags, dict):
            tags = {}

        base_name = os.path.splitext(os.path.basename(filepath))[0] or "Unknown Track"
        title = tags.get("title")
        if not title or not str(title).strip():
            title = base_name
        else:
            title = str(title).strip()

        artist = tags.get("artist")
        if not artist or not str(artist).strip():
            artist = "Unknown Artist"
        else:
            artist = str(artist).strip()

        album = tags.get("album")
        if not album or not str(album).strip():
            album = "Unknown Album"
        else:
            album = str(album).strip()

        # Sanitize duration
        raw_duration = tags.get("duration")
        duration = 0.0
        if raw_duration is not None:
            try:
                duration = float(raw_duration)
                if math.isnan(duration) or math.isinf(duration) or duration < 0.0:
                    duration = 0.0
            except (ValueError, TypeError):
                duration = 0.0

        # Sanitize bitrate
        raw_bitrate = tags.get("bitrate")
        bitrate = 0
        if raw_bitrate is not None:
            try:
                bitrate = max(0, int(raw_bitrate))
            except (ValueError, TypeError):
                bitrate = 0

        # Sanitize year
        raw_year = tags.get("year")
        year = None
        if raw_year is not None:
            try:
                year = int(str(raw_year)[:4])
            except (ValueError, TypeError, IndexError):
                year = None

        format_ = tags.get("format") or os.path.splitext(filepath)[1].lstrip('.').upper()
        genre = tags.get("genre")

        # Add to database
        track_id = self.db.add_track(
            title=title,
            artist=artist,
            album=album,
            duration=duration,
            file_path=filepath,
            source="local",
            bitrate=bitrate,
            format_=format_,
            genre=genre,
            year=year,
        )

        if not track_id:
            return None

        # Save cover art with track ID
        if tags.get("cover_data"):
            try:
                cover_path = save_cover_to_file(
                    tags["cover_data"], tags.get("cover_mime"),
                    self._covers_dir, track_id
                )
                if cover_path:
                    with self.db.conn:
                        self.db.conn.execute(
                            "UPDATE tracks SET cover_path = ? WHERE id = ?",
                            (cover_path, track_id)
                        )
            except Exception:
                pass

        # Return the full track record
        return self.db.get_track(track_id)

    def rescan_all_folders(self):
        """Rescan all registered folders."""
        folders = self.db.get_scan_folders()
        for folder in folders:
            if folder.get("auto_scan"):
                self.scan_folder(folder["folder_path"])

    def cancel_scan(self):
        """Cancel ongoing scan."""
        self._scanning = False

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
