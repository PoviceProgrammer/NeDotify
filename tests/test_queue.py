"""PlaybackQueue unit tests (audio/queue.py). Pure logic, no I/O."""

import pytest

from audio.queue import PlaybackQueue


def _tracks(n=5):
    return [
        {"id": i, "title": "t%d" % i, "artist": "a", "source": "youtube",
         "source_id": "vid%d" % i}
        for i in range(n)
    ]


def test_set_tracks_and_current():
    q = PlaybackQueue()
    assert q.is_empty
    q.set_tracks(_tracks(3), 1)
    assert q.count == 3
    assert q.current_index == 1
    assert q.current_track["id"] == 1


def test_next_prev_walk():
    q = PlaybackQueue()
    q.set_tracks(_tracks(3), 0)
    assert q.next_track()["id"] == 1
    assert q.next_track()["id"] == 2
    assert q.previous_track()["id"] == 1


def test_next_at_end_returns_none_without_repeat():
    q = PlaybackQueue()
    q.repeat = "off"
    q.set_tracks(_tracks(2), 1)
    assert q.next_track() is None


def test_repeat_all_wraps():
    q = PlaybackQueue()
    q.repeat = "all"
    q.set_tracks(_tracks(2), 1)
    nxt = q.next_track()
    assert nxt is not None
    assert q.current_track["id"] == 0


def test_repeat_one_stays():
    q = PlaybackQueue()
    q.repeat = "one"
    q.set_tracks(_tracks(3), 1)
    assert q.next_track()["id"] == 1
    assert q.current_index == 1


def test_shuffle_keeps_current_first():
    q = PlaybackQueue()
    q.set_tracks(_tracks(10), 4)
    q.shuffle = True
    assert q.current_track["id"] == 4
    assert q.current_index == 0
    assert q.count == 10
    ids = sorted(t["id"] for t in q.tracks)
    assert ids == list(range(10))


def test_shuffle_off_restores_order():
    q = PlaybackQueue()
    q.set_tracks(_tracks(6), 2)
    q.shuffle = True
    q.shuffle = False
    assert [t["id"] for t in q.tracks] == list(range(6))


def test_move_track_shifts_current_index():
    q = PlaybackQueue()
    q.set_tracks(_tracks(5), 2)  # current id=2
    q.move_track(0, 4)  # move track 0 after current
    assert q.current_track["id"] == 2
    assert q.count == 5
    ids = [t["id"] for t in q.tracks]
    assert sorted(ids) == list(range(5))


def test_remove_track_before_current_adjusts_index():
    q = PlaybackQueue()
    q.set_tracks(_tracks(5), 3)
    q.remove_track(0)
    assert q.current_track["id"] == 3
    assert q.count == 4


def test_add_track_and_play_next():
    q = PlaybackQueue()
    q.set_tracks(_tracks(2), 0)
    extra = {"id": 99, "title": "x", "artist": "a"}
    q.add_track(extra, play_next=True)
    assert q.tracks[1]["id"] == 99
    assert q.count == 3


def test_clear_empties_queue():
    q = PlaybackQueue()
    q.set_tracks(_tracks(4), 1)
    q.clear()
    assert q.is_empty
    assert q.count == 0
    assert q.current_track is None
