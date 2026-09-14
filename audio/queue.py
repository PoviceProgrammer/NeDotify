"""
AURA Music - Playback Queue Manager
Manages track queue, shuffle, repeat modes.
"""

import random
import threading
from typing import Optional


class PlaybackQueue:
    """Manages the playback queue with shuffle and repeat support."""

    def __init__(self):
        self._lock = threading.RLock()
        self._tracks: list = []  # List of track dicts
        self._original_order: list = []  # Original order before shuffle
        self._current_index: int = -1
        self._shuffle: bool = False
        self._repeat: str = "off"  # off, one, all
        self._history_stack: list = []  # For back navigation

    @property
    def current_track(self) -> Optional[dict]:
        """Get the currently playing track."""
        with self._lock:
            if 0 <= self._current_index < len(self._tracks):
                return self._tracks[self._current_index]
            return None

    def update_current(self, track: dict):
        """Update the currently playing track."""
        with self._lock:
            if 0 <= self._current_index < len(self._tracks):
                self._tracks[self._current_index] = track

    @property
    def current_index(self) -> int:
        with self._lock:
            return self._current_index

    @property
    def tracks(self) -> list:
        with self._lock:
            return self._tracks.copy()

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._tracks)

    @property
    def is_empty(self) -> bool:
        with self._lock:
            return len(self._tracks) == 0

    @staticmethod
    def _track_key(track: dict) -> tuple:
        if not isinstance(track, dict):
            return (None, None)
        return (track.get("source"), str(track.get("source_id") or track.get("id") or track.get("url") or ""))

    @property
    def shuffle(self) -> bool:
        with self._lock:
            return self._shuffle

    @shuffle.setter
    def shuffle(self, enabled: bool):
        with self._lock:
            if enabled and not self._shuffle:
                # Save original order and shuffle
                self._original_order = self._tracks.copy()
                current = self.current_track
                current_key = self._track_key(current) if current else None
                remaining = [t for i, t in enumerate(self._tracks) if i != self._current_index]
                random.shuffle(remaining)
                if current:
                    self._tracks = [current] + remaining
                    self._current_index = 0
                else:
                    self._tracks = remaining
            elif not enabled and self._shuffle:
                # Restore original order without losing newly added tracks
                current = self.current_track
                current_key = self._track_key(current) if current else None
                current_keys = {self._track_key(t) for t in self._tracks}
                restored = [t for t in self._original_order if self._track_key(t) in current_keys]
                restored_keys = {self._track_key(t) for t in restored}
                for t in self._tracks:
                    if self._track_key(t) not in restored_keys:
                        restored.append(t)
                        restored_keys.add(self._track_key(t))
                self._tracks = restored
                if current_key:
                    found_idx = -1
                    for idx, t in enumerate(self._tracks):
                        if self._track_key(t) == current_key:
                            found_idx = idx
                            break
                    self._current_index = found_idx if found_idx >= 0 else (0 if self._tracks else -1)
                else:
                    self._current_index = 0 if self._tracks else -1
            self._shuffle = enabled

    @property
    def repeat(self) -> str:
        with self._lock:
            return self._repeat

    @repeat.setter
    def repeat(self, mode: str):
        with self._lock:
            if mode in ("off", "one", "all"):
                self._repeat = mode

    def set_tracks(self, tracks: list, start_index: int = 0):
        """Set the queue with a list of tracks."""
        with self._lock:
            self._tracks = tracks.copy()
            self._original_order = tracks.copy()
            self._current_index = min(start_index, len(tracks) - 1) if tracks else -1
            self._history_stack.clear()
            if self._shuffle:
                current = self.current_track
                remaining = [t for i, t in enumerate(self._tracks) if i != self._current_index]
                random.shuffle(remaining)
                if current:
                    self._tracks = [current] + remaining
                    self._current_index = 0

    def add_track(self, track: dict, play_next: bool = False):
        """Add a track to the queue."""
        with self._lock:
            if play_next and self._current_index >= 0:
                self._tracks.insert(self._current_index + 1, track)
                if self._original_order:
                    orig_curr = self.current_track
                    orig_curr_key = self._track_key(orig_curr) if orig_curr else None
                    found_orig_idx = -1
                    if orig_curr_key:
                        for idx, t in enumerate(self._original_order):
                            if self._track_key(t) == orig_curr_key:
                                found_orig_idx = idx
                                break
                    if found_orig_idx >= 0:
                        self._original_order.insert(found_orig_idx + 1, track)
                    else:
                        self._original_order.append(track)
            else:
                self._tracks.append(track)
                if self._original_order:
                    self._original_order.append(track)
            if self._current_index < 0 and len(self._tracks) == 1:
                self._current_index = 0

    def add_tracks(self, tracks: list):
        """Batch add multiple tracks to the queue under a single lock."""
        if not tracks or not isinstance(tracks, list):
            return
        with self._lock:
            for track in tracks:
                if not isinstance(track, dict):
                    continue
                self._tracks.append(track)
                if self._original_order:
                    self._original_order.append(track)
            if self._current_index < 0 and len(self._tracks) > 0:
                self._current_index = 0

    def remove_track(self, index: int):
        """Remove a track from the queue by index."""
        with self._lock:
            if 0 <= index < len(self._tracks):
                track = self._tracks.pop(index)
                if self._original_order:
                    target_key = self._track_key(track)
                    self._original_order = [t for t in self._original_order if self._track_key(t) != target_key]
                if len(self._tracks) == 0:
                    self._current_index = -1
                elif index < self._current_index:
                    self._current_index -= 1
                elif index == self._current_index:
                    self._current_index = min(self._current_index, len(self._tracks) - 1)

    def move_track(self, old_index: int, new_index: int):
        """Move a track in the queue from old_index to new_index."""
        with self._lock:
            if 0 <= old_index < len(self._tracks) and 0 <= new_index < len(self._tracks):
                if old_index == new_index:
                    return
                
                # Handle current_index shifting
                track = self._tracks.pop(old_index)
                self._tracks.insert(new_index, track)
                
                # Update current_index if we moved the currently playing track
                if old_index == self._current_index:
                    self._current_index = new_index
                # Update current_index if we moved a track from before the current track to after it
                elif old_index < self._current_index and new_index >= self._current_index:
                    self._current_index -= 1
                # Update current_index if we moved a track from after the current track to before it
                elif old_index > self._current_index and new_index <= self._current_index:
                    self._current_index += 1

    def next_track(self) -> Optional[dict]:
        """Move to the next track. Returns the track or None."""
        with self._lock:
            if self.is_empty:
                return None

            if self._repeat == "one":
                return self.current_track

            # End of queue without repeat: stay where we are and report None.
            # Advancing first used to push a stale index onto the history
            # stack, so a later prev_track() jumped backwards unexpectedly.
            if self._current_index >= len(self._tracks) - 1:
                if self._repeat != "all":
                    return None
                if self.current_track:
                    self._history_stack.append(self._current_index)
                if self._shuffle:
                    current = self._tracks[0] if self._tracks else None
                    random.shuffle(self._tracks)
                    if current:
                        try:
                            idx = self._tracks.index(current)
                            self._tracks[0], self._tracks[idx] = self._tracks[idx], self._tracks[0]
                        except ValueError:
                            pass
                self._current_index = 0
                return self.current_track

            if self.current_track:
                self._history_stack.append(self._current_index)

            self._current_index += 1
            return self.current_track

    def previous_track(self) -> Optional[dict]:
        """Move to the previous track. Returns the track or None."""
        with self._lock:
            if self.is_empty:
                return None

            if self._history_stack:
                self._current_index = self._history_stack.pop()
            else:
                self._current_index = max(0, self._current_index - 1)

            return self.current_track

    # Historical alias: callers exist under both spellings.
    prev_track = previous_track

    def jump_to(self, index: int) -> Optional[dict]:
        """Jump to a specific track in the queue."""
        with self._lock:
            if 0 <= index < len(self._tracks):
                if self.current_track:
                    self._history_stack.append(self._current_index)
                self._current_index = index
                return self.current_track
            return None

    def clear(self):
        """Clear the queue."""
        with self._lock:
            self._tracks.clear()
            self._original_order.clear()
            self._history_stack.clear()
            self._current_index = -1

    def get_upcoming(self, count: int = 10) -> list:
        """Get the next N upcoming tracks."""
        with self._lock:
            start = self._current_index + 1
            return self._tracks[start:start + count]

    def to_serializable(self) -> dict:
        """Serialize queue state for session persistence."""
        with self._lock:
            return {
                "track_ids": [t.get("id") for t in self._tracks if t.get("id")],
                "current_index": self._current_index,
                "shuffle": self._shuffle,
                "repeat": self._repeat,
            }

    def get_queue_track_ids(self) -> list:
        """Get list of track IDs in queue."""
        with self._lock:
            return [t.get("id") for t in self._tracks if t.get("id")]
