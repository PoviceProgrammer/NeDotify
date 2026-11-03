"""Round-trip guarantees for bounded session queues and listening heartbeats."""

from __future__ import annotations

import pytest

from core.listening import ListeningSession
from core.session import SessionManager


class MemorySettings:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def set(self, category, key, value):
        self.values[(category, key)] = value

    def get(self, category, key, default=None):
        return self.values.get((category, key), default)

    def flush(self):
        pass


@pytest.mark.parametrize("size", [1, 199, 200, 201, 1000])
@pytest.mark.parametrize("requested_index", [0, 1, 199, 200, 250, 799, 950, 999])
def test_session_round_trip_caps_queue_and_preserves_current_track_and_position(size, requested_index):
    settings = MemorySettings()
    manager = SessionManager(settings)
    queue = [
        {"id": track_id, "title": f"Track {track_id}", "artist": "Artist", "source": "youtube"}
        for track_id in range(size)
    ]
    expected_index = min(requested_index, size - 1)

    manager.save_session(
        track_id=expected_index,
        position=87.25,
        queue=queue,
        queue_index=requested_index,
    )
    restored = manager.restore_session()

    assert len(restored["queue"]) <= SessionManager.MAX_PERSISTED_QUEUE
    assert restored["queue"][restored["queue_index"]]["id"] == expected_index
    assert restored["track_id"] == expected_index
    assert restored["position"] == 87.25


def test_restore_session_clears_legacy_transient_paths_on_copy_only():
    cached_queue = [
        {
            "id": 7,
            "title": "Remote track",
            "source": "youtube",
            "file_path": r"C:\old-cache\track.webm",
            "resolved_at": 123.0,
            "stream_url": "http://127.0.0.1:49200/api/stream?track_id=7&k=old-session",
        }
    ]
    settings = MemorySettings({("session", "last_queue"): cached_queue})

    restored = SessionManager(settings).restore_session()

    assert restored["queue"][0]["file_path"] is None
    assert restored["queue"][0]["resolved_at"] == 0
    assert 'stream_url' not in restored["queue"][0]
    assert cached_queue[0]['stream_url'].startswith('http://127.0.0.1:49200/')
    assert cached_queue[0]["file_path"] == r"C:\old-cache\track.webm"
    assert cached_queue[0]["resolved_at"] == 123.0
    assert restored["queue"] is not cached_queue
    assert restored["queue"][0] is not cached_queue[0]


@pytest.mark.parametrize(
    ("elapsed", "expected"),
    [(15, 15), (16, 16), (60, 60), (300, 300), (301, 0)],
)
def test_listening_heartbeat_accepts_elapsed_through_anomaly_cap(elapsed, expected):
    session = ListeningSession({"duration": 1000}, last_tick=100.0, audible=True)

    session.tick(now=100.0 + elapsed)

    assert session.seconds == expected
    assert session.media_seconds == expected
    assert session.last_tick == 100.0 + elapsed
