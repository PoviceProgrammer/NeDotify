"""The JavaScript bridge only exposes the declared flat public API."""

from __future__ import annotations

import sys
import types
import inspect
from types import SimpleNamespace

import pytest

from core.bridge import BridgeApi, PUBLIC_METHODS, install_bridge_guard


def test_real_wrapped_bridge_retains_parameter_names_and_defaults(api):
    signature = inspect.signature(BridgeApi(api).play_track)
    assert list(signature.parameters) == ['track', 'track_list', 'index']
    assert signature.parameters['track_list'].default is None
    assert signature.parameters['index'].default == 0


def test_bridge_exception_does_not_echo_raw_provider_path_or_secret(api, core_ns, emitted, monkeypatch, caplog):
    raw = 'Invalid connection id C:\\private\\library.db token=bridge-secret'
    def fail():
        raise ValueError(raw)
    monkeypatch.setattr(core_ns.db, 'get_tracks_count', fail)
    with pytest.raises(RuntimeError) as error:
        api.get_profile_stats()
    assert 'bridge-secret' not in str(error.value) + caplog.text + repr(emitted)
    assert 'private' not in str(error.value) + repr(emitted)
    event = next(data for name, data in emitted if name == 'api_error')
    assert event['code'] == 'invalid_input'


def test_bridge_api_exposes_only_whitelisted_callables_and_preserves_signature():
    calls = []

    class Api:
        nested = SimpleNamespace(secret=lambda: "hidden")

        def get_queue(self, include_current=False):
            calls.append(include_current)
            return ["track"]

        def private_helper(self):
            return "hidden"

    bridge = BridgeApi(Api())
    assert set(dir(bridge)) == {name for name in PUBLIC_METHODS if hasattr(Api, name)}
    assert "nested" not in dir(bridge)
    assert "private_helper" not in dir(bridge)
    assert bridge.get_queue(True) == ["track"]
    assert calls == [True]
    with pytest.raises(AttributeError):
        _ = bridge.nested
    with pytest.raises(AttributeError):
        _ = bridge.private_helper


def test_guard_rejects_nested_or_unlisted_calls_and_forwards_allowed_args(monkeypatch):
    forwarded = []
    util = types.ModuleType("webview.util")
    util.js_bridge_call = lambda *args: forwarded.append(args) or "forwarded"
    webview = types.ModuleType("webview")
    webview.util = util
    monkeypatch.setitem(sys.modules, "webview", webview)
    monkeypatch.setitem(sys.modules, "webview.util", util)

    install_bridge_guard()
    guarded = util.js_bridge_call
    api = SimpleNamespace(get_queue=lambda: [])
    window = SimpleNamespace(_js_api=BridgeApi(api))
    params = {"args": [], "kwargs": {"limit": 12}}

    assert guarded(window, "nested.secret", params, "callback-1") is None
    assert forwarded == []
    assert guarded(window, "get_queue", params, "callback-2") == "forwarded"
    assert forwarded == [(window, "get_queue", params, "callback-2")]

    # Internal pywebview callbacks remain reachable through the guard.
    internal = next(iter(__import__("core.bridge", fromlist=["_INTERNAL_METHODS"])._INTERNAL_METHODS))
    assert guarded(window, internal, params, "callback-3") == "forwarded"
    assert forwarded[-1] == (window, internal, params, "callback-3")


def test_guard_install_is_idempotent(monkeypatch):
    util = types.ModuleType("webview.util")
    original = lambda *args: args
    util.js_bridge_call = original
    webview = types.ModuleType("webview")
    webview.util = util
    monkeypatch.setitem(sys.modules, "webview", webview)
    monkeypatch.setitem(sys.modules, "webview.util", util)

    install_bridge_guard()
    once = util.js_bridge_call
    install_bridge_guard()
    assert util.js_bridge_call is once
