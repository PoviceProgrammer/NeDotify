"""StreamResolver state tests: P2-6 (stats under the lock) + refresh/_persist.

Pre-fix failures:
  * ``_stats["network_cascades"] += 1`` ran OUTSIDE ``self._lock`` while
    ``stats()`` reads the same dict under the lock. Non-atomic read-modify-write
    on shared state -> lost updates.
  * ``refresh()`` and ``_persist()`` were near-identical copies, so a fix to one
    silently skipped the other.
"""

import threading

from core.resolver import StreamResolver


class _NoDb:
    """Records cache_stream calls; stands in for the DB."""

    def __init__(self):
        self.cached = []

    def cache_stream(self, source, source_id, stream_url):
        self.cached.append((source, source_id, stream_url))

    def get_cached_stream(self, source, source_id, max_age_seconds=None):
        return None

    def invalidate_cached_stream(self, source, source_id):
        pass


# --- P2-6: stats are mutated only under the lock ----------------------------

def test_network_cascades_incremented_once_per_owner():
    """Single-flight must still mean exactly one cascade per key."""
    r = StreamResolver(db=None)
    calls = {"n": 0}

    def resolver_fn():
        calls["n"] += 1
        return ("url", None)

    assert r.resolve("yt", "a", resolver_fn) == "url"
    assert calls["n"] == 1
    assert r.stats()["network_cascades"] == 1
    assert r.stats()["single_flight_waits"] == 0


def test_network_cascades_count_not_lost_under_concurrency():
    """Every real cascade must be counted, even when threads collide.

    Pre-fix the counter was incremented outside the lock, so concurrent
    read-modify-write pairs dropped increments.
    """
    r = StreamResolver(db=None)
    threads_count = 8
    barrier = threading.Barrier(threads_count)

    def worker(i):
        barrier.wait()          # maximise contention on the stats dict
        r.resolve("yt", f"k{i}", lambda: (f"url-{i}", None))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(threads_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert r.stats()["network_cascades"] == threads_count


def test_stats_mutations_happen_under_the_lock():
    """Assert the invariant directly: _stats is only written while locked.

    ``_lock`` is replaced by a counting wrapper and ``_stats`` by a dict that
    records writes seen at depth 0. Any mutation outside the critical section
    is reported. (A non-blocking re-acquire cannot be used to detect this:
    threading.Lock is not re-entrant and never reports its own owner.)
    """
    r = StreamResolver(db=None)
    violations = []

    class _CountingLock:
        def __init__(self):
            self._inner = threading.Lock()
            self.depth = 0

        def acquire(self, *a, **kw):
            got = self._inner.acquire(*a, **kw)
            if got:
                self.depth += 1
            return got

        def release(self):
            self.depth -= 1
            self._inner.release()

        def __enter__(self):
            self.acquire()
            return self

        def __exit__(self, *exc):
            self.release()
            return False

    class _CheckedStats(dict):
        def __setitem__(self, k, v):
            if r._lock.depth == 0:
                violations.append(k)
            super().__setitem__(k, v)

    r._lock = _CountingLock()
    r._stats = _CheckedStats(r._stats)

    assert r.resolve("yt", "a", lambda: ("url-a", None)) == "url-a"
    assert r.resolve("yt", "b", lambda: ("url-b", None)) == "url-b"
    r.get_cached_url("yt", "a")

    assert not violations, f"_stats mutated outside the lock: {violations}"


def test_stats_and_resolve_are_safe_concurrently():
    """Reader thread hammering stats() while resolves run."""
    r = StreamResolver(db=None)
    errors = []
    stop = threading.Event()

    def reader():
        try:
            while not stop.is_set():
                s = r.stats()
                assert set(s) == {
                    "mem_hits", "db_hits", "network_cascades", "single_flight_waits"
                }
        except Exception as e:  # pragma: no cover - failure path
            errors.append(repr(e))

    readers = [threading.Thread(target=reader) for _ in range(3)]
    for t in readers:
        t.start()
    try:
        for i in range(40):
            r.resolve("yt", f"k{i}", lambda: (f"url-{i}", None))
    finally:
        stop.set()
        for t in readers:
            t.join()

    assert not errors, errors


def test_single_flight_shares_one_cascade():
    """Concurrent callers for one key wait on a single flight."""
    r = StreamResolver(db=None)
    calls = {"n": 0}
    release = threading.Event()

    def resolver_fn():
        calls["n"] += 1
        release.wait(5)
        return ("url", None)

    threads = [threading.Thread(target=lambda: r.resolve("yt", "same", resolver_fn))
               for _ in range(5)]
    for t in threads:
        t.start()
    threading.Event().wait(0.15)
    release.set()
    for t in threads:
        t.join(5)

    assert calls["n"] == 1, "single-flight broken: more than one cascade ran"
    stats = r.stats()
    assert stats["network_cascades"] == 1
    assert stats["single_flight_waits"] >= 1


def test_db_hits_counted_under_the_lock():
    """db_hits was also incremented outside the critical section."""
    db = _NoDb()
    r = StreamResolver(db=db)
    db.cached.append(("yt", "x", "cached-url"))

    def get_cached_stream(source, source_id, max_age_seconds=None):
        return {"stream_url": "cached-url"} if source_id == "x" else None

    db.get_cached_stream = get_cached_stream

    assert r.get_cached_url("yt", "x") == "cached-url"
    assert r.stats()["db_hits"] == 1


# --- refresh / _persist de-duplication --------------------------------------

def test_refresh_stores_in_memory_and_db():
    """refresh() must still populate both cache layers."""
    db = _NoDb()
    r = StreamResolver(db=db)

    r.refresh("yt", "a", "http://fresh")

    assert r.get_cached_url("yt", "a") == "http://fresh"
    assert db.cached == [("yt", "a", "http://fresh")]


def test_refresh_ignores_empty_url():
    """The `if not stream_url: return` guard is preserved."""
    db = _NoDb()
    r = StreamResolver(db=db)

    r.refresh("yt", "a", "")
    r.refresh("yt", "a", None)

    assert r._mem == {}
    assert db.cached == []


def test_refresh_and_persist_share_one_code_path():
    """Both entry points must produce identical cache state."""
    db = _NoDb()
    r = StreamResolver(db=db)

    r.refresh("yt", "via-refresh", "http://u1")
    r._persist("yt", "via-persist", "http://u2")

    assert db.cached == [
        ("yt", "via-refresh", "http://u1"),
        ("yt", "via-persist", "http://u2"),
    ]
    assert r.get_cached_url("yt", "via-refresh") == "http://u1"
    assert r.get_cached_url("yt", "via-persist") == "http://u2"


def test_resolve_persists_via_the_same_path():
    """A successful resolve reaches both layers, like refresh does."""
    db = _NoDb()
    r = StreamResolver(db=db)

    assert r.resolve("yt", "a", lambda: ("http://resolved", None)) == "http://resolved"
    assert db.cached == [("yt", "a", "http://resolved")]


def test_invalidate_clears_both_layers():
    db = _NoDb()
    r = StreamResolver(db=db)
    r.refresh("yt", "a", "http://x")
    r.invalidate("yt", "a")
    assert ("yt", "a") not in r._mem
    assert r.get_cached_url("yt", "a") is None