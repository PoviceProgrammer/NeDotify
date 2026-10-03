"""AudioEngine.resolve_stream_url / _resolve_via_network (audio/engine.py).

Every service is an in-process stub that invokes its callback SYNCHRONOUSLY, so
the cascade's ``event.wait`` timeouts are never actually waited on and the
tests stay deterministic (no sleeps, no network).

``urllib.request.urlopen`` is blocked for the whole module: the YouTube
fallback may fire a real oEmbed request (audio/engine.py:212), and this suite
must never touch the network. The two tests that cover that branch install
their own stub over it.
"""

import json
import time
import types
import urllib.request

import pytest

import audio.engine as engine_mod
from audio.engine import AudioEngine
from core.resolver import StreamResolver


# --------------------------------------------------------------------------- #
# stubs
# --------------------------------------------------------------------------- #

class _Db:
    """Records the side effects of a successful resolve."""

    def __init__(self):
        self.updated = []
        self.cached = []
        self.raise_on_update = False

    def update_track(self, track_id, **kwargs):
        if self.raise_on_update:
            raise RuntimeError("db is gone")
        self.updated.append((track_id, kwargs))

    def cache_stream(self, source, source_id, stream_url):
        self.cached.append((source, source_id, stream_url))


class _Youtube:
    def __init__(self, stream=None, meta=None, error=None, results=None,
                 search_error=None, raises=False, log=None, clock=None, cost=0.0):
        self.stream = stream
        self.meta = meta
        self.error = error
        self.results = results
        self.search_error = search_error
        self.raises = raises
        self.log = log
        self.clock = clock
        self.cost = cost
        self.stream_calls = []
        self.search_calls = []

    def get_stream_url(self, video_url, callback=None, error_callback=None, quality="high"):
        self.stream_calls.append(video_url)
        if self.log is not None:
            self.log.append("yt.get_stream_url")
        if self.clock is not None:
            self.clock.advance(self.cost)
        if self.raises:
            raise RuntimeError("yt-dlp exploded")
        if self.error is not None:
            if error_callback:
                error_callback(self.error)
            return None
        if callback:
            callback(self.stream, self.meta)
        return None

    def search(self, query, max_results=20, callback=None, error_callback=None):
        self.search_calls.append((query, max_results))
        if self.log is not None:
            self.log.append("yt.search")
        if self.clock is not None:
            self.clock.advance(self.cost)
        if self.results is None:
            if error_callback:
                error_callback("nothing found")
            return None
        if callback:
            callback(self.results)
        return None


class _SoundCloud:
    def __init__(self, stream=None, meta=None, error=None, results=None,
                 log=None, clock=None, cost=0.0):
        self.stream = stream
        self.meta = meta
        self.error = error
        self.results = results
        self.log = log
        self.clock = clock
        self.cost = cost
        self.stream_calls = []
        self.search_calls = []

    def get_stream_url(self, track_url, callback=None, error_callback=None, quality="high", **kw):
        self.stream_calls.append(track_url)
        if self.log is not None:
            self.log.append("sc.get_stream_url")
        if self.clock is not None:
            self.clock.advance(self.cost)
        if self.error is not None:
            if error_callback:
                error_callback(self.error)
            return None
        if callback:
            callback(self.stream, self.meta)
        return None

    def search(self, query, max_results=20, callback=None, error_callback=None):
        self.search_calls.append((query, max_results))
        if self.log is not None:
            self.log.append("sc.search")
        if self.clock is not None:
            self.clock.advance(self.cost)
        if self.results is None:
            if error_callback:
                error_callback("nothing found")
            return None
        if callback:
            callback(self.results)
        return None


class _Yandex:
    def __init__(self, stream=None, meta=None, error=None, log=None):
        self.stream = stream
        self.meta = meta
        self.error = error
        self.log = log
        self.stream_calls = []

    def get_stream_url(self, source_id, callback=None, error_callback=None, quality="high", **kw):
        self.stream_calls.append(source_id)
        if self.log is not None:
            self.log.append("yandex.get_stream_url")
        if self.error is not None:
            if error_callback:
                error_callback(self.error)
            return None
        if callback:
            callback(self.stream, self.meta)
        return None


class _RecordingResolver:
    """Capture resolver.resolve()'s (source, source_id) pair; optional cache hit."""

    def __init__(self, cached=None):
        self.cached = cached
        self.lookups = []
        self.resolved = []
        self.network_calls = 0

    def get_cached_url(self, source, source_id):
        self.lookups.append((source, source_id))
        return self.cached

    def resolve(self, source, source_id, resolver_fn):
        self.resolved.append((source, source_id))
        self.network_calls += 1
        return resolver_fn()[0]


class _Clock:
    """Fake monotonic() clock: the cascade budget is checked against it.

    ``step`` is added on every read (models a call that consumes wall-clock time
    by itself), ``advance()`` models a stub service that consumed some time.
    """

    def __init__(self, start=1000.0, step=0.0):
        self.now = start
        self.step = step

    def __call__(self):
        value = self.now
        self.now += self.step
        return value

    def advance(self, dt):
        self.now += dt


