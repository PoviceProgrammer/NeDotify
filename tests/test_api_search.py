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
    res = api.search("hello", source="zeno")
    assert res == {"query": "hello", "tracks": []}
    completed = [d for e, d in emitted if e == "search_completed"]
    assert len(completed) == 1
    assert completed[0]["source"] == "zeno"


def test_yandex_provider_is_not_disabled(api, emitted):
    api.search("hello", source="yandex")
    assert _wait_for(emitted, "search_completed")


def test_disabled_vk_completes(api, emitted):
    api.search("hello", source="vk")
    assert _wait_for(emitted, "search_completed")


def test_empty_query_short_circuits(api, emitted):
    assert api.search("   ", source="yandex") == {"query": "", "tracks": []}
    assert emitted == [("search_completed", {
        "query": "", "source": "yandex", "type": None, "request_id": None,
    })]


def test_local_search_offline_roundtrip(api, emitted, tmp_db):
    tmp_db.add_track(title="UniqueLocalSongXYZ", artist="LocalArt",
                     source="local", source_id="loc1")
    api.search("UniqueLocalSongXYZ", source="local")
    assert _wait_for(emitted, "search_results")
    assert _wait_for(emitted, "search_completed")
    batches = [d for e, d in emitted if e == "search_results"]
    assert any(b["source"] == "local" for b in batches)


def test_selected_provider_only_is_created_and_obsolete_queued_search_is_skipped(api, emitted):
    from types import SimpleNamespace
    tasks, queries = [], []
    api._search_executor.shutdown(wait=True)
    api._search_executor = SimpleNamespace(submit=lambda fn, *args: tasks.append((fn, args)))
    class Core:
        spotify = SimpleNamespace(search=lambda query, callback, **kwargs:
                                  (queries.append(query), callback([{'title': query}])))
        @property
        def youtube(self):
            raise AssertionError('Unselected YouTube created')
        @property
        def soundcloud(self):
            raise AssertionError('Unselected SoundCloud created')
        @property
        def yandex(self):
            raise AssertionError('Disabled Yandex created')
    original_core = api._core
    api._core = Core()
    try:
        api.search('old', source='spotify')
        api.search('latest', source='spotify')
        assert not queries  # no provider initialization on the bridge thread
        for fn, args in tasks:
            fn(*args)
        assert queries == ['latest']
        assert all(data['query'] == 'latest' for event, data in emitted)
        assert sum(event == 'search_completed' for event, data in emitted) == 1
    finally:
        api._core = original_core
