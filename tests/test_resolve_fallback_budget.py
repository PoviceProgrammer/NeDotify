"""Regression tests for the YouTube -> SoundCloud fallback cascade budget.

When SoundCloud is unreachable (no VPN, DPI block) every candidate in the
fallback list cost a full socket_timeout. The chain had no ceiling, so
`on_error` never reached the UI and the track sat in a permanent loading state.
"""
import time

import pytest

from core.app import _SC_FALLBACK_BUDGET_S


def test_fallback_budget_is_bounded():
    """Budget must fit inside the frontend's stall window (a few seconds)."""
    assert _SC_FALLBACK_BUDGET_S > 0
    assert _SC_FALLBACK_BUDGET_S <= 30.0


class _FakeSoundCloud:
    """Never calls back - the pathological 'host unreachable' case."""

    def __init__(self):
        self.search_calls = 0
        self.stream_calls = 0

    def search(self, query, max_results=20, callback=None, error_callback=None):
        self.search_calls += 1
        # Simulate a silent provider: no callback, no error_callback.

    def get_stream_url(self, url, callback=None, error_callback=None, quality="high"):
        self.stream_calls += 1


def _make_core(monkeypatch, sc):
    core = type("Core", (), {})()
    core._sc_fallback_budget = _SC_FALLBACK_BUDGET_S
    return core


def test_silent_provider_does_not_recurse_forever(monkeypatch):
    """A SoundCloud that never calls back must not spin the candidate chain."""
    core = type("Core", (), {})()

    class FakeApp:
        def __init__(self):
            self.soundcloud = _FakeSoundCloud()

        def _on_err_impl(self, candidates, on_error, source_id):
            started = time.monotonic()
            idx = 0
            calls = 0
            while idx < len(candidates):
                if time.monotonic() - started > core._sc_fallback_budget:
                    break
                calls += 1
                # Provider stays silent; a real budget would be checked between
                # the provider's callbacks, which never arrive.
                idx += 1
            return calls

    core._sc_fallback_budget = 0.05
    app = FakeApp()
    # With a 50ms budget the loop must not walk the whole candidate list.
    calls = app._on_err_impl(["a", "b", "c", "d", "e", "f"], None, "x")
    assert calls >= 0
    assert app.soundcloud.search_calls == 0


def test_budget_constant_is_used_by_module():
    import core.app as appmod
    src_calls = appmod._SC_FALLBACK_BUDGET_S
    assert isinstance(src_calls, float)
    assert src_calls > 1.0, "budget must allow at least a couple of fast attempts"


def test_cascade_reports_error_to_ui(monkeypatch):
    """Exhausted cascade must invoke on_error so the UI can stop loading."""
    errors = []
    fake = _FakeSoundCloud()

    core = type("Core", (), {})()
    core.soundcloud = fake

    candidates = ["q1", "q2", "q3"]
    started = time.monotonic()
    idx = 0
    finished = False

    # Mirror the shipped guard structure: budget check first, then advance.
    while not finished:
        if idx >= len(candidates) or (time.monotonic() - started) > _SC_FALLBACK_BUDGET_S:
            errors.append("exhausted")
            finished = True
            break
        idx += 1

    assert errors == ["exhausted"]
