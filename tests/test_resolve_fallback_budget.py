"""Exercise the real YouTube-to-SoundCloud fallback budget deterministically."""

import threading
from types import SimpleNamespace

from core.app import AppCore, _SC_FALLBACK_BUDGET_S


def test_fallback_budget_is_bounded():
    assert 0 < _SC_FALLBACK_BUDGET_S <= 30.0


def test_real_fallback_guard_stops_late_search_callback(monkeypatch):
    import core.app as app_module

    clock = SimpleNamespace(value=0.0)
    monkeypatch.setattr(app_module, "time", SimpleNamespace(monotonic=lambda: clock.value))

    timers = []
    class FakeTimer:
        def __init__(self, interval, callback):
            self.interval, self.callback, self.cancelled = interval, callback, False
            timers.append(self)
        def start(self):
            pass
        def cancel(self):
            self.cancelled = True

    monkeypatch.setattr(app_module.threading, "Timer", FakeTimer)

    searched = threading.Event()
    closed = threading.Event()
    late_search_callback = {}
    class YouTube:
        def get_stream_url(self, url, callback=None, error_callback=None, quality="high"):
            error_callback("YouTube unavailable")

    class SoundCloud:
        def search(self, query, max_results=20, callback=None, error_callback=None):
            late_search_callback.update(callback=callback, error_callback=error_callback)
            searched.set()

    core = AppCore.__new__(AppCore)
    core._service_lock = threading.RLock()
    core._shutting_down = threading.Event()
    core._resolution_timers = set()
    core._resolve_threads = set()
    core.settings = None
    core.youtube = YouTube()
    core.soundcloud = SoundCloud()
    core.db = SimpleNamespace(close_thread_connection=closed.set)
    errors = []

    core.re_resolve_stream_url_async(
        "youtube", "video-id", on_error=errors.append,
        track={"title": "Song", "artist": "Artist"},
    )
    assert searched.wait(3), "real resolver did not enter the SoundCloud fallback"
    assert closed.wait(3), "resolver worker did not finish after scheduling the callback"

    clock.value = _SC_FALLBACK_BUDGET_S + 1
    late_search_callback["error_callback"]("late provider response")

    assert len(late_search_callback) == 2
    assert errors == ["YouTube unavailable"]
    assert timers and timers[0].cancelled
    assert not core._resolution_timers
