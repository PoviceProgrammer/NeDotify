"""
NeDotify - File Scanner
Recursively scans directories for audio files and adds them to the database.
"""

import os
import threading
from typing import Callable, Optional

from utils.tag_parser import is_audio_file, parse_tags, save_cover_to_file
from core.database import DatabaseManager


class FileScanner:
    """Scans folders for audio files and imports them into the database."""

    def __init__(self, db: DatabaseManager):
        self.db = db
        self._scanning = False
        self._scan_thread: Optional[threading.Thread] = None
        self._on_progress: Optional[Callable] = None
        self._on_complete: Optional[Callable] = None
        self._on_file_found: Optional[Callable] = None
        # Store covers inside ui/web_new/covers so WebView can resolve them via relative paths
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._covers_dir = os.path.abspath(os.path.join(project_root, "ui", "web_new", "covers"))

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

    def scan_folder(self, folder_path: str, recursive: bool = True):
        """Scan a folder for audio files (runs in background thread)."""
        if self._scanning:
            return

        def _scan():
            self._scanning = True
            files = []

            # Collect all audio files
            if recursive:
                for root, dirs, filenames in os.walk(folder_path):
                    for fname in filenames:
                        fpath = os.path.join(root, fname)
                        if is_audio_file(fpath):
                            files.append(fpath)
            else:
                for fname in os.listdir(folder_path):
                    fpath = os.path.join(folder_path, fname)
                    if os.path.isfile(fpath) and is_audio_file(fpath):
                        files.append(fpath)

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
            self.db.add_scan_folder(folder_path)
            self.db.update_scan_time(folder_path)

            self._scanning = False
            if self._on_complete:
                self._on_complete(added)

        self._scan_thread = threading.Thread(target=_scan, daemon=True)
        self._scan_thread.start()

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
                self.db.conn.execute(
                    "UPDATE tracks SET cover_path = ? WHERE id = ?",
                    (cover_path, track_id)
                )
                self.db.conn.commit()

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
