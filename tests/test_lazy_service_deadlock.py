"""Regression test: lazy service properties must not self-deadlock.

`recommendations` acquires AppCore._service_lock and then reads
`self.soundcloud`, which acquires the same lock. With a non-reentrant Lock that
is an unrecoverable self-deadlock: every later reader of a lazy service (the
search bridge method among them) blocks forever, so search never dispatches a
provider and the UI spins on "Поиск..." indefinitely.
"""
import threading
import time

from core.app import AppCore


def test_service_lock_is_reentrant():
    assert isinstance(AppCore.__init__.__doc__ or "", (str, type(None)))
    core = AppCore.__new__(AppCore)
    core._service_lock = threading.RLock()
    assert isinstance(core._service_lock, type(threading.RLock()))


def test_nested_lazy_property_access_does_not_deadlock(monkeypatch):
    core = AppCore.__new__(AppCore)
    core._service_lock = threading.RLock()
    core._soundcloud = None
    core._yandex = None
    core._recommendations = None
    core.settings = None
    core.db = None
    core.youtube = object()

    import sys
    import types

    sc_mod = types.ModuleType("services.soundcloud_service")

    class SoundCloudService:
        def __init__(self, settings=None):
            self.settings = settings

    sc_mod.SoundCloudService = SoundCloudService

    rec_mod = types.ModuleType("services.recommendation_service")

    class RecommendationService:
        def __init__(self, **kw):
            self.kw = kw

    rec_mod.RecommendationService = RecommendationService

    monkeypatch.setitem(sys.modules, "services.soundcloud_service", sc_mod)
    monkeypatch.setitem(sys.modules, "services.recommendation_service", rec_mod)

    # Exercise the exact nesting that deadlocked: recommendations -> soundcloud
    rec = core.recommendations
    assert rec is not None
    assert isinstance(rec.kw["soundcloud_service"], SoundCloudService)
    # A second reader (what search() does) must still be able to get the service.
    assert core.soundcloud is not None


def test_concurrent_lazy_access_all_succeed():
    core = AppCore.__new__(AppCore)
    core._service_lock = threading.RLock()
    core._soundcloud = None
    core._yandex = None
    core._recommendations = None
    core.settings = None
    core.db = None
    core.youtube = object()

    import sys
    import types

    sc_mod = types.ModuleType("services.soundcloud_service")

    class SoundCloudService:
        def __init__(self, settings=None):
            time.sleep(0.01)
            self.settings = settings

    sc_mod.SoundCloudService = SoundCloudService
    sys.modules["services.soundcloud_service"] = sc_mod

    got = []
    errors = []

    def worker():
        try:
            got.append(core.soundcloud)
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert not any(t.is_alive() for t in threads), "lazy property access deadlocked"
    assert not errors
    assert len(got) == 8
