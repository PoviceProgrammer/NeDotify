"""Cache eviction tests: P2-4 (real LRU) and P2-5 (get_search_cache guard).

Pre-fix these all failed because:
  * set_to_cache / set_search_cache / StreamResolver._mem_set picked
    ``next(iter(cache))``, which is the FIRST-INSERTED key. Re-assigning an
    existing key kept its original position, so a key that had just been
    served from the cache was the next one evicted -> FIFO, not LRU.
  * get_search_cache() did ``entry['ts']`` with no guard, so a raw value in
    _search_cache raised KeyError (get_from_cache() already handled that).
"""

import threading
import time

import pytest

import core.resolver as resolver_module
from core.resolver import StreamResolver
from services.base_service import BaseMusicService


@pytest.fixture(autouse=True)
def isolated_caches():
    """Snapshot and restore the class-level caches/caps shared across tests."""
    stream, search = BaseMusicService._stream_cache, BaseMusicService._search_cache
    max_stream = BaseMusicService._MAX_CACHE_SIZE
    max_search = BaseMusicService._SEARCH_CACHE_MAX_SIZE
    stream.clear()
    search.clear()
    yield
    stream.clear()
    search.clear()
    BaseMusicService._MAX_CACHE_SIZE = max_stream
    BaseMusicService._SEARCH_CACHE_MAX_SIZE = max_search


# --- P2-4: LRU ordering in the stream cache ----------------------------------

def test_stream_cache_evicts_least_recently_used_not_oldest():
    """Touch the oldest key, then insert: the touched key must survive."""
    BaseMusicService._MAX_CACHE_SIZE = 3
    for k in ("a", "b", "c"):
        BaseMusicService.set_to_cache(k, {"v": k})

    # 'a' is the oldest entry; read it so it becomes most-recently-used.
    assert BaseMusicService.get_from_cache("a") == {"v": "a"}

    BaseMusicService.set_to_cache("d", {"v": "d"})

    assert "a" in BaseMusicService._stream_cache, "recently used key was evicted"
    assert "b" not in BaseMusicService._stream_cache, "truly unused key survived"
    assert len(BaseMusicService._stream_cache) == 3


def test_search_cache_evicts_least_recently_used():
    """Same contract for the search cache."""
    BaseMusicService._SEARCH_CACHE_MAX_SIZE = 3
    for k in ("a", "b", "c"):
        BaseMusicService.set_search_cache(k, [k])

    assert BaseMusicService.get_search_cache("a") == ["a"]

    BaseMusicService.set_search_cache("d", ["d"])

    assert "a" in BaseMusicService._search_cache
    assert "b" not in BaseMusicService._search_cache
    assert len(BaseMusicService._search_cache) == 3


def test_overwriting_an_existing_key_refreshes_recency():
    """Re-setting a key makes it most-recently-used (this is the FIFO->LRU hinge)."""
    BaseMusicService._MAX_CACHE_SIZE = 3
    for k in ("a", "b", "c"):
        BaseMusicService.set_to_cache(k, {"v": k})

    BaseMusicService.set_to_cache("a", {"v": "a2"})   # update, no size change
    assert len(BaseMusicService._stream_cache) == 3
    assert BaseMusicService.get_from_cache("a") == {"v": "a2"}

    BaseMusicService.set_to_cache("d", {"v": "d"})
    assert "a" in BaseMusicService._stream_cache
    assert "b" not in BaseMusicService._stream_cache


def test_cache_stays_within_cap():
    BaseMusicService._MAX_CACHE_SIZE = 5
    for i in range(50):
        BaseMusicService.set_to_cache(f"k{i}", {"i": i})
    assert len(BaseMusicService._stream_cache) == 5
    # The most recent writes are the ones kept.
    assert "k49" in BaseMusicService._stream_cache


def test_hit_does_not_extend_ttl():
    """Refreshing recency must not restart the TTL clock."""
    BaseMusicService._stream_cache["old"] = {
        "data": {"v": 1}, "ts": time.time() - BaseMusicService._STREAM_CACHE_TTL - 1
    }
    assert BaseMusicService.get_from_cache("old") is None
    assert "old" not in BaseMusicService._stream_cache


def test_search_cache_hit_does_not_extend_ttl():
    BaseMusicService._search_cache["old"] = {
        "data": ["x"], "ts": time.time() - BaseMusicService._SEARCH_CACHE_TTL - 1
    }
    assert BaseMusicService.get_search_cache("old") is None
    assert "old" not in BaseMusicService._search_cache


