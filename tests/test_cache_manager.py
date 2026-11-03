"""Cache quota accounting focuses on evictable stream files."""

import logging
import threading

from utils.cache_manager import CacheManager


def _bare_cache(tmp_path, db):
    cache = CacheManager.__new__(CacheManager)
    cache.db = db
    cache._base_dir = str(tmp_path)
    cache._covers_dir = str(tmp_path / "covers")
    cache._streams_dir = str(tmp_path / "streams")
    cache._temp_dir = str(tmp_path / "temp")
    for name in ("covers", "streams", "temp"):
        (tmp_path / name).mkdir(exist_ok=True)
    cache._size_cache_lock = threading.Lock()
    cache._cached_size_bytes = 0
    cache._last_size_scan = 0.0
    cache._active_downloads = set()
    cache._active_downloads_lock = threading.Lock()
    cache.logger = logging.getLogger("test-cache-manager")
    return cache


def test_stream_quota_does_not_evict_every_stream_when_other_cache_is_large(tmp_path, tmp_db):
    cache = _bare_cache(tmp_path, tmp_db)
    (tmp_path / "streams" / "a.mp3").write_bytes(b"1234")
    (tmp_path / "streams" / "b.mp3").write_bytes(b"5678")
    (tmp_path / "covers" / "cover.jpg").write_bytes(b"c" * 100)
    (tmp_path / "temp" / "partial.part").write_bytes(b"t" * 50)

    assert cache.purge_stream_cache(quota_bytes=10) == 0
    details = cache.get_storage_details()
    assert details["used_bytes"] == 8
    assert details["total_cache_bytes"] == 158
    assert (tmp_path / "streams" / "a.mp3").exists()
    assert (tmp_path / "streams" / "b.mp3").exists()


def test_cache_manager_without_settings_defaults_safely(tmp_path, tmp_db):
    cache = _bare_cache(tmp_path, tmp_db)
    (tmp_path / "streams" / "small.mp3").write_bytes(b"x")

    details = cache.get_storage_details()

    assert details["quota_gb"] == 5
    assert cache.purge_stream_cache() == 0