class _FakeTimeModule:
    """time-module stand-in: only monotonic() is faked, scoped to audio.engine."""

    def __init__(self, real, clock):
        self._real = real
        self._clock = clock

    def monotonic(self):
        return self._clock()

    def __getattr__(self, name):
        return getattr(self._real, name)


def _core(**kwargs):
    """app_core namespace; omit a service to emulate an unconfigured provider."""
    ns = types.SimpleNamespace(db=kwargs.pop("db", None) or _Db())
    for name in ("youtube", "soundcloud", "yandex"):
        if name in kwargs:
            setattr(ns, name, kwargs.pop(name))
    for name, value in kwargs.items():
        setattr(ns, name, value)
    return ns


def _engine(core=None):
    e = AudioEngine()
    e.app_core = core if core is not None else _core()
    return e


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Hard-block real sockets for the whole module (see module docstring)."""
    blocked = []

    def _urlopen(*a, **kw):
        blocked.append(a)
        raise OSError("network is disabled in the engine test-suite")

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    return blocked


def _yt_track(**over):
    track = {"id": 1, "source": "youtube", "source_id": "dQw4w9WgXcQ",
             "title": "Song", "artist": "Artist"}
    track.update(over)
    return track


# --------------------------------------------------------------------------- #
# source / source_id derivation
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("empty", [None, {}, ""])
def test_empty_track_resolves_to_none(empty):
    resolver = _RecordingResolver()
    engine = _engine(_core(resolver=resolver))

    assert engine.resolve_stream_url(empty) is None
    assert resolver.resolved == []


def test_missing_source_with_a_url_is_treated_as_local():
    """No source + a url => 'local', so the raw path/URL is handed back as-is."""
    resolver = _RecordingResolver()
    engine = _engine(_core(resolver=resolver,
                           youtube=_Youtube(error="must not be called")))

    assert engine.resolve_stream_url({"id": 1, "url": "C:/Music/a.mp3"}) == "C:/Music/a.mp3"
    assert resolver.resolved == [], "a local track must never hit the network"


def test_local_source_returns_the_url():
    engine = _engine(_core(youtube=_Youtube(error="must not be called")))

    assert engine.resolve_stream_url(
        {"source": "local", "url": "C:/Music/a.mp3", "source_id": "ignored"}
    ) == "C:/Music/a.mp3"


def test_local_source_without_a_url_returns_none():
    engine = _engine(_core(youtube=_Youtube(error="must not be called")))

    assert engine.resolve_stream_url({"source": "local", "title": "T"}) is None


@pytest.mark.parametrize("source", ["vk", "bandcamp", "deezer", ""])
def test_unknown_source_returns_none(source):
    """An unsupported source is a silent miss, not an exception."""
    engine = _engine(_core(youtube=_Youtube(error="must not be called"),
                           soundcloud=_SoundCloud(error="must not be called")))

    track = {"id": 1, "source": source, "source_id": "abc", "title": "T", "artist": "A"}
    assert engine.resolve_stream_url(track) is None


def test_source_id_falls_back_to_the_row_id():
    """``source_id or id`` - the id fallback is what reaches the resolver."""
    resolver = _RecordingResolver()
    engine = _engine(_core(resolver=resolver,
                           youtube=_Youtube(error="no stream")))

    engine.resolve_stream_url({"id": 4242, "source": "youtube", "title": "T", "artist": "A"})

    assert resolver.resolved == [("youtube", 4242)]


def test_source_id_is_built_from_artist_and_title_when_missing():
    """A title-only track gets 'artist title' - which contains a space and is
    therefore not a candidate for direct extraction (see below)."""
    resolver = _RecordingResolver()
    engine = _engine(_core(resolver=resolver,
                           youtube=_Youtube(error="no stream")))

    engine.resolve_stream_url({"id": 1, "source": "youtube", "title": "Song", "artist": "Artist"})

    assert resolver.resolved == [("youtube", "Artist Song")]


def test_source_id_built_from_title_only_has_no_leading_space():
    resolver = _RecordingResolver()
    engine = _engine(_core(resolver=resolver,
                           youtube=_Youtube(error="no stream")))

    engine.resolve_stream_url({"id": 1, "source": "youtube", "title": "Song"})

    assert resolver.resolved == [("youtube", "Song")]


def test_missing_source_without_url_defaults_to_youtube():
    resolver = _RecordingResolver()
    engine = _engine(_core(resolver=resolver,
                           youtube=_Youtube(error="no stream")))

    engine.resolve_stream_url({"id": 1, "source_id": "dQw4w9WgXcQ",
                               "title": "Song", "artist": "Artist"})

    assert resolver.resolved == [("youtube", "dQw4w9WgXcQ")]


# --------------------------------------------------------------------------- #
# resolver integration
# --------------------------------------------------------------------------- #

def test_resolver_cache_hit_short_circuits_the_network():
    resolver = _RecordingResolver(cached="http://cached/stream")
    yt = _Youtube(stream="http://yt/stream")
    engine = _engine(_core(resolver=resolver, youtube=yt))

    assert engine.resolve_stream_url(_yt_track()) == "http://cached/stream"
    assert resolver.network_calls == 0
    assert yt.stream_calls == [], "a cache hit must not call the provider"


def test_resolver_cache_miss_runs_the_cascade_once():
    resolver = _RecordingResolver(cached=None)
    yt = _Youtube(stream="http://yt/stream")
    engine = _engine(_core(resolver=resolver, youtube=yt))

    assert engine.resolve_stream_url(_yt_track()) == "http://yt/stream"
    assert resolver.network_calls == 1
    assert yt.stream_calls == ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]


def test_real_resolver_persists_a_resolved_url():
    db = _Db()
    yt = _Youtube(stream="http://yt/stream")
    engine = _engine(_core(resolver=StreamResolver(db=None), youtube=yt, db=db))

    assert engine.resolve_stream_url(_yt_track()) == "http://yt/stream"
    # Second call is served from the resolver's memory, no provider round trip.
    assert engine.resolve_stream_url(_yt_track()) == "http://yt/stream"
    assert yt.stream_calls == ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]


def test_resolver_swallows_cascade_exceptions():
    """resolver.resolve() must answer None instead of propagating."""
    resolver = _RecordingResolver()
    engine = _engine(_core(resolver=resolver,
                           youtube=_Youtube(raises=True)))

    assert engine.resolve_stream_url(_yt_track()) is None
    assert resolver.network_calls == 1


# --------------------------------------------------------------------------- #
# YouTube branch: tier 0 - direct extraction
# --------------------------------------------------------------------------- #

def test_youtube_direct_extraction_builds_the_watch_url():
    yt = _Youtube(stream="http://yt/stream")
    engine = _engine(_core(youtube=yt, soundcloud=_SoundCloud(error="must not run")))

    assert engine.resolve_stream_url(_yt_track()) == "http://yt/stream"
    assert yt.stream_calls == ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]


def test_youtube_source_id_that_is_already_a_url_is_passed_through():
    yt = _Youtube(stream="http://yt/stream")
    engine = _engine(_core(youtube=yt))
    direct = "https://youtu.be/dQw4w9WgXcQ"

    assert engine.resolve_stream_url(_yt_track(source_id=direct)) == "http://yt/stream"
    assert yt.stream_calls == [direct]


@pytest.mark.parametrize("source_id", ["ab", "abc", "Artist Song", ""])
def test_youtube_skips_direct_extraction_for_unusable_source_ids(source_id):
    """len() > 3 and no space: a bare 'artist title' is never a video id."""
    yt = _Youtube(stream="http://yt/stream")
    engine = _engine(_core(youtube=yt, soundcloud=_SoundCloud(error="no stream")))

    assert engine.resolve_stream_url(_yt_track(source_id=source_id)) is None
    assert yt.stream_calls == []


def test_youtube_extraction_failure_falls_through_to_the_cascade():
    log = []
    yt = _Youtube(error="Sign in to confirm you're not a bot", log=log)
    sc = _SoundCloud(results=[{"source_id": "77", "source_url": "https://soundcloud.com/a/b"}],
                     stream="http://sc/stream", log=log)
    engine = _engine(_core(youtube=yt, soundcloud=sc))

    assert engine.resolve_stream_url(_yt_track()) == "http://sc/stream"
    assert log == ["yt.get_stream_url", "sc.search", "sc.get_stream_url"]


def test_youtube_extraction_that_raises_does_not_break_the_cascade():
    log = []
    yt = _Youtube(raises=True, log=log)
    sc = _SoundCloud(results=[{"source_id": "77"}], stream="http://sc/stream", log=log)
    engine = _engine(_core(youtube=yt, soundcloud=sc))

    assert engine.resolve_stream_url(_yt_track()) == "http://sc/stream"
    assert log == ["yt.get_stream_url", "sc.search", "sc.get_stream_url"]


def test_successful_youtube_extraction_skips_every_fallback():
    log = []
    yt = _Youtube(stream="http://yt/stream", log=log)
    sc = _SoundCloud(results=[{"source_id": "77"}], stream="http://sc/stream", log=log)
    engine = _engine(_core(youtube=yt, soundcloud=sc))

    assert engine.resolve_stream_url(_yt_track()) == "http://yt/stream"
    assert log == ["yt.get_stream_url"]


# --------------------------------------------------------------------------- #
# YouTube branch: duration bookkeeping
# --------------------------------------------------------------------------- #

def test_youtube_duration_is_persisted_in_seconds():
    """services/youtube_service.py:767 passes yt-dlp's ``info['duration']``,
    which is already SECONDS - engine.py must not scale it."""
    db = _Db()
    yt = _Youtube(stream="http://yt/stream", meta={"duration": 240})
    engine = _engine(_core(youtube=yt, db=db))
    track = _yt_track(duration=0)

    assert engine.resolve_stream_url(track) == "http://yt/stream"
    assert db.updated == [(1, {"duration": 240})]
    assert track["duration"] == 240, "the caller's dict is updated in place"


def test_youtube_duration_is_not_stored_when_the_track_already_has_one():
    db = _Db()
    yt = _Youtube(stream="http://yt/stream", meta={"duration": 240})
    engine = _engine(_core(youtube=yt, db=db))

    engine.resolve_stream_url(_yt_track(duration=199))

    assert db.updated == [], "a known duration must win over the provider's"


def test_youtube_duration_of_zero_is_ignored():
    db = _Db()
    yt = _Youtube(stream="http://yt/stream", meta={"duration": 0})
    engine = _engine(_core(youtube=yt, db=db))

    assert engine.resolve_stream_url(_yt_track(duration=0)) == "http://yt/stream"
    assert db.updated == []


def test_youtube_duration_write_failure_does_not_lose_the_stream_url():
    db = _Db()
    db.raise_on_update = True
    yt = _Youtube(stream="http://yt/stream", meta={"duration": 240})
    engine = _engine(_core(youtube=yt, db=db))

    assert engine.resolve_stream_url(_yt_track(duration=0)) == "http://yt/stream"


def test_youtube_duration_is_not_persisted_for_a_track_without_an_id():
    db = _Db()
    yt = _Youtube(stream="http://yt/stream", meta={"duration": 240})
    engine = _engine(_core(youtube=yt, db=db))
    track = _yt_track(id=None, duration=0)

    assert engine.resolve_stream_url(track) == "http://yt/stream"
    assert db.updated == []


@pytest.mark.xfail(
    strict=True,
    reason="BUG audio/engine.py:406 - the SoundCloud branch divides the provider's "
           "duration by 1000, but services/soundcloud_service.py:483 already returns "
           "SECONDS, so int(240/1000) == 0 and the duration is never persisted "
           "(a 30-minute track would be stored as 1 second)",
)
def test_soundcloud_duration_is_persisted_in_seconds():
    db = _Db()
    sc = _SoundCloud(stream="http://sc/stream", meta={"duration": 240})
    engine = _engine(_core(soundcloud=sc, db=db))
    track = {"id": 5, "source": "soundcloud", "source_id": "77",
             "title": "Song", "artist": "Artist", "duration": 0}

    assert engine.resolve_stream_url(track) == "http://sc/stream"
    assert db.updated == [(5, {"duration": 240})]
    assert track["duration"] == 240


def test_soundcloud_duration_units_are_inconsistent_with_the_youtube_branch():
    """The two branches of the same function disagree about the units: given the
    identical metadata payload, one persists it and the other drops it."""
    db = _Db()
    sc = _SoundCloud(stream="http://sc/stream", meta={"duration": 240})
    engine = _engine(_core(soundcloud=sc, db=db))

    engine.resolve_stream_url({"id": 5, "source": "soundcloud", "source_id": "77",
                               "title": "Song", "artist": "A", "duration": 0})

    assert db.updated == [], (
        "documents BUG audio/engine.py:406 - /1000 turns the provider's 240s into 0"
    )


# --------------------------------------------------------------------------- #
# YouTube branch: tier 1 - SoundCloud search fallback
# --------------------------------------------------------------------------- #

def test_soundcloud_fallback_uses_the_first_search_hit():
    sc = _SoundCloud(results=[{"source_id": "77", "source_url": "https://soundcloud.com/a/b"}],
                     stream="http://sc/stream")
    engine = _engine(_core(youtube=_Youtube(error="no stream"), soundcloud=sc))

    assert engine.resolve_stream_url(_yt_track()) == "http://sc/stream"
    assert sc.stream_calls == ["https://soundcloud.com/a/b"], "source_url wins over source_id"


def test_soundcloud_fallback_falls_back_to_source_id_without_a_url():
    sc = _SoundCloud(results=[{"source_id": "77"}], stream="http://sc/stream")
    engine = _engine(_core(youtube=_Youtube(error="no stream"), soundcloud=sc))

    assert engine.resolve_stream_url(_yt_track()) == "http://sc/stream"
    assert sc.stream_calls == ["77"]


def test_soundcloud_fallback_without_usable_ids_still_calls_the_provider():
    """Pinned current behaviour: the engine does not filter a hit that carries
    neither source_url nor source_id, it forwards None to the provider."""
    sc = _SoundCloud(results=[{"title": "no ids here"}], stream="http://sc/stream")
    engine = _engine(_core(youtube=_Youtube(error="no stream"), soundcloud=sc))

    assert engine.resolve_stream_url(_yt_track()) == "http://sc/stream"
    assert sc.stream_calls == [None]


def test_soundcloud_fallback_caches_the_resolved_url():
    db = _Db()
    sc = _SoundCloud(results=[{"source_id": "77"}], stream="http://sc/stream")
    engine = _engine(_core(youtube=_Youtube(error="no stream"), soundcloud=sc, db=db))

    engine.resolve_stream_url(_yt_track())

    assert db.cached == [("youtube", "dQw4w9WgXcQ", "http://sc/stream")]


def test_soundcloud_fallback_caches_without_a_track_id():
    db = _Db()
    sc = _SoundCloud(results=[{"source_id": "77"}], stream="http://sc/stream")
    engine = _engine(_core(youtube=_Youtube(error="no stream"), soundcloud=sc, db=db))

    engine.resolve_stream_url(_yt_track(id=None))

    assert db.cached == [], "stream_cache is keyed by a row id"
    assert db.updated == []


def test_soundcloud_fallback_failure_moves_to_the_next_candidate():
    sc = _SoundCloud(results=[{"source_id": "77"}], error="preview only")
    yt = _Youtube(error="no stream", results=[{"source_id": "newvid"}], stream="http://yt/tier2")
    engine = _engine(_core(youtube=yt, soundcloud=sc))

    assert engine.resolve_stream_url(_yt_track()) == "http://yt/tier2"
    assert len(sc.search_calls) == 3, "all three candidates are tried"
    assert len(sc.stream_calls) == 3


def test_soundcloud_stage_is_skipped_when_the_provider_is_missing():
    """No soundcloud service => no SoundCloud search, straight to tier 2."""
    yt = _Youtube(error="no stream", results=[{"source_id": "newvid"}], stream="http://yt/tier2")
    engine = _engine(_core(youtube=yt, soundcloud=None))
    engine.app_core.soundcloud = None

    assert engine.resolve_stream_url(_yt_track()) == "http://yt/tier2"
    assert yt.search_calls, "tier 2 must still run"


def test_soundcloud_search_that_raises_is_survived():
    sc = _SoundCloud(results=[{"source_id": "77"}], stream="http://sc/stream")

    def _boom(*a, **kw):
        raise RuntimeError("provider exploded")

    sc.search = _boom
    yt = _Youtube(error="no stream", results=[{"source_id": "newvid"}], stream="http://yt/tier2")
    engine = _engine(_core(youtube=yt, soundcloud=sc))

    assert engine.resolve_stream_url(_yt_track()) == "http://yt/tier2"


# --------------------------------------------------------------------------- #
# YouTube branch: query building for the SoundCloud stage
# --------------------------------------------------------------------------- #

def test_fallback_queries_strip_official_noise_and_are_capped_at_three():
    sc = _SoundCloud(error="no stream")
    engine = _engine(_core(youtube=_Youtube(error="no stream"), soundcloud=sc))

    engine.resolve_stream_url(_yt_track(title="Song (Official Video)", artist="Artist"))

    assert [q for q, _ in sc.search_calls] == [
        "Artist Song",
        "Song",
        "Artist Song (Official Video)",
    ], "candidates are de-duplicated, noise-cleaned and truncated to 3"


def test_fallback_queries_split_an_artist_dash_title():
    sc = _SoundCloud(error="no stream")
    engine = _engine(_core(youtube=_Youtube(error="no stream"), soundcloud=sc))

    engine.resolve_stream_url(_yt_track(title="BB - CC (Official)", artist="AA"))

    assert [q for q, _ in sc.search_calls] == ["BB CC", "CC", "AA BB CC"]


def test_fallback_queries_drop_an_artist_already_present_in_the_title():
    sc = _SoundCloud(error="no stream")
    engine = _engine(_core(youtube=_Youtube(error="no stream"), soundcloud=sc))

    engine.resolve_stream_url(_yt_track(title="Radiohead - Creep", artist="Radiohead"))

    assert [q for q, _ in sc.search_calls] == ["Radiohead Creep", "Creep", "Radiohead - Creep"]


def test_soundcloud_stage_requests_at_most_three_hits():
    sc = _SoundCloud(error="no stream")
    engine = _engine(_core(youtube=_Youtube(error="no stream"), soundcloud=sc))

    engine.resolve_stream_url(_yt_track())

    assert {max_results for _, max_results in sc.search_calls} == {3}


# --------------------------------------------------------------------------- #
# YouTube branch: tier 2 - YouTube search fallback
# --------------------------------------------------------------------------- #

def test_tier2_search_query_and_extraction_of_the_new_id():
    yt = _Youtube(error="no stream", results=[{"source_id": "newvid"}], stream="http://yt/tier2")
    sc = _SoundCloud(error="no stream")
    engine = _engine(_core(youtube=yt, soundcloud=sc))

    assert engine.resolve_stream_url(_yt_track()) == "http://yt/tier2"
    assert yt.search_calls == [("Artist Song audio", 1)]
    assert yt.stream_calls == [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",  # tier 0
        "newvid",                                        # tier 2
    ]


def test_tier2_is_skipped_when_the_search_returns_the_same_id():
    yt = _Youtube(error="no stream", results=[{"source_id": "dQw4w9WgXcQ"}])
    engine = _engine(_core(youtube=yt, soundcloud=_SoundCloud(error="no stream")))

    assert engine.resolve_stream_url(_yt_track()) is None
    assert yt.stream_calls == ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"], (
        "re-extracting the same video id must not loop"
    )


def test_tier2_is_skipped_when_the_search_hit_has_no_id():
    yt = _Youtube(error="no stream", results=[{"title": "no id"}])
    engine = _engine(_core(youtube=yt, soundcloud=_SoundCloud(error="no stream")))

    assert engine.resolve_stream_url(_yt_track()) is None
    assert len(yt.stream_calls) == 1


def test_tier2_search_error_is_survived():
    yt = _Youtube(error="no stream", search_error="rate limited")
    engine = _engine(_core(youtube=yt, soundcloud=_SoundCloud(error="no stream")))

    assert engine.resolve_stream_url(_yt_track()) is None


def test_tier2_search_that_raises_is_survived():
    yt = _Youtube(error="no stream", results=[{"source_id": "newvid"}], stream="http://yt/tier2")
    yt.search = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom"))
    engine = _engine(_core(youtube=yt, soundcloud=_SoundCloud(error="no stream")))

    assert engine.resolve_stream_url(_yt_track()) is None


def test_tier2_does_not_cache_the_url_it_finds():
    """Tier 2 is the last resort: its URL is not written to stream_cache
    (only the SoundCloud stage persists), so the next resolve re-runs."""
    db = _Db()
    yt = _Youtube(error="no stream", results=[{"source_id": "newvid"}], stream="http://yt/tier2")
    engine = _engine(_core(youtube=yt, soundcloud=_SoundCloud(error="no stream"), db=db))

    assert engine.resolve_stream_url(_yt_track()) == "http://yt/tier2"
    assert db.cached == []


# --------------------------------------------------------------------------- #
# the shared cascade budget (cascade_deadline = time.monotonic() + 20.0)
# --------------------------------------------------------------------------- #

def _fake_clock(monkeypatch, start=1000.0, step=0.0):
    """Install a fake time module into audio.engine only (nothing global)."""
    clock = _Clock(start, step)
    monkeypatch.setattr(engine_mod, "time", _FakeTimeModule(time, clock))
    return clock


def test_an_exhausted_budget_skips_every_fallback_stage(monkeypatch):
    """A clock that jumps 25s per read: nothing after the tier-0 extraction
    may run, which is only true because cascade_deadline is < 25s."""
    _fake_clock(monkeypatch, step=25.0)

    yt = _Youtube(error="no stream", results=[{"source_id": "newvid"}], stream="http://yt/tier2")
    sc = _SoundCloud(results=[{"source_id": "77"}], stream="http://sc/stream")
    engine = _engine(_core(youtube=yt, soundcloud=sc))

    assert engine.resolve_stream_url(_yt_track()) is None
    assert yt.stream_calls == ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]
    assert sc.search_calls == [], "the SoundCloud stage must respect the budget"
    assert yt.search_calls == [], "tier 2 must respect the budget"


def test_the_budget_is_shared_between_the_two_fallback_stages(monkeypatch):
    """Each SoundCloud search costs 5 fake seconds: 20s of budget fits three
    candidates, and tier 2 is then skipped because it runs out of time."""
    clock = _fake_clock(monkeypatch)

    sc = _SoundCloud(error="no stream", clock=clock, cost=5.0)
    yt = _Youtube(error="no stream", results=[{"source_id": "newvid"}], stream="http://yt/tier2",
                  clock=clock, cost=5.0)
    engine = _engine(_core(youtube=yt, soundcloud=sc))

    assert engine.resolve_stream_url(_yt_track()) is None
    assert len(sc.search_calls) == 3
    assert yt.search_calls == [], "5s x 4 calls must not fit into the 20s budget"


def test_a_fast_cascade_still_reaches_tier_two(monkeypatch):
    clock = _fake_clock(monkeypatch)

    sc = _SoundCloud(error="no stream", clock=clock, cost=4.0)
    yt = _Youtube(error="no stream", results=[{"source_id": "newvid"}], stream="http://yt/tier2",
                  clock=clock)
    engine = _engine(_core(youtube=yt, soundcloud=sc))

    assert engine.resolve_stream_url(_yt_track()) == "http://yt/tier2"
    assert len(sc.search_calls) == 3
    assert yt.search_calls == [("Artist Song audio", 1)]


def test_the_budget_covers_the_stream_extraction_step_too(monkeypatch):
    """A SoundCloud *search* that is fast but whose stream extraction eats the
    remaining budget must not start the next candidate."""
    clock = _fake_clock(monkeypatch)

    sc = _SoundCloud(results=[{"source_id": "77"}], clock=clock, cost=12.0)
    yt = _Youtube(error="no stream", results=[{"source_id": "newvid"}], stream="http://yt/tier2",
                  clock=clock)
    engine = _engine(_core(youtube=yt, soundcloud=sc))

    assert engine.resolve_stream_url(_yt_track()) is None
    assert len(sc.search_calls) == 2, "12s + 12s no longer fit into 20s"
    assert yt.search_calls == []


# --------------------------------------------------------------------------- #
# the oEmbed title lookup (a real network call, stubbed here)
# --------------------------------------------------------------------------- #

class _FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_missing_title_triggers_exactly_one_oembed_lookup(monkeypatch):
    """A track without a title gets one oEmbed round trip (audio/engine.py:209)
    *before* the cascade deadline is even computed."""
    requested = []

    def _fake_urlopen(req, timeout=None):
        requested.append((req.full_url, timeout))
        return _FakeResponse({"title": "Real Title", "author_name": "Real Artist"})

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    sc = _SoundCloud(error="no stream")
    engine = _engine(_core(youtube=_Youtube(error="no stream"), soundcloud=sc))

    assert engine.resolve_stream_url({"id": 1, "source": "youtube",
                                      "source_id": "dQw4w9WgXcQ"}) is None
    assert len(requested) == 1
    assert "oembed" in requested[0][0] and "v=dQw4w9WgXcQ" in requested[0][0]
    assert requested[0][1] == 3.0, "the lookup is capped at 3s"
    assert [q for q, _ in sc.search_calls] == ["Real Artist Real Title", "Real Title",
                                               "Real Artist Real Title"]


def test_oembed_failure_falls_back_to_the_raw_metadata(monkeypatch):
    def _boom(*a, **kw):
        raise OSError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    sc = _SoundCloud(error="no stream")
    engine = _engine(_core(youtube=_Youtube(error="no stream"), soundcloud=sc))

    assert engine.resolve_stream_url({"id": 1, "source": "youtube",
                                      "source_id": "dQw4w9WgXcQ",
                                      "title": "Hashy", "artist": "Artist"}) is None
    assert sc.search_calls == [], "'Hashy' is 5 chars: no oEmbed, no usable query"


def test_hash_like_title_triggers_the_oembed_lookup(monkeypatch):
    requested = []

    def _fake_urlopen(req, timeout=None):
        requested.append(req.full_url)
        return _FakeResponse({"title": "Real Title"})

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    sc = _SoundCloud(error="no stream")
    engine = _engine(_core(youtube=_Youtube(error="no stream"), soundcloud=sc))

    engine.resolve_stream_url(_yt_track(title="dQw4w9WgXc", artist="Artist"))

    assert len(requested) == 1
    assert [q for q, _ in sc.search_calls] == ["Artist Real Title", "Real Title"]


def test_no_oembed_lookup_for_a_real_title(_no_network):
    """Sanity check on the guard: a real title must never hit the network."""
    sc = _SoundCloud(error="no stream")
    engine = _engine(_core(youtube=_Youtube(error="no stream"), soundcloud=sc))

    engine.resolve_stream_url(_yt_track())

    assert _no_network == [], "urlopen must not be called for a usable title"


# --------------------------------------------------------------------------- #
# SoundCloud / Spotify / Yandex branches
# --------------------------------------------------------------------------- #

def test_soundcloud_branch_resolves_the_permalink_directly():
    log = []
    sc = _SoundCloud(stream="http://sc/stream", meta={"duration": 240}, log=log)
    yt = _Youtube(error="must not run", log=log)
    engine = _engine(_core(youtube=yt, soundcloud=sc))

    track = {"id": 3, "source": "soundcloud", "source_id": "https://soundcloud.com/a/b",
             "title": "Song", "artist": "Artist"}
    assert engine.resolve_stream_url(track) == "http://sc/stream"
    assert sc.stream_calls == ["https://soundcloud.com/a/b"]
    assert log == ["sc.get_stream_url"]


def test_soundcloud_branch_target_falls_back_through_source_url_and_url():
    sc = _SoundCloud(stream="http://sc/stream")
    engine = _engine(_core(youtube=_Youtube(error="no stream"), soundcloud=sc))

    assert engine.resolve_stream_url({"source": "soundcloud", "source_url": "https://soundcloud.com/a/b",
                                      "title": "T"}) == "http://sc/stream"
    assert sc.stream_calls == ["https://soundcloud.com/a/b"]


def test_soundcloud_branch_target_is_built_from_artist_and_title():
    sc = _SoundCloud(stream="http://sc/stream")
    engine = _engine(_core(youtube=_Youtube(error="must not run"), soundcloud=sc))

    assert engine.resolve_stream_url({"id": 3, "source": "soundcloud",
                                      "title": "Song", "artist": "Artist"}) == "http://sc/stream"
    assert sc.stream_calls == ["Artist Song"]


def test_soundcloud_failure_falls_back_to_a_youtube_search():
    log = []
    sc = _SoundCloud(error="track is unavailable", log=log)
    yt = _Youtube(results=[{"source_id": "newvid"}], stream="http://yt/fallback", log=log)
    engine = _engine(_core(youtube=yt, soundcloud=sc))

    track = {"id": 3, "source": "soundcloud", "source_id": "77",
             "title": "Song", "artist": "Artist"}
    assert engine.resolve_stream_url(track) == "http://yt/fallback"
    assert log == ["sc.get_stream_url", "yt.search", "yt.get_stream_url"]
    assert yt.search_calls == [("Artist Song", 1)]


def test_soundcloud_failure_without_a_title_skips_the_youtube_fallback():
    yt = _Youtube(results=[{"source_id": "newvid"}], stream="http://yt/fallback")
    sc = _SoundCloud(error="track is unavailable")
    engine = _engine(_core(youtube=yt, soundcloud=sc))

    assert engine.resolve_stream_url({"source": "soundcloud", "source_id": "77"}) is None
    assert yt.search_calls == [], "with no title there is nothing to search for"


def test_soundcloud_branch_stream_extraction_that_raises_is_survived():
    sc = _SoundCloud(error="nope")
    sc.get_stream_url = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom"))
    engine = _engine(_core(youtube=_Youtube(error="no stream"), soundcloud=sc))

    assert engine.resolve_stream_url({"id": 3, "source": "soundcloud", "source_id": "77"}) is None


def test_spotify_branch_searches_youtube_for_the_first_hit():
    log = []
    yt = _Youtube(results=[{"source_id": "newvid"}], stream="http://yt/spotify", log=log)
    engine = _engine(_core(youtube=yt, soundcloud=_SoundCloud(error="must not run", log=log)))

    track = {"id": 8, "source": "spotify", "source_id": "spotify_track:xyz",
             "title": "Song", "artist": "Artist"}
    assert engine.resolve_stream_url(track) == "http://yt/spotify"
    assert yt.search_calls == [("Artist Song", 1)]
    assert yt.stream_calls == ["newvid"]
    assert log == ["yt.search", "yt.get_stream_url"]


def test_spotify_branch_with_no_hits_returns_none():
    yt = _Youtube(results=[])
    engine = _engine(_core(youtube=yt))

    track = {"id": 8, "source": "spotify", "source_id": "x", "title": "Song", "artist": "Artist"}
    assert engine.resolve_stream_url(track) is None
    assert yt.stream_calls == []


def test_spotify_branch_search_error_returns_none():
    yt = _Youtube(search_error="rate limited")
    engine = _engine(_core(youtube=yt))

    track = {"id": 8, "source": "spotify", "source_id": "x", "title": "Song", "artist": "A"}
    assert engine.resolve_stream_url(track) is None


def test_spotify_branch_search_that_raises_returns_none():
    yt = _Youtube()
    yt.search = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom"))
    engine = _engine(_core(youtube=yt))

    track = {"id": 8, "source": "spotify", "source_id": "x", "title": "Song", "artist": "A"}
    assert engine.resolve_stream_url(track) is None


def test_yandex_branch_resolves_through_the_yandex_service():
    yandex = _Yandex(stream="http://yandex/stream")
    engine = _engine(_core(yandex=yandex, youtube=_Youtube(error="must not run")))

    track = {"id": 9, "source": "yandex", "source_id": "12345", "title": "T", "artist": "A"}
    assert engine.resolve_stream_url(track) == "http://yandex/stream"
    assert yandex.stream_calls == ["12345"]


def test_yandex_branch_failure_returns_none():
    yandex = _Yandex(error="track is not available")
    engine = _engine(_core(yandex=yandex))

    track = {"id": 9, "source": "yandex", "source_id": "12345", "title": "T", "artist": "A"}
    assert engine.resolve_stream_url(track) is None


def test_yandex_branch_without_a_service_returns_none():
    engine = _engine(_core(youtube=_Youtube(error="must not run")))

    track = {"id": 9, "source": "yandex", "source_id": "12345", "title": "T", "artist": "A"}
    with pytest.raises(AttributeError):
        engine.resolve_stream_url(track)


# --------------------------------------------------------------------------- #
# AUDIT-F BUG-1: len() on a non-string source_id
# --------------------------------------------------------------------------- #

@pytest.mark.xfail(
    strict=True,
    reason="BUG audio/engine.py:172 - `len(source_id)` is called on a value that "
           "falls back to tracks.id (an INTEGER). A DB row whose source_id is NULL "
           "makes resolve_stream_url() raise TypeError instead of resolving; with a "
           "resolver attached the error is swallowed and the track silently never plays",
)
def test_int_source_id_must_resolve_instead_of_raising():
    engine = _engine(_core(youtube=_Youtube(stream="http://yt/stream")))

    assert engine.resolve_stream_url(
        {"id": 12345, "source": "youtube", "title": "Song", "artist": "Artist"}
    ) == "http://yt/stream"


def test_int_source_id_is_swallowed_by_the_resolver():
    """Documents the same bug with production wiring (AppCore always installs a
    StreamResolver, core/app.py:113): no crash, but a silent 'cannot resolve'."""
    yt = _Youtube(stream="http://yt/stream")
    engine = _engine(_core(youtube=yt, resolver=StreamResolver(db=None)))

    assert engine.resolve_stream_url(
        {"id": 12345, "source": "youtube", "title": "Song", "artist": "Artist"}
    ) is None
    assert yt.stream_calls == [], "the cascade died before reaching the provider"


def test_int_source_id_is_fine_for_the_soundcloud_branch():
    """Only the YouTube branch calls len(): SoundCloud str()s the target."""
    sc = _SoundCloud(stream="http://sc/stream")
    engine = _engine(_core(youtube=_Youtube(error="must not run"), soundcloud=sc))

    assert engine.resolve_stream_url(
        {"id": 12345, "source": "soundcloud", "title": "Song", "artist": "Artist"}
    ) == "http://sc/stream"
    assert sc.stream_calls == ["12345"]