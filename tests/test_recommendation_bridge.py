"""Recommendation bridge contracts without providers or a running WebView."""

from types import SimpleNamespace

import pytest


def test_manual_mix_refresh_invalidates_before_generating(api, core_ns):
    calls = []
    core_ns.recommendations = SimpleNamespace(
        reset_service=lambda: calls.append('reset'),
        get_mixes=lambda *args, callback, **kwargs: (calls.append('generate'), callback([])),
    )
    api._emit = lambda *args: None
    api.get_home_mixes(6, 'manual-refresh', True)
    assert calls == ['reset', 'generate']
    calls.clear()
    api.get_home_mixes(6, 'normal-load')
    assert calls == ['generate']


def test_seed_recommendation_limit_reaches_provider(api, core_ns):
    calls, delivered = [], []

    def recommendations(seed, *, max_results, callback, error_callback):
        calls.append((seed, max_results))
        callback([{"source_id": str(i)} for i in range(5)])

    core_ns.recommendations = SimpleNamespace(get_recommendations=recommendations)
    seed = {"title": "Seed", "artist": "Artist"}
    api._emit = lambda name, payload: delivered.append((name, payload))
    result = api.get_recommendations(seed, 2, request_id="recommendation-test")
    assert result == {"status": "pending", "request_id": "recommendation-test"}
    assert calls == [(seed, 2)]
    assert delivered == [("recommendations_ready", {
        "request_id": "recommendation-test",
        "tracks": [{"source_id": "0"}, {"source_id": "1"}],
    })]


@pytest.mark.parametrize("method,event", [
    ("get_feed", "feed_ready"),
    ("get_home_mixes", "mixes_ready"),
    ("get_home_releases", "releases_ready"),
])
def test_home_provider_error_publishes_empty_completion(api, core_ns, emitted, method, event):
    def fail(*args, callback, error_callback, **kwargs):
        error_callback("provider unavailable")

    core_ns.recommendations = SimpleNamespace(
        get_feed=fail, get_mixes=fail, get_releases=fail,
    )
    assert getattr(api, method)(3) == []
    assert emitted == [(event, [])]


@pytest.mark.parametrize("method,provider,event", [
    ("get_feed", "get_feed", "feed_ready"),
    ("get_home_mixes", "get_mixes", "mixes_ready"),
    ("get_home_releases", "get_releases", "releases_ready"),
])
def test_home_limit_is_used_for_work_and_payload(api, core_ns, emitted, method, provider, event):
    calls = []

    def complete(*args, max_results, callback, error_callback):
        calls.append(max_results)
        callback([{"source_id": str(i)} for i in range(5)])

    core_ns.recommendations = SimpleNamespace(**{provider: complete})
    assert getattr(api, method)(2) == []
    assert calls == [2]
    assert emitted == [(event, [{"source_id": "0"}, {"source_id": "1"}])]


def test_releases_use_listened_artist_names(api, core_ns, emitted, monkeypatch):
    monkeypatch.setattr(core_ns.db, "get_top_artists", lambda limit: [{"artist": "PHARAOH"}])
    seeds = []

    def releases(artists, **kwargs):
        seeds.extend(artists)
        kwargs["callback"]([])

    core_ns.recommendations = SimpleNamespace(get_releases=releases)
    api.get_home_releases(4)
    assert seeds == ["PHARAOH"]


def test_wave_completion_preserves_request_id_out_of_order(api, core_ns, emitted):
    pending = []

    def wave(seed, **kwargs):
        pending.append(kwargs)

    core_ns.recommendations = SimpleNamespace(get_wave_for_track=wave)
    seed = {"source_id": "seed", "title": "Seed"}
    api.get_track_wave(seed, request_id="old")
    api.get_track_wave(seed, request_id="new")
    pending[1]["callback"]([{"source_id": "new-result"}])
    pending[0]["error_callback"]("old error")
    assert emitted[0] == (
        "track_wave_ready", {"tracks": [{"source_id": "new-result"}], "request_id": "new"}
    )
    assert emitted[1][0] == "track_wave_ready"
    assert emitted[1][1]["tracks"] == []
    assert emitted[1][1]["request_id"] == "old"
    assert emitted[1][1]["error"]
    assert "old error" not in emitted[1][1]["error"]


def test_wave_legacy_payload_stays_compatible(api, core_ns, emitted):
    core_ns.recommendations = SimpleNamespace(
        get_wave_for_track=lambda seed, **kw: kw["callback"]([]),
    )
    assert api.get_track_wave({"title": "Seed"}) == []
    assert emitted == [("track_wave_ready", {"tracks": []})]


def test_invalid_wave_completes_instead_of_leaving_listener_waiting(api, emitted):
    assert api.get_track_wave({}, request_id="invalid") == []
    assert emitted[0][0] == "track_wave_ready"
    assert emitted[0][1]["tracks"] == []
    assert emitted[0][1]["request_id"] == "invalid"
    assert emitted[0][1]["error"]
