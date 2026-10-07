"""Regression: _emit must never block on the UI thread.

pywebview's WinForms backend marshals `window.evaluate_js` through
`Control.Invoke`. Invoking that from the UI thread itself makes the thread wait
for its own message queue, freezing the entire window. The pywebview `loaded`
event runs on the UI thread, and `main.py` calls
`engine._on_track_changed(...)` from it to restore the saved session track, so
every app start with a restorable track deadlocked: the UI stopped responding
to clicks and `track_changed` never reached the frontend (player bar stayed on
"Не играет").
"""
import threading
import time

import pytest

from core.api import AppApi, _MAIN_THREAD


class _FakeWindow:
    """Records evaluate_js calls and simulates the UI-thread Invoke lock."""

    def __init__(self):
        self.calls = []
        self.never = threading.Event()

    def evaluate_js(self, code):
        self.calls.append(code)
        return None


def _make_api(window):
    api = AppApi.__new__(AppApi)
    api._window = window
    api._core = None
    return api


def test_emit_from_ui_thread_does_not_block():
    """Emitting on the main thread must hand off and return immediately."""
    window = _FakeWindow()
    api = _make_api(window)

    def run_on_main():
        # Simulate pywebview invoking our callback on the UI thread.
        assert threading.current_thread() is _MAIN_THREAD
        start = time.monotonic()
        api._emit("track_changed", {"title": "x"})
        return time.monotonic() - start

    # Execute the body on a thread object we control but treat as "main".
    holder = {}

    def body():
        # Temporarily pretend the calling thread is the main thread.
        global _MAIN_THREAD
        original = _MAIN_THREAD
        _MAIN_THREAD = threading.current_thread()
        try:
            holder["elapsed"] = run_on_main()
        finally:
            _MAIN_THREAD = original

    t = threading.Thread(target=body)
    t.start()
    t.join(timeout=5)

    assert not t.is_alive(), "_emit blocked the calling (UI) thread"
    assert holder["elapsed"] < 1.0, f"_emit took {holder['elapsed']:.2f}s on the UI thread"
    assert window.calls, "evaluate_js was never scheduled"


def test_emit_from_worker_thread_runs_inline():
    """Normal bridge-thread emission stays synchronous (ordering preserved)."""
    window = _FakeWindow()
    api = _make_api(window)

    result = {}

    def worker():
        start = time.monotonic()
        api._emit("queue_updated", {"tracks": []})
        result["elapsed"] = time.monotonic() - start
        result["count_at_return"] = len(window.calls)

    t = threading.Thread(target=worker)
    t.start()
    t.join(timeout=5)

    assert not t.is_alive()
    # Synchronous path: the call has already been made when _emit returns.
    assert result["count_at_return"] == 1


def test_emit_without_window_is_noop():
    api = AppApi.__new__(AppApi)
    api._window = None
    api._core = None
    # Must not raise.
    api._emit("track_changed", {"a": 1})


def test_emit_unserializable_payload_does_not_raise():
    """A payload json cannot encode must be dropped, not crash the caller."""
    window = _FakeWindow()
    api = _make_api(window)

    class Weird:
        pass

    t = threading.Thread(target=api._emit, args=("track_changed", {"x": Weird()}))
    t.start()
    t.join(timeout=5)

    assert not t.is_alive()
    assert not window.calls, "unserializable payload must not reach evaluate_js"


def test_emit_heavy_payload_roundtrip():
    """A realistic queue payload (Cyrillic, nested, long) must serialize."""
    import json
    import re

    window = _FakeWindow()
    api = _make_api(window)

    payload = {
        "tracks": [
            {
                "id": i,
                "title": "ЗАНЫ ПРЕПАРАТЫ / ultra slowed",
                "artist": "ЗаныПрепараты, КРАКЭН",
                "source": "youtube",
                "source_id": "abc" * 12,
                "duration": 181.5,
                "is_favorite": False,
            }
            for i in range(50)
        ],
        "current_index": 3,
        "shuffle": True,
        "repeat": "off",
    }
    api._emit("queue_updated", payload)
    assert window.calls

    # json.dumps escapes non-ASCII by default; JS parses \uXXXX correctly.
    # Verify the emitted code carries the full payload by round-tripping it.
    code = window.calls[0]
    m = re.search(r"window\.onPythonEvent\(\"queue_updated\", (.*)\); \}", code, re.S)
    assert m, "could not locate the JSON argument in the emitted JS"
    decoded = json.loads(m.group(1))
    assert decoded == payload
    assert decoded["tracks"][0]["title"] == "ЗАНЫ ПРЕПАРАТЫ / ultra slowed"
