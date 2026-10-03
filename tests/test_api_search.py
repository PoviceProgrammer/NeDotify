"""AppApi search: disabled providers complete immediately, local DB is offline."""

import time


def _wait_for(events, name, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(e == name for e, _ in events):
            return True
        time.sleep(0.05)
    return False


def test_disabled_provider_completes_immediately(api, emitted):
    t0 = time.monotonic()
    res = api.search("hello", source="yandex")
    dt = time.monotonic() - t0
    assert res == {"query": "hello", "tracks": []}
    assert dt < 5.0
    completed = [d for e, d in emitted if e == "search_completed"]
    assert len(completed) == 1
    assert completed[0]["source"] == "yandex"


def test_disabled_vk_completes(api, emitted):
    api.search("hello", source="vk")
    assert _wait_for(emitted, "search_completed")


def test_empty_query_short_circuits(api, emitted):
    assert api.search("   ", source="yandex") == {"query": "", "tracks": []}
    assert emitted == []


def test_local_search_offline_roundtrip(api, emitted, tmp_db):
    tmp_db.add_track(title="UniqueLocalSongXYZ", artist="LocalArt",
                     source="local", source_id="loc1")
    api.search("UniqueLocalSongXYZ", source="local")
    assert _wait_for(emitted, "search_results")
    assert _wait_for(emitted, "search_completed")
    batches = [d for e, d in emitted if e == "search_results"]
    assert any(b["source"] == "local" for b in batches)
