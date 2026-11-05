"""Avoid redundant provider traffic without changing search/playback results."""
from types import SimpleNamespace

import pytest



@pytest.mark.parametrize('index', [0, 1, 2])
def test_duplicate_search_is_one_task_and_repeat_is_served_without_a_task(providers, index):
    service = providers[index]
    responses = []
    for _ in range(3):
        service.search('same query', callback=responses.append)
    assert len(service._executor.tasks) == 1
    service._executor.tasks.pop()()
    assert len(responses) == 3 and responses[0]
    service.search('same query', callback=responses.append)
    assert len(responses) == 4
    assert not service._executor.tasks


@pytest.mark.parametrize('index', [0, 1])
def test_small_fallback_search_does_not_poison_normal_search_limit(providers, index):
    service = providers[index]
    responses = []
    service.search('same query', max_results=1, callback=responses.append)
    service._executor.tasks.pop()()
    service.search('same query', max_results=20, callback=responses.append)
    assert len(service._executor.tasks) == 1
    service._executor.tasks.pop()()
    assert len(responses) == 2


def test_soundcloud_simultaneous_play_and_queue_share_api_calls(providers):
    service = providers[1]
    calls, responses = [], []
    service._media_url_is_servable = lambda url: True
    def get(url, **kwargs):
        calls.append(url)
        payload = ({'url': 'https://cdn.sndcdn.com/audio.mp3'} if '/media/' in url else
                   {'id': 123, 'title': 'Track', 'media': {'transcodings': [
                       {'url': 'https://api-v2.soundcloud.com/media/stream',
                        'format': {'protocol': 'progressive'}}]}})
        return SimpleNamespace(status_code=200, json=lambda: payload)
    service._api_get = get
    service._public_json = lambda url, **kw: get(url, **kw).json()
    for _ in range(3):
        service.get_stream_url('123', callback=lambda url, meta: responses.append(url))
    assert len(service._playback_executor.tasks) == 1
    service._playback_executor.tasks.pop()()
    assert len(calls) == 2
    assert responses == ['https://cdn.sndcdn.com/audio.mp3'] * 3


def test_spotify_transient_failure_is_retried_after_network_recovers(providers, monkeypatch):
    import services.spotify_service as module
    service = providers[2]
    responses = []
    monkeypatch.setattr(module._session, 'get', lambda *a, **k:
                        SimpleNamespace(status_code=503))
    # Exercise the real metadata function, not the successful provider stub.
    import importlib.util
    spec = importlib.util.spec_from_file_location('_spotify_retry', module.__file__)
    real = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(real)
    monkeypatch.setattr(service._get_session(), 'get', lambda *a, **k: SimpleNamespace(status_code=503))
    monkeypatch.setattr(module, '_cached_spotify_search', real._cached_spotify_search)
    service.search('retry query', callback=responses.append)
    service._executor.tasks.pop()()
    assert responses == [[]]
    monkeypatch.setattr(service._get_session(), 'get', lambda *a, **k:
                        SimpleNamespace(status_code=200, json=lambda: {'results': [{'trackId': 1, 'trackName': 'Track'}]}))
    service.search('retry query', callback=responses.append)
    service._executor.tasks.pop()()
    assert responses[-1][0]['title'] == 'Track'
