"""Concurrent transport calls keep queue results and emitted tracks aligned."""

import threading
import time

from audio.engine import AudioEngine


def test_concurrent_next_commands_serialize_mutate_and_notify():
    engine = AudioEngine()
    engine.queue.set_tracks([
        {"id": 1, "title": "A"},
        {"id": 2, "title": "B"},
        {"id": 3, "title": "C"},
    ], start_index=0)
    first_advanced = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    announced = []
    results = {}
    original_next = engine.queue.next_track
    calls = 0

    def controlled_next():
        nonlocal calls
        calls += 1
        result = original_next()
        if calls == 1:
            first_advanced.set()
            assert release_first.wait(2)
        return result

    engine.queue.next_track = controlled_next
    engine._on_track_changed = lambda track: announced.append(track["id"])

    first = threading.Thread(target=lambda: results.setdefault("first", engine.next_track()))
    second = threading.Thread(target=lambda: (
        second_started.set(), results.setdefault("second", engine.next_track())))
    first.start()
    assert first_advanced.wait(1)
    second.start()
    assert second_started.wait(1)
    time.sleep(0.03)
    # The second command must wait until the first command has notified B.
    assert announced == []
    release_first.set()
    first.join(2)
    second.join(2)

    assert not first.is_alive() and not second.is_alive()
    assert [results["first"]["id"], results["second"]["id"]] == [2, 3]
    assert announced == [2, 3]
