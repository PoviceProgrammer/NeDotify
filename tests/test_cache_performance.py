"""Background caching reuses complete audio and keeps quota protection intact."""

from pathlib import Path

import pytest

from tests.helpers import DeferredExecutor
from utils.cache_manager import CacheManager


@pytest.fixture
def cache(tmp_db, redirect_home):
    manager = CacheManager(tmp_db)
    manager._executor.shutdown(wait=True)
    manager._executor = DeferredExecutor()
    return manager


def test_existing_audio_skips_extraction_and_quota_scan(cache, monkeypatch):
    import yt_dlp

    # BUG-A1-006: only hashed-stem cache files are trusted, so the seeded
    # complete audio must live under the current naming scheme.
    from utils.cache_manager import stream_cache_stem
    audio_path = Path(cache.streams_dir) / (stream_cache_stem('youtube', 'existing') + '.m4a')
    audio_path.write_bytes(b'audio' * 2048)
    cache.db.cache_stream('youtube', 'existing', 'https://media.googlevideo.com/audio')
    cache.db.set_cached_file('youtube', 'existing', str(audio_path))
    cache.db.conn.execute("UPDATE stream_cache SET cached_at = datetime('now', '-1 day')")
    cache.db.conn.commit()

    def unexpected_work(*args, **kwargs):
        pytest.fail('Complete cached audio must not be downloaded or scanned again')

    monkeypatch.setattr(yt_dlp, 'YoutubeDL', unexpected_work)
    monkeypatch.setattr(cache, 'purge_stream_cache', unexpected_work)
    cache.download_audio_stream('youtube', 'existing', 'https://media.googlevideo.com/audio')
    assert len(cache._executor.tasks) == 1
    cache._executor.tasks.pop()()

    assert not cache._active_downloads
    assert audio_path.read_bytes() == b'audio' * 2048


@pytest.mark.parametrize('cached_state', ['missing', 'empty', 'truncated', 'wrong_extension'])
def test_invalid_cached_audio_is_downloaded_again(cache, monkeypatch, cached_state):
    from tests.audio_helpers import wave_bytes

    suffix = '.html' if cached_state == 'wrong_extension' else '.m4a'
    cached_path = Path(cache.streams_dir) / ('old' + suffix)
    if cached_state != 'missing':
        cached_path.write_bytes(b'audio' * (0 if cached_state == 'empty' else
                                          10 if cached_state == 'truncated' else 2048))
    cache.db.cache_stream('youtube', 'replace', 'https://media.googlevideo.com/audio')
    cache.db.set_cached_file('youtube', 'replace', str(cached_path))
    quota_checks = []
    downloads = []
    monkeypatch.setattr(cache, 'purge_stream_cache', lambda: quota_checks.append(True))

    class Response:
        headers = {'Content-Type': 'audio/wav', 'Content-Length': str(len(wave_bytes()))}
        def __init__(self):
            self.payload = wave_bytes()
        def read(self, count=-1):
            result, self.payload = self.payload[:count], self.payload[count:]
            return result
        def __enter__(self): return self
        def __exit__(self, *_args): return False

    def open_url(url, **_kwargs):
        assert quota_checks
        downloads.append(url.full_url if hasattr(url, 'full_url') else str(url))
        return Response()

    monkeypatch.setattr('utils.url_safety.guarded_open_url', open_url)
    cache.download_audio_stream('youtube', 'replace', 'https://media.googlevideo.com/audio')
    cache.download_audio_stream('youtube', 'replace', 'https://media.googlevideo.com/audio')
    assert len(cache._executor.tasks) == 1
    cache._executor.tasks.pop()()

    assert len(downloads) == 1
    assert len(quota_checks) == 1
    assert not cache._active_downloads
    cached = cache.db.get_cached_stream('youtube', 'replace')
    assert Path(cached['cached_file_path']).read_bytes() == wave_bytes()


def test_size_scan_counts_nested_files_and_reuses_cached_total(cache, monkeypatch):
    nested = Path(cache.streams_dir) / 'nested'
    nested.mkdir()
    (nested / 'audio.m4a').write_bytes(b'audio' * 100)
    (Path(cache.covers_dir) / 'cover.jpg').write_bytes(b'image' * 20)
    (Path(cache.temp_dir) / 'stream.part').write_bytes(b'partial' * 10)

    assert cache.get_cache_size() == 670

    def unexpected_scan(*args):
        pytest.fail('A recent size total must be reused')

    monkeypatch.setattr(cache, '_cache_file_stats', unexpected_scan)
    assert cache.get_cache_size() == 670


def test_purge_preserves_protected_and_active_files_in_nested_folders(cache):
    nested = Path(cache.streams_dir) / 'nested'
    nested.mkdir()
    protected = nested / 'youtube_favorite.m4a'
    active = nested / 'youtube_active.m4a.part'
    temporary = nested / 'youtube_temporary.m4a'
    for audio_path in (protected, active, temporary):
        audio_path.write_bytes(b'audio' * 2048)
    cache.db.add_track(title='Favorite', artist='Artist', source='youtube',
                       source_id='favorite', file_path=str(protected), is_favorite=1)
    cache._active_downloads.add('youtube_active')
    cache.db.cache_stream('youtube', 'temporary', 'https://media.example/audio')
    cache.db.set_cached_file('youtube', 'temporary', str(temporary))

    assert cache.purge_stream_cache(force_all_temporary=True) == 10240

    assert protected.exists()
    assert active.exists()
    assert not temporary.exists()
    assert cache.db.get_cached_stream('youtube', 'temporary')['cached_file_path'] is None


def test_rejected_cache_task_releases_active_download(cache):
    def rejected_task(*args):
        raise RuntimeError('executor is shutting down')

    cache._executor.submit = rejected_task
    cache.download_audio_stream('youtube', 'rejected', 'https://media.googlevideo.com/audio')

    assert not cache._active_downloads
