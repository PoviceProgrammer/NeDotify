"""The production AppCore lock must support nested lazy-property access."""

import os
import threading
from types import SimpleNamespace

from core.app import AppCore


class _Component:
    def __init__(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs
        self._started = False

    def start(self):
        self._started = True

    def stop(self, *args, **kwargs):
        self._started = False


def _build_production_core(monkeypatch):
    import core.app as app_module

    db = SimpleNamespace(db_path=os.path.join(os.getcwd(), "stub.db"))
    engine = SimpleNamespace()
    monkeypatch.setattr(app_module, "DatabaseManager", lambda: db)
    monkeypatch.setattr(app_module, "SettingsManager", lambda *_: _Component())
    monkeypatch.setattr(app_module, "SessionManager", lambda *_: _Component())
    monkeypatch.setattr(app_module, "CacheManager", lambda *_: _Component())
    monkeypatch.setattr(app_module, "FileScanner", lambda *_: _Component())
    monkeypatch.setattr(app_module, "StreamResolver", lambda *_args, **_kwargs: _Component())
    monkeypatch.setattr(app_module, "AudioEngine", lambda: engine)
    for name in (
        "YouTubeService", "VKService", "SpotifyService", "LyricsService", "ArtistService",
        "LocalProxyManager", "DownloadManager", "PluginManager", "ZapretService",
        "PlaylistImportService", "WatchdogService", "LufsScannerService",
        "AudioFingerprintService", "DiscordRPCService",
    ):
        monkeypatch.setattr(app_module, name, lambda *args, **kwargs: _Component(*args, **kwargs))
    core = AppCore()  # lock and lazy-property fields come from the real initializer
    return core


def _install_lazy_service_stubs(monkeypatch, delay=None):
    import services.soundcloud_service as sc_module
    import services.recommendation_service as rec_module

    class SoundCloudService:
        def __init__(self, settings=None):
            if delay is not None:
                delay.wait(2)
            self.settings = settings

    class RecommendationService:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(sc_module, "SoundCloudService", SoundCloudService)
    monkeypatch.setattr(rec_module, "RecommendationService", RecommendationService)
    return SoundCloudService, RecommendationService


def _stop_core_cleanup(core):
    core._cache_cleanup_stop.set()
    core._cache_cleanup_thread.join(2)


def test_production_service_lock_is_reentrant(monkeypatch):
    core = _build_production_core(monkeypatch)
    soundcloud_cls, _ = _install_lazy_service_stubs(monkeypatch)
    done = threading.Event()
    result = {}

    def nested_access():
        with core._service_lock:
            result["service"] = core.soundcloud
        done.set()

    thread = threading.Thread(target=nested_access, daemon=True)
    try:
        thread.start()
        assert done.wait(2), "the production service lock deadlocked on nested acquisition"
        assert isinstance(result["service"], soundcloud_cls)
    finally:
        _stop_core_cleanup(core)


def test_recommendation_property_uses_real_core_lock_and_dependencies(monkeypatch):
    core = _build_production_core(monkeypatch)
    soundcloud_cls, recommendation_cls = _install_lazy_service_stubs(monkeypatch)
    try:
        recommendations = core.recommendations
        assert isinstance(recommendations, recommendation_cls)
        assert isinstance(recommendations.kwargs["soundcloud_service"], soundcloud_cls)
        assert recommendations.kwargs["youtube_service"] is core.youtube
        assert core.soundcloud is recommendations.kwargs["soundcloud_service"]
    finally:
        _stop_core_cleanup(core)


def test_concurrent_lazy_access_all_succeed(monkeypatch):
    release = threading.Event()
    core = _build_production_core(monkeypatch)
    soundcloud_cls, _ = _install_lazy_service_stubs(monkeypatch, delay=release)
    got, errors = [], []

    def worker():
        try:
            got.append(core.soundcloud)
        except Exception as exc:  # pragma: no cover - failures are collected for useful output
            errors.append(exc)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(8)]
    try:
        for thread in threads:
            thread.start()
        release.set()
        for thread in threads:
            thread.join(2)
        assert not any(thread.is_alive() for thread in threads), "lazy property access deadlocked"
        assert not errors
        assert len(got) == 8 and all(isinstance(item, soundcloud_cls) for item in got)
        assert len({id(item) for item in got}) == 1
    finally:
        release.set()
        _stop_core_cleanup(core)
