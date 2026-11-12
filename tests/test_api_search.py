"""AppApi search: disabled providers complete immediately, local DB is offline."""

import time
from threading import Event
from types import SimpleNamespace

import pytest


def _wait_for(events, name, timeout=10.0, request_id=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(event == name and (request_id is None or data.get('request_id') == request_id)
               for event, data in events):
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


def test_local_search_offline_roundtrip(api, emitted, tmp_db, tmp_path):
    audio = tmp_path / 'song.mp3'
    audio.write_bytes(b'audio')
    tmp_db.add_track(title="UniqueLocalSongXYZ", artist="LocalArt",
                     source="local", source_id="loc1", file_path=str(audio))
    api.search("UniqueLocalSongXYZ", source="local")
    assert _wait_for(emitted, "search_results")
    assert _wait_for(emitted, "search_completed")
    batches = [d for e, d in emitted if e == "search_results"]
    assert any(b["source"] == "local" and b["tracks"] for b in batches)


@pytest.mark.parametrize('result_type', [None, 'tracks'])
def test_search_only_publishes_tracks_with_audio(api, emitted, tmp_db, tmp_path, monkeypatch, result_type):
    audio = tmp_path / 'present.mp3'
    audio.write_bytes(b'audio')
    for name, path in [('present', audio), ('missing', tmp_path / 'missing.mp3')]:
        tmp_db.add_track(title=f'Example {name}', source='local', source_id=name, file_path=str(path))

    results = [
        {'title': 'Example online', 'source': 'youtube', 'source_id': 'playable'},
        {'title': 'Example private', 'source': 'youtube', 'source_id': 'unavailable'},
        {'title': 'Example album', 'source': 'youtube', 'source_id': 'album', 'type': 'album'},
    ]
    monkeypatch.setattr(api._core, 'youtube', SimpleNamespace(
        search=lambda query, callback, **kwargs: callback(results)))
    for provider in ('soundcloud', 'spotify', 'deezer'):
        monkeypatch.setattr(api._core, provider, SimpleNamespace(
            search=lambda query, callback, **kwargs: callback([])), raising=False)
    monkeypatch.setattr(api._core.engine, 'resolve_stream_url',
                        lambda track, **kwargs: 'https://example.com/audio' if track['source_id'] == 'playable' else None)

    api.search('Example', result_type=result_type, request_id='combined')
    assert _wait_for(emitted, 'search_completed', request_id='combined')
    assert emitted[-1][0] == 'search_completed'
    tracks = [track['source_id'] for event, data in emitted if event == 'search_results' for track in data['tracks']]
    assert set(tracks) == {'present', 'playable', 'album'}


def test_cancelled_audio_check_cannot_publish_stale_track(api, emitted, monkeypatch):
    checking, finish = Event(), Event()

    def search(query, callback, **kwargs):
        callback([{'title': query, 'source': 'youtube', 'source_id': query}])

    def resolve(track, cancel_token):
        if track['source_id'] == 'previous':
            checking.set()
            assert finish.wait(3)
            assert cancel_token()
        return 'https://example.com/audio'

    monkeypatch.setattr(api._core, 'youtube', SimpleNamespace(search=search))
    monkeypatch.setattr(api._core.engine, 'resolve_stream_url', resolve)
    api.search('previous', source='youtube', request_id='old')
    try:
        assert checking.wait(2)
        api.search('current', source='youtube', request_id='new')
        assert _wait_for(emitted, 'search_completed', request_id='new')
    finally:
        finish.set()
        api._search_audio_executor.shutdown(wait=True)
    assert [(event, data['request_id']) for event, data in emitted] == [
        ('search_results', 'new'), ('search_completed', 'new'),
    ]


def test_slow_audio_checks_do_not_block_other_provider_searches(api, emitted, monkeypatch):
    release, started, other_called = Event(), Event(), Event()
    count = [0]

    def resolve(track, cancel_token):
        count[0] += 1
        if count[0] >= 6:
            started.set()
        release.wait(3)
        return 'https://example.com/audio'

    def youtube(query, callback, **kwargs):
        callback([{'title': query, 'source': 'youtube', 'source_id': str(i)} for i in range(12)])

    def deezer(query, callback, **kwargs):
        assert started.wait(2)
        other_called.set()
        callback([{'title': 'Album', 'source': 'deezer', 'source_id': '1', 'type': 'album'}])

    monkeypatch.setattr(api._core, 'youtube', SimpleNamespace(search=youtube))
    monkeypatch.setattr(api._core, 'deezer', SimpleNamespace(search=deezer), raising=False)
    monkeypatch.setattr(api._core.engine, 'resolve_stream_url', resolve)
    try:
        api.search('test', request_id='parallel')
        assert other_called.wait(2)
        assert _wait_for(emitted, 'search_results', timeout=1, request_id='parallel')
    finally:
        release.set()


def test_catalogue_verdicts_are_immediate_and_unknown_tracks_are_checked(api, emitted, monkeypatch):
    release, started = Event(), Event()
    tracks = [
        {'title': 'Ready', 'source': 'youtube', 'source_id': 'ready', '_catalogue_available': True},
        {'title': 'Blocked', 'source': 'youtube', 'source_id': 'blocked', '_catalogue_available': False},
        {'title': 'Unknown', 'source': 'youtube', 'source_id': 'slow'},
    ]
    monkeypatch.setattr(api._core, 'youtube', SimpleNamespace(search=lambda query, callback, **kwargs:
                        callback(tracks)))

    def resolve(track, cancel_token):
        assert track['source_id'] == 'slow'
        started.set()
        release.wait(3)
        return 'https://example.com/audio'

    monkeypatch.setattr(api._core.engine, 'resolve_stream_url', resolve)
    try:
        api.search('test', source='youtube', request_id='catalogue')
        assert started.wait(1)
        assert [event for event, _ in emitted] == ['search_results']
        assert [track['source_id'] for track in emitted[0][1]['tracks']] == ['ready']
    finally:
        release.set()
        api._search_audio_executor.shutdown(wait=True)
    assert _wait_for(emitted, 'search_completed', request_id='catalogue')
    assert [track['source_id'] for track in emitted[1][1]['tracks']] == ['slow']
    assert emitted[-1][0] == 'search_completed'


def test_selected_provider_only_is_created_and_obsolete_queued_search_is_skipped(api, emitted):
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
