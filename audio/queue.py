"""
NeDotify - Playback Queue Manager
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
        self._counter: int = 0

    def _make_entry(self, track: dict, force_copy: bool = False) -> dict:
        entry = dict(track) if force_copy else track
        self._counter += 1
        entry["_queue_item_id"] = self._counter
        return entry

    def snapshot(self):
        """Read the queue, index and current track from the same instant."""
        with self._lock:
            tracks = [dict(track) for track in self._tracks]
            index = self._current_index
            return {'tracks': tracks, 'current_index': index,
                    'current_track': tracks[index] if 0 <= index < len(tracks) else None,
                    'shuffle': self._shuffle, 'repeat': self._repeat,
                    'history': [dict(self._tracks[i], queue_index=i) for i in self._history_stack[-200:]
                                if 0 <= i < len(self._tracks)]}

    @property
    def current_track(self) -> Optional[dict]:
        """Get the currently playing track."""
        with self._lock:
            if 0 <= self._current_index < len(self._tracks):
                return self._tracks[self._current_index]
            return None

    def update_current(self, track: dict):
        """Update the currently playing track."""
        if not isinstance(track, dict):
            return
        with self._lock:
            if 0 <= self._current_index < len(self._tracks):
                old_track = self._tracks[self._current_index]
                target_qid = old_track.get("_queue_item_id")
                if target_qid is not None and "_queue_item_id" not in track:
                    track["_queue_item_id"] = target_qid
                self._tracks[self._current_index] = track
                if self._original_order:
                    for idx, t in enumerate(self._original_order):
                        if (target_qid is not None and t.get("_queue_item_id") == target_qid) or t is old_track or self._track_key(t) == self._track_key(old_track):
                            self._original_order[idx] = track
                            break

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
            self._history_stack.clear()
            if enabled and not self._shuffle:
                # Save original order and shuffle
                self._original_order = self._tracks.copy()
                current = self.current_track
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
                current_qid = current.get("_queue_item_id") if current else None
                current_qids = {t.get("_queue_item_id") for t in self._tracks if t.get("_queue_item_id") is not None}
                if current_qids:
                    restored = [t for t in self._original_order if t.get("_queue_item_id") in current_qids]
                    restored_qids = {t.get("_queue_item_id") for t in restored}
                    for t in self._tracks:
                        qid = t.get("_queue_item_id")
                        if qid not in restored_qids:
                            restored.append(t)
                            restored_qids.add(qid)
                    self._tracks = restored
                    if current_qid is not None:
                        found_idx = -1
                        for idx, t in enumerate(self._tracks):
                            if t.get("_queue_item_id") == current_qid:
                                found_idx = idx
                                break
                        self._current_index = found_idx if found_idx >= 0 else (0 if self._tracks else -1)
                    else:
                        self._current_index = 0 if self._tracks else -1
                else:
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
            seen_ids = set()
            entries = []
            for t in (tracks or []):
                if not isinstance(t, dict):
                    continue
                force_copy = id(t) in seen_ids
                seen_ids.add(id(t))
                entries.append(self._make_entry(t, force_copy=force_copy))
            self._tracks = entries.copy()
            self._original_order = entries.copy()
            try:
                start_index = int(start_index)
            except (TypeError, ValueError):
                start_index = 0
            n = len(self._tracks)
            if n > 0 and -n <= start_index < 0:
                start_index = n + start_index
            self._current_index = max(0, min(start_index, n - 1)) if n > 0 else -1
            self._history_stack.clear()
            if self._shuffle:
                current = self.current_track
                remaining = [t for i, t in enumerate(self._tracks) if i != self._current_index]
                random.shuffle(remaining)
                if current:
                    self._tracks = [current] + remaining
                    self._current_index = 0

    def add_track(self, track: dict, play_next: bool = False) -> bool:
        """Add a track to the queue."""
        if not isinstance(track, dict):
            return False
        with self._lock:
            force_copy = any(t is track for t in self._tracks)
            entry = self._make_entry(track, force_copy=force_copy)
            if play_next and self._current_index >= 0:
                insert_idx = self._current_index + 1
                self._tracks.insert(insert_idx, entry)
                self._history_stack = [
                    i + 1 if i >= insert_idx else i
                    for i in self._history_stack
                ]
                if self._original_order:
                    orig_curr = self.current_track
                    orig_curr_qid = orig_curr.get("_queue_item_id") if orig_curr else None
                    found_orig_idx = -1
                    if orig_curr_qid is not None:
                        for idx, t in enumerate(self._original_order):
                            if t.get("_queue_item_id") == orig_curr_qid:
                                found_orig_idx = idx
                                break
                    if found_orig_idx < 0 and orig_curr:
                        orig_curr_key = self._track_key(orig_curr)
                        for idx, t in enumerate(self._original_order):
                            if self._track_key(t) == orig_curr_key:
                                found_orig_idx = idx
                                break
                    if found_orig_idx >= 0:
                        self._original_order.insert(found_orig_idx + 1, entry)
                    else:
                        self._original_order.append(entry)
            else:
                self._tracks.append(entry)
                if self._original_order:
                    self._original_order.append(entry)
            if self._current_index < 0 and len(self._tracks) == 1:
                self._current_index = 0
            return True

    def add_tracks(self, tracks: list):
        """Batch add multiple tracks to the queue under a single lock."""
        if not tracks or not isinstance(tracks, list):
            return
        with self._lock:
            seen_ids = {id(t) for t in self._tracks}
            for track in tracks:
                if not isinstance(track, dict):
                    continue
                force_copy = id(track) in seen_ids
                seen_ids.add(id(track))
                entry = self._make_entry(track, force_copy=force_copy)
                self._tracks.append(entry)
                if self._original_order:
                    self._original_order.append(entry)
            if self._current_index < 0 and len(self._tracks) > 0:
                self._current_index = 0

    def remove_track(self, index: int) -> Optional[dict]:
        """Remove a track from the queue by index."""
        with self._lock:
            n = len(self._tracks)
            if n > 0 and -n <= index < 0:
                index = n + index
            if 0 <= index < n:
                track = self._tracks.pop(index)
                target_qid = track.get("_queue_item_id")
                if target_qid is not None:
                    self._original_order = [t for t in self._original_order if t.get("_queue_item_id") != target_qid]
                elif self._original_order:
                    target_key = self._track_key(track)
                    for i, t in enumerate(self._original_order):
                        if t is track or self._track_key(t) == target_key:
                            self._original_order.pop(i)
                            break
                self._history_stack = [
                    i - 1 if i > index else i
                    for i in self._history_stack
                    if i != index
                ]
                if len(self._tracks) == 0:
                    self._current_index = -1
                elif index < self._current_index:
                    self._current_index -= 1
                elif index == self._current_index:
                    self._current_index = min(self._current_index, len(self._tracks) - 1)
                return track
            return None

    def move_track(self, old_index: int, new_index: int) -> bool:
        """Move a track in the queue from old_index to new_index."""
        with self._lock:
            n = len(self._tracks)
            if n > 0 and -n <= old_index < 0:
                old_index = n + old_index
            if n > 0 and -n <= new_index < 0:
                new_index = n + new_index
            if 0 <= old_index < n and 0 <= new_index < n:
                if old_index == new_index:
                    return True
                self._history_stack.clear()

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
                return True
            return False

    def next_track(self, force_advance: bool = False) -> Optional[dict]:
        """Move to the next track. Returns the track or None."""
        with self._lock:
            if self.is_empty:
                return None

            if self._current_index < 0:
                self._current_index = 0
                return self.current_track

            if self._repeat == "one" and not force_advance:
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
                    last_track = self.current_track
                    old_tracks = list(self._tracks)
                    random.shuffle(self._tracks)
                    if len(self._tracks) > 1 and self._tracks[0] == last_track:
                        swap_idx = random.randint(1, len(self._tracks) - 1)
                        self._tracks[0], self._tracks[swap_idx] = self._tracks[swap_idx], self._tracks[0]
                    new_idx_map = {id(t): idx for idx, t in enumerate(self._tracks)}
                    self._history_stack = [
                        new_idx_map.get(id(old_tracks[i]), i)
                        for i in self._history_stack
                        if 0 <= i < len(old_tracks)
                    ]
                self._current_index = 0
                return self.current_track

            if self.current_track:
                self._history_stack.append(self._current_index)
                if len(self._history_stack) > 100:
                    self._history_stack = self._history_stack[-100:]

            self._current_index += 1
            return self.current_track

    def previous_track(self) -> Optional[dict]:
        """Move to the previous track. Returns the track or None."""
        with self._lock:
            if self.is_empty or self._current_index < 0:
                return None

            while self._history_stack:
                idx = self._history_stack.pop()
                if 0 <= idx < len(self._tracks):
                    self._current_index = idx
                    return self.current_track
            self._current_index = max(0, self._current_index - 1)

            return self.current_track

    def toggle_shuffle(self) -> bool:
        with self._lock:
            self.shuffle = not self._shuffle
            return self._shuffle

    def toggle_repeat(self) -> str:
        with self._lock:
            modes = ["off", "all", "one"]
            self._repeat = modes[(modes.index(self._repeat) + 1) % len(modes)]
            return self._repeat

    # Alias kept for external/3rd-party callers: the app itself only uses
    # previous_track() (audio/engine.py:prev_track).
    prev_track = previous_track

    def jump_to(self, index: int) -> Optional[dict]:
        """Jump to a specific track in the queue."""
        with self._lock:
            if isinstance(index, bool):
                return None
            try:
                index = int(index)
            except (TypeError, ValueError):
                return None
            n = len(self._tracks)
            if n > 0 and -n <= index < 0:
                index = n + index
            if 0 <= index < n:
                if self.current_track:
                    self._history_stack.append(self._current_index)
                    if len(self._history_stack) > 100:
                        self._history_stack = self._history_stack[-100:]
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
            self._counter = 0

    def get_upcoming(self, count: int = 10) -> list:
        """Get the next N upcoming tracks."""
        with self._lock:
            start = self._current_index + 1
            return self._tracks[start:start + count]

    def peek_next(self) -> Optional[dict]:
        """Peek at the next track that would play without advancing the queue."""
        with self._lock:
            if self.is_empty:
                return None
            if self._repeat == "one":
                return self.current_track
            if self._current_index < len(self._tracks) - 1:
                return self._tracks[self._current_index + 1]
            if self._repeat == "all":
                return self._tracks[0] if self._tracks else None
            return None
