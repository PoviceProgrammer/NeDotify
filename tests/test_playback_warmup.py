"""Network initialization overlaps window loading and honors source/lifecycle settings."""
import threading
from types import SimpleNamespace

import pytest

from core.app import AppCore


@pytest.mark.parametrize('enabled,shutdown,expected', [(True, False, 1), (False, False, 0), (True, True, 0)])
def test_source_warmup_is_single_flight_owned_and_respects_shutdown(monkeypatch, enabled, shutdown, expected):
    import services.soundcloud_service as module
    initialized = []
    monkeypatch.setattr(module, 'SoundCloudService', lambda settings: initialized.append(1) or SimpleNamespace())
    core = AppCore.__new__(AppCore)
    core._service_lock = threading.RLock()
    core._shutting_down = threading.Event()
    if shutdown:
        core._shutting_down.set()
    core._soundcloud = None
    core._resolve_threads = set()
    core.youtube = object()
    core.settings = SimpleNamespace(get=lambda category, key, default=None: enabled)
    for _ in range(4):
        core.warm_playback_sources()
    with core._service_lock:
        workers = list(core._resolve_threads)
    for worker in workers:
        worker.join(timeout=1)
        assert not worker.is_alive()
    assert len(initialized) == expected
    assert not core._resolve_threads
    if expected:
        assert core.soundcloud.youtube_service is core.youtube