def test_lru_touch_is_shared_by_both_caches():
    """The helper keeps the plain-dict type: yandex_service iterates these."""
    assert type(BaseMusicService._stream_cache) is dict
    assert type(BaseMusicService._search_cache) is dict


def test_concurrent_cache_writes_keep_the_cap():
    """Lock discipline holds: never more than the cap, no exceptions."""
    BaseMusicService._MAX_CACHE_SIZE = 20
    BaseMusicService._SEARCH_CACHE_MAX_SIZE = 20
    errors = []

    def worker(n):
        try:
            for i in range(200):
                BaseMusicService.set_to_cache(f"w{n}-{i}", {"n": n, "i": i})
                BaseMusicService.get_from_cache(f"w{n}-{i}")
                BaseMusicService.set_search_cache(f"w{n}-{i}", [n, i])
                BaseMusicService.get_search_cache(f"w{n}-{i}")
        except Exception as e:  # pragma: no cover - failure path
            errors.append(repr(e))

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    assert len(BaseMusicService._stream_cache) <= 20
    assert len(BaseMusicService._search_cache) <= 20


# --- P2-5: get_search_cache tolerates raw values -----------------------------

def test_get_search_cache_returns_raw_value():
    """A raw value in _search_cache must come back as-is, not raise KeyError."""
    BaseMusicService._search_cache["raw"] = {"anything": "goes"}
    assert BaseMusicService.get_search_cache("raw") == {"anything": "goes"}


def test_get_search_cache_raw_value_is_not_purged_by_ttl():
    """A raw value has no timestamp, so the TTL check must not touch it."""
    BaseMusicService._search_cache["raw"] = [1, 2, 3]
    assert BaseMusicService.get_search_cache("raw") == [1, 2, 3]
    assert "raw" in BaseMusicService._search_cache


def test_get_search_cache_raw_and_wrapped_agree():
    """Wrapped entries unwrap; raw entries pass through; both are symmetric."""
    BaseMusicService.set_search_cache("wrapped", ["v"])
    assert BaseMusicService.get_search_cache("wrapped") == ["v"]
    assert BaseMusicService.get_search_cache("missing") is None


def test_get_from_cache_raw_value_still_works():
    """Pre-existing behaviour, kept symmetric with the search cache."""
    BaseMusicService._stream_cache["raw"] = {"x": 1}
    assert BaseMusicService.get_from_cache("raw") == {"x": 1}


# --- P2-4: LRU in StreamResolver._mem ----------------------------------------

def test_resolver_mem_cache_evicts_least_recently_used(monkeypatch):
    monkeypatch.setattr(resolver_module, "_MEM_MAX_SIZE", 3)
    r = StreamResolver(db=None)
    for k in "abc":
        r._mem_set(("yt", k), (f"url-{k}", time.time()))

    # A cache hit refreshes recency.
    assert r.get_cached_url("yt", "a") == "url-a"

    r._mem_set(("yt", "d"), ("url-d", time.time()))

    assert ("yt", "a") in r._mem, "recently hit key was evicted"
    assert ("yt", "b") not in r._mem, "unused key survived"
    assert len(r._mem) == 3


def test_resolver_mem_set_updates_recency(monkeypatch):
    monkeypatch.setattr(resolver_module, "_MEM_MAX_SIZE", 3)
    r = StreamResolver(db=None)
    for k in "abc":
        r._mem_set(("yt", k), (f"url-{k}", time.time()))

    r._mem_set(("yt", "a"), ("url-a2", time.time()))
    assert len(r._mem) == 3

    r._mem_set(("yt", "d"), ("url-d", time.time()))
    assert ("yt", "a") in r._mem
    assert ("yt", "b") not in r._mem


def test_resolver_mem_cache_hit_does_not_extend_ttl(monkeypatch):
    r = StreamResolver(db=None, mem_ttl=0.05)
    r._mem_set(("yt", "a"), ("url-a", time.time()))
    assert r.get_cached_url("yt", "a") == "url-a"

    # The hit above must not have restarted the clock.
    time.sleep(0.08)
    assert r.get_cached_url("yt", "a") is None


def test_resolver_mem_hits_are_counted(monkeypatch):
    """Recency bookkeeping must not disturb the hit counters."""
    monkeypatch.setattr(resolver_module, "_MEM_MAX_SIZE", 2)
    r = StreamResolver(db=None)
    r._mem_set(("yt", "a"), ("url-a", time.time()))
    r._mem_set(("yt", "b"), ("url-b", time.time()))
    assert r.get_cached_url("yt", "a") == "url-a"
    assert r.get_cached_url("yt", "a") == "url-a"
    assert r.stats()["mem_hits"] == 2