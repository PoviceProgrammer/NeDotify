"""
Regression and verification tests for Group 9 fixes:
- BUG-WIN-027: Linear disk storm os.stat on 10k-100k files every 30 seconds in core/offline.py.
               Replaced full periodic polling with directory modification time check / lazy check when playing a track (play_track).
- History updates still emit events for active views.
"""

import os
import time
import pytest
from unittest.mock import MagicMock

from core import offline
from core.database import DatabaseManager


# ==============================================================================
# BUG-WIN-027: Offline library availability without periodic disk storm
# ==============================================================================

def test_bug_win_027_no_stat_storm_when_directories_unchanged(tmp_db, tmp_path, monkeypatch):
    """When directory timestamps do not change, refresh() must NOT stat each track's file.
    
    In the previous implementation, every 30 seconds an expired flag triggered _local_file
    on every single track in entries, causing 10k-100k os.stat calls.
    """
    dir1 = tmp_path / "music1"
    dir1.mkdir()
    dir2 = tmp_path / "music2"
    dir2.mkdir()

    t1_path = dir1 / "song1.mp3"
    t1_path.write_bytes(b"audio" * 1024)
    t2_path = dir2 / "song2.mp3"
    t2_path.write_bytes(b"audio" * 1024)

    t1 = tmp_db.add_track("Song 1", artist="Artist", file_path=str(t1_path))
    t2 = tmp_db.add_track("Song 2", artist="Artist", file_path=str(t2_path))

    # Initial index creation checks files and captures directory stamps
    ids = offline.offline_library_ids(tmp_db)
    assert set(ids) == {t1, t2}

    # Track how many times _local_file is called during subsequent refresh
    stat_calls = []
    original_local_file = offline._local_file

    def counting_local_file(path, cached=False):
        stat_calls.append(path)
        return original_local_file(path, cached=cached)

    monkeypatch.setattr(offline, "_local_file", counting_local_file)

    # Refresh when no directory changed: should make 0 _local_file calls
    index = offline._availability_index(tmp_db)
    assert stat_calls == [], "Unchanged directories must not trigger _local_file calls on tracks"

    # Even after time passes, NO periodic disk storm should occur
    clock = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: clock + 3600)
    index = index.refresh(force=False)
    assert stat_calls == [], "Time passage must not cause a full re-stat disk storm"


def test_bug_win_027_directory_change_only_rechecks_changed_directory(tmp_db, tmp_path, monkeypatch):
    """When one directory's mtime changes, only tracks in that directory should be rechecked."""
    dir1 = tmp_path / "music1"
    dir1.mkdir()
    dir2 = tmp_path / "music2"
    dir2.mkdir()

    t1_path = dir1 / "song1.mp3"
    t1_path.write_bytes(b"audio" * 1024)
    t2_path = dir2 / "song2.mp3"
    t2_path.write_bytes(b"audio" * 1024)

    t1 = tmp_db.add_track("Song 1", artist="Artist", file_path=str(t1_path))
    t2 = tmp_db.add_track("Song 2", artist="Artist", file_path=str(t2_path))

    index = offline._availability_index(tmp_db)
    assert set(index.ids) == {t1, t2}

    # Add a new file to dir1 to change its mtime
    time.sleep(0.05)
    (dir1 / "new_file.txt").write_bytes(b"temp")

    checked_paths = []
    original_local_file = offline._local_file

    def spy_local_file(path, cached=False):
        checked_paths.append(path)
        return original_local_file(path, cached=cached)

    monkeypatch.setattr(offline, "_local_file", spy_local_file)

    refreshed = index.refresh(force=False)
    # Only t1 (in dir1) should be rechecked; t2 (in dir2) must NOT be rechecked
    assert str(t1_path) in checked_paths
    assert str(t2_path) not in checked_paths


def test_bug_win_027_play_track_lazy_check_and_invalidation(api, core_ns, tmp_path, monkeypatch):
    """play_track must lazily verify local file existence and evict missing tracks from offline index."""
    song_path = tmp_path / "vanished.mp3"
    song_path.write_bytes(b"audio" * 1024)
    tid = core_ns.db.add_track("Vanished", artist="Ghost", file_path=str(song_path), source="local")

    # Initial indexing puts it in offline library
    assert tid in offline.offline_library_ids(core_ns.db)

    # File disappears or is truncated to 0 bytes
    song_path.unlink()

    track = core_ns.db.get_track(tid)
    res = api.play_track(track, [track], 0)
    assert res["success"] is False
    assert res["code"] == "file_missing"

    # Lazy eviction: missing track must be evicted from cached offline availability index
    assert tid not in offline.offline_library_ids(core_ns.db)


def test_bug_win_027_empty_or_truncated_file_lazy_check(api, core_ns, tmp_path):
    """A 0-byte file must be rejected as invalid and missing during play_track."""
    empty_path = tmp_path / "empty.mp3"
    empty_path.write_bytes(b"")
    tid = core_ns.db.add_track("Empty", artist="Zero", file_path=str(empty_path), source="local")

    track = core_ns.db.get_track(tid)
    res = api.play_track(track, [track], 0)
    assert res["success"] is False
    assert res["code"] == "file_missing"


# ==============================================================================
def test_bug_win_044_maybe_log_history_emits_history_updated(api, core_ns, emitted):
    """When a track is played and history is logged, history_updated must be emitted."""
    tid = core_ns.db.add_track("History Song", artist="Artist", source="local")
    track = core_ns.db.get_track(tid)
    api._current_track = track

    api.maybe_log_history()

    history_events = [e for e in emitted if e[0] == "history_updated"]
    assert len(history_events) >= 1
    assert history_events[0][1]["track_id"] == tid


def test_bug_win_044_clear_history_emits_history_updated(api, core_ns, emitted):
    """Clearing listening history must emit history_updated to notify active views."""
    api.clear_listening_history(confirmed=True)
    history_events = [e for e in emitted if e[0] == "history_updated"]
    assert len(history_events) >= 1
    assert history_events[0][1] == {"cleared": True}


