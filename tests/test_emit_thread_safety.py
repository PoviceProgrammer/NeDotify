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

import pytest

import core.api as api_module
from core.api import AppApi


class _FakeWindow:
    """Records evaluate_js calls and simulates the UI-thread Invoke lock."""

    def __init__(self):
        self.calls = []
        self.never = threading.Event()
        self.evaluated = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def evaluate_js(self, code):
        self.calls.append(code)
        self.evaluated.set()
        self.release.wait(5)
        return None


def _wait_for_delivery(window):
    assert window.evaluated.wait(2), "queued event was not delivered"


def _make_api(window):
    api = AppApi.__new__(AppApi)
    api._window = window
    api._core = None
    return api


def test_emit_from_ui_thread_does_not_block(monkeypatch):
    """Emitting on the main thread must hand off and return immediately."""
    window = _FakeWindow()
    window.release.clear()
    api = _make_api(window)

    t = threading.Thread(target=lambda: api._emit("track_changed", {"title": "x"}))
    monkeypatch.setattr(api_module, "_MAIN_THREAD", t)
    t.start()
    try:
        assert window.evaluated.wait(2), "queued event was not delivered"
        t.join(timeout=2)
        assert not t.is_alive(), "_emit blocked the calling (UI) thread"
        assert window.calls, "evaluate_js was never scheduled"
    finally:
        window.release.set()
        t.join(timeout=2)


def test_emit_from_worker_thread_runs_inline():
    """Normal bridge-thread emission stays synchronous (ordering preserved)."""
    window = _FakeWindow()
    api = _make_api(window)

    result = {}

    def worker():
        api._emit("queue_updated", {"tracks": []})
        result["count_at_return"] = len(window.calls)

    t = threading.Thread(target=worker)
    t.start()
    t.join(timeout=5)

    assert not t.is_alive()
    # Synchronous path: the call has already been made when _emit returns.
    assert result["count_at_return"] == 1


def test_emit_does_not_wait_for_renderer_under_playback_command_lock(api):
    window = _FakeWindow()
    window.release.clear()
    api._window = window
    api._ui_ready_event.set()
    returned = threading.Event()
    def command():
        with api._playback_guard():
            api._emit('queue_updated', {'tracks': []})
            returned.set()
    worker = threading.Thread(target=command)
    worker.start()
    try:
        assert window.evaluated.wait(2)
        assert returned.wait(1), 'a playback command waited for blocked UI evaluation'
    finally:
        window.release.set()
        worker.join(2)
    assert not worker.is_alive()


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


@pytest.mark.parametrize("payload", [[], 0, False, ""])
def test_emit_falsy_payload_is_preserved(payload):
    """Falsy but real payloads ([], 0, False, "") must not be replaced by {}."""
    import json
    import re

    window = _FakeWindow()
    api = _make_api(window)
    api._emit("queue_updated", payload)
    _wait_for_delivery(window)

    m = re.search(r"window\.onPythonEvent\(\"queue_updated\", (.*)\); \}", window.calls[0], re.S)
    assert json.loads(m.group(1)) == payload


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
    _wait_for_delivery(window)
    assert window.calls

    # json.dumps escapes non-ASCII by default; JS parses \uXXXX correctly.
    # Verify the emitted code carries the full payload by round-tripping it.
    code = window.calls[0]
    m = re.search(r"window\.onPythonEvent\(\"queue_updated\", (.*)\); \}", code, re.S)
    assert m, "could not locate the JSON argument in the emitted JS"
    decoded = json.loads(m.group(1))
    assert decoded == payload
    assert decoded["tracks"][0]["title"] == "ЗАНЫ ПРЕПАРАТЫ / ultra slowed"
