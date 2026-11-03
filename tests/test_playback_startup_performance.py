"""Playback preparation stays bounded for big queues; warmups use real caches."""
from types import SimpleNamespace
import time

import pytest

from audio.engine import AudioEngine
from core.resolver import StreamResolver


class DeferredExecutor:
    def __init__(self):
        self.tasks = []
        self.closed = False

    def submit(self, fn):
        if self.closed:
            raise RuntimeError('executor stopped')
        self.tasks.append(fn)


def test_ten_thousand_track_queue_only_enriches_the_active_track(api, core_ns, emitted, monkeypatch, tmp_path):
    audio = tmp_path / 'local.mp3'
    audio.write_bytes(b'\0' * 4096)
    tracks = [dict(track_id=i+1, source='local', source_id=str(i+1), title=f'Track {i}', file_path=str(audio)) for i in range(10_000)]
    engine = core_ns.engine = AudioEngine()
    engine._on_track_changed = api._on_track_changed
    queries = []
    def enrich(track):
        queries.append(track['id'])
        track['loudness_lufs'] = -18
        return track
    monkeypatch.setattr(api, '_enrich_track_lufs', enrich)
    api.play_track(tracks[-1], tracks, 9999)
    assert queries and len(queries) <= 3
    assert set(queries) == {10_000}
    assert engine.queue.current_track['id'] == 10_000
    assert 'loudness_lufs' not in tracks[0]
    assert 'id' not in tracks[0]  # caller's collection is an immutable input
    assert engine.queue.tracks[0]['id'] == 1
    assert 'track_changed' in [event for event, _ in emitted]


@pytest.fixture
def warmup(api, core_ns, monkeypatch):
    executor = DeferredExecutor()
    api._prefetch_executor.shutdown(wait=False)
    monkeypatch.setattr(api, '_prefetch_executor', executor)
    core_ns.resolver = StreamResolver(core_ns.db)
    engine = core_ns.engine = AudioEngine()
    engine.app_core = core_ns
    engine._on_track_changed = api._on_track_changed
    # Make the pruning boundary explicit; the OS monotonic clock may be <600s after boot.
    api._last_stream_clean = time.monotonic() - 601
    calls = []
    def network(track, cancel_token=None):
        calls.append(('network', dict(track)))
        track['temporary_provider_field'] = True
        return 'https://cdn.test/audio.m4a'
    monkeypatch.setattr(engine, '_resolve_via_network', network)
    monkeypatch.setattr(api, '_clean_stream_cache', lambda: calls.append(('prune',)))
    monkeypatch.setattr(api._search_executor, 'submit', lambda *a, **k: pytest.fail('Stream warmup must not wait behind search'))
    return executor, calls


def test_prefetch_is_deduplicated_and_populates_playback_cache_without_mutating_queue(api, core_ns, warmup):
    executor, calls = warmup
    track = dict(source='youtube', source_id='video1', title='A Song', artist='Artist')
    before = dict(track)
    assert api.prefetch_track(track) and api.prefetch_track(track)
    assert len(executor.tasks) == 1
    executor.tasks.pop()()
    assert track == before
    assert calls[0][0] == 'network' and calls[-1][0] == 'prune'
    assert core_ns.resolver.get_cached_url('youtube', 'video1') == 'https://cdn.test/audio.m4a'
    assert not api._prefetch_pending
    # The normal bridge path must start from this warm URL without a resolver call.
    import threading
    ready = threading.Event()
    original = core_ns.engine._notify_track_changed
    def notify():
        original()
        if core_ns.engine.queue.current_track.get('file_path'):
            ready.set()
    core_ns.engine._notify_track_changed = notify
    api.play_track(track, [track], 0)
    assert ready.wait(2)
    assert core_ns.engine.queue.current_track['file_path'] == 'https://cdn.test/audio.m4a'
    assert len([call for call in calls if call[0] == 'network']) == 1


def test_prefetch_bounds_outstanding_work_and_releases_slots_after_completion(api, warmup):
    executor, _ = warmup
    tracks = [dict(source='youtube', source_id=str(i)) for i in range(3)]
    assert api.prefetch_track(tracks[0]) is True
    assert api.prefetch_track(tracks[1]) is True
    assert api.prefetch_track(tracks[2]) is False
    assert len(executor.tasks) == 2
    executor.tasks.pop(0)()
    assert api.prefetch_track(tracks[2]) is True


def test_prefetch_error_or_shutdown_does_not_leave_track_pending(api, core_ns, warmup, monkeypatch):
    executor, _ = warmup
    track = dict(source='youtube', source_id='broken')
    monkeypatch.setattr(core_ns.engine, 'resolve_stream_url', lambda *a: (_ for _ in ()).throw(RuntimeError('offline')))
    assert api.prefetch_track(track) is True
    executor.tasks.pop()()
    assert not api._prefetch_pending
    executor.closed = True
    assert api.prefetch_track(track) is False
    assert not api._prefetch_pending


@pytest.mark.parametrize('queued', [False, True])
def test_expired_url_is_not_reused_by_the_bridge(api, core_ns, monkeypatch, queued):
    engine = core_ns.engine = AudioEngine()
    engine.app_core = core_ns
    engine._on_track_changed = api._on_track_changed
    core_ns.resolver = StreamResolver(core_ns.db)
    expired = f'https://cdn.test/audio.m4a?expire={int(time.time())-1}'
    track = dict(source='youtube', source_id='expired', title='Song', file_path=expired, stream_url='https://stale.test/proxy')
    core_ns.db.cache_stream('youtube', 'expired', expired)
    calls = []
    def resolve(candidate, cancel_token=None):
        calls.append((candidate['source'], candidate['source_id']))
        return 'https://cdn.test/fresh.m4a'
    monkeypatch.setattr(engine, '_resolve_via_network', resolve)
    import threading
    ready = threading.Event()
    original = engine._notify_track_changed
    def notify():
        original()
        if engine.queue.current_track.get('file_path') == 'https://cdn.test/fresh.m4a':
            ready.set()
    monkeypatch.setattr(engine, '_notify_track_changed', notify)
    if queued:
        api.play_track(track, [track], 0)
    else:
        engine.queue.set_tracks([dict(track)], 0)
        api._resolve_track(engine.queue.current_track, lambda _: None).result(timeout=2)
    assert ready.wait(2)
    assert calls == [('youtube', 'expired')]
    assert engine.queue.current_track['file_path'] == 'https://cdn.test/fresh.m4a'
