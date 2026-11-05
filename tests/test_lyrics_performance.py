"""Fast lyrics reuse and wider verified candidate coverage; no live providers/profile."""
import concurrent.futures
import json
import sqlite3
import threading
import time
from contextlib import closing

import pytest

from services.lyrics_cache import LyricsDiskCache
from services.lyrics_service import LyricsService
from services.music_matching import title_metadata


PROVIDERS = ('lrclib', 'netease', 'qqmusic', 'genius', 'megalobiz')


def configure(service, monkeypatch, provider=None):
    for name in PROVIDERS:
        monkeypatch.setattr(service._lookup, name, lambda *args: None)
    if provider:
        monkeypatch.setattr(service._lookup, 'lrclib', provider)
    return service


def result(engine, form, *, synced='[00:01.00] Hello'):
    return engine.accept(form, form['metadata']['title'], form['metadata']['artists'],
                         form['duration'], synced, 'Hello', 'Test')


def form():
    return {'metadata': title_metadata('A Song', 'Artist'), 'duration': 120, 'album': '',
            'fallback': False, 'query_artist': 'Artist', 'query_title': 'A Song'}


def cached_record(**changes):
    return dict(status='found', source='Test', match_type='exact', confidence=1,
                syncedLyrics='[00:01.00] Hello', plainLyrics='Hello', instrumental=False,
                weight=1, matched_title='A Song', matched_artist='Artist', matched_duration=120,
                **changes)


def test_found_survives_service_restart_and_needs_no_network(tmp_path, monkeypatch):
    path = tmp_path / 'lyrics.db'
    first = configure(LyricsService(cache_path=path), monkeypatch)
    calls = []
    def provider(context, *args):
        calls.append(1)
        return result(first._lookup, context)
    monkeypatch.setattr(first._lookup, 'lrclib', provider)
    wanted = first.get_lyrics('A Song', 'Artist', 120000)
    assert path.exists() and wanted['syncedLyrics']
    second = LyricsService(cache_path=path)
    def forbidden(*args):
        calls.append('unexpected network')
        raise AssertionError('Warm disk lookup must not contact providers')
    for name in PROVIDERS:
        monkeypatch.setattr(second._lookup, name, forbidden)
    seen = []
    actual = second.get_lyrics('A Song', 'Artist', 120000, on_update=seen.append)
    assert actual['syncedLyrics'] == wanted['syncedLyrics'] and calls == [1]
    assert len(seen) == 1 and seen[0]['phase'] == 'final' and seen[0]['revision'] == 1


@pytest.mark.parametrize('title,artist,duration', [
    ('A Song (Remix)', 'Artist', 120000), ('A Song', 'Other Artist', 120000),
    ('A Song', 'Artist', 121000), ('A Song (Live)', 'Artist', 120000),
])
def test_disk_cache_does_not_cross_identity_or_timing(tmp_path, monkeypatch, title, artist, duration):
    path = tmp_path / 'lyrics.db'
    first = configure(LyricsService(cache_path=path), monkeypatch)
    monkeypatch.setattr(first._lookup, 'lrclib', lambda context, *args: result(first._lookup, context))
    assert first.get_lyrics('A Song', 'Artist', 120000)['status'] == 'found'
    second = configure(LyricsService(cache_path=path), monkeypatch)
    assert second.get_lyrics(title, artist, duration)['status'] == 'not_found'


def test_case_and_presentation_variations_reuse_verified_cache(monkeypatch):
    service = configure(LyricsService(), monkeypatch)
    calls = []
    def provider(context, *args):
        calls.append(1)
        return result(service._lookup, context)
    monkeypatch.setattr(service._lookup, 'lrclib', provider)
    assert service.get_lyrics('A Song (Official Video)', 'Artist', 120000)['status'] == 'found'
    assert service.get_lyrics('a song', 'ARTIST', 120000)['status'] == 'found'
    assert calls == [1]


def test_cache_hit_notifies_outside_service_lock(monkeypatch):
    service = configure(LyricsService(), monkeypatch)
    monkeypatch.setattr(service._lookup, 'lrclib', lambda context, *args: result(service._lookup, context))
    service.get_lyrics('A Song', 'Artist', 120000)
    acquired, observed, workers = threading.Event(), [], []
    def update(payload):
        def acquire():
            with service._cache_lock:
                acquired.set()
        worker = threading.Thread(target=acquire)
        workers.append(worker)
        worker.start()
        observed.append(acquired.wait(.5))
    service.get_lyrics('A Song', 'Artist', 120000, on_update=update)
    for worker in workers:
        worker.join(1)
    assert observed == [True], 'Bridge notification must not block another cache reader'


def test_lookup_without_cache_path_does_not_create_disk_cache(monkeypatch):
    service = configure(LyricsService(), monkeypatch)
    assert service._lookup.disk_cache is None
    monkeypatch.setattr(service._lookup, 'lrclib', lambda context, *args: result(service._lookup, context))
    assert service.get_lyrics('A Song', 'Artist', 120000)['status'] == 'found'


@pytest.mark.parametrize('later_path', ['https://cdn.example/audio?token=new',
                                      'http://cdn.example/audio?token=new', None])
def test_signed_stream_urls_share_persistent_lyrics_identity(tmp_path, monkeypatch, later_path):
    import os
    path = tmp_path / 'lyrics.db'
    original_stat = os.stat
    remote_stats, tag_calls, provider_calls = [], [], []
    def local_stat(value, *args, **kwargs):
        if isinstance(value, str) and value.casefold().startswith(('https://', 'http://')):
            remote_stats.append(value)
            raise AssertionError('A remote stream is not a local tagged file')
        return original_stat(value, *args, **kwargs)
    monkeypatch.setattr('services.lyrics_lookup.os.stat', local_stat)
    monkeypatch.setattr('utils.tag_parser.extract_embedded_lyrics', lambda value: tag_calls.append(value) or '')
    first = configure(LyricsService(cache_path=path), monkeypatch)
    def provider(context, *args):
        provider_calls.append(1)
        return result(first._lookup, context)
    monkeypatch.setattr(first._lookup, 'lrclib', provider)
    assert first.get_lyrics('A Song', 'Artist', 120000,
                           'https://cdn.example/audio?token=old')['syncedLyrics']
    second = configure(LyricsService(cache_path=path), monkeypatch)
    def forbidden(*args):
        provider_calls.append('unexpected network')
        raise AssertionError('URL token changes must reuse the verified disk hit')
    for name in PROVIDERS:
        monkeypatch.setattr(second._lookup, name, forbidden)
    assert second.get_lyrics('A Song', 'Artist', 120000, later_path)['syncedLyrics']
    assert provider_calls == [1] and not remote_stats and not tag_calls


def test_plain_exact_unknown_duration_finishes_before_slow_sources(monkeypatch):
    service = configure(LyricsService(), monkeypatch)
    release = threading.Event()
    entered_slow_source = threading.Event()
    result_ready = threading.Event()
    result_box = {}
    def slow_source(*args):
        entered_slow_source.set()
        release.wait(5)
        return None
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        monkeypatch.setattr(service, 'submit', executor.submit)
        monkeypatch.setattr(service._lookup, 'lrclib', lambda context, *args: result(service._lookup, context))
        monkeypatch.setattr(service._lookup, 'netease', slow_source)
        def lookup():
            result_box['value'] = service.get_lyrics('A Song', 'Artist', 0)
            result_ready.set()
        caller = threading.Thread(target=lookup, daemon=True)
        try:
            caller.start()
            assert entered_slow_source.wait(5), 'slow source did not start for the concurrency check'
            assert result_ready.wait(5), 'exact plain lyrics waited for a blocked timing source'
        finally:
            release.set()
            if caller.ident is not None:
                caller.join(5)
    actual = result_box['value']
    assert actual['status'] == 'found' and actual['syncedLyrics'] is None


def test_instrumental_finishes_without_waiting_for_lyrics_hosts(monkeypatch):
    service = configure(LyricsService(), monkeypatch)
    release = threading.Event()
    result_ready = threading.Event()
    result_box = {}
    def instrumental(context, *args):
        return service._lookup.accept(context, 'A Song', 'Artist', 120, None, None, 'Test', True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        monkeypatch.setattr(service, 'submit', executor.submit)
        monkeypatch.setattr(service._lookup, 'lrclib', instrumental)
        monkeypatch.setattr(service._lookup, 'netease', lambda *args: release.wait(5) and None)
        caller = threading.Thread(
            target=lambda: (result_box.setdefault('value', service.get_lyrics('A Song', 'Artist', 120000)), result_ready.set()),
            daemon=True,
        )
        try:
            caller.start()
            assert result_ready.wait(5), 'instrumental result waited for a blocked lyric provider'
        finally:
            release.set()
            if caller.ident is not None:
                caller.join(5)
    assert result_box['value']['instrumental']


@pytest.mark.parametrize('name', ['netease', 'qqmusic'])
def test_missing_lyric_on_first_verified_release_tries_another(monkeypatch, name):
    service = LyricsService()
    seen = []
    def request(url, *args):
        seen.append(url)
        if 'cloudsearch' in url:
            return {'code': 200, 'result': {'songs': [
                {'id': 1, 'name': 'A Song', 'ar': [{'name': 'Artist'}], 'dt': 120000},
                {'id': 2, 'name': 'A Song', 'ar': [{'name': 'Artist'}], 'dt': 120000}]}}
        if 'client_search' in url:
            return {'data': {'song': {'list': [
                {'songmid': 'one', 'songname': 'A Song', 'singer': [{'name': 'Artist'}], 'interval': 120},
                {'songmid': 'two', 'songname': 'A Song', 'singer': [{'name': 'Artist'}], 'interval': 120}]}}}
        if 'id=1&' in url or 'songmid=one&' in url:
            return {'lrc': {'lyric': ''}, 'lyric': ''}
        return {'lrc': {'lyric': '[00:01.00] Hello'}, 'lyric': '[00:01.00] Hello'}
    monkeypatch.setattr(service._lookup, '_json', request)
    actual = getattr(service._lookup, name)(form(), time.monotonic() + 8, lambda result: None)
    assert actual['syncedLyrics'] == '[00:01.00] Hello'
    assert len(seen) == 3


@pytest.mark.parametrize('name', ['netease', 'qqmusic'])
def test_duration_compatible_release_is_fetched_first(monkeypatch, name):
    service = LyricsService()
    seen = []
    def request(url, *args):
        seen.append(url)
        if 'cloudsearch' in url:
            return {'result': {'songs': [
                {'id': 1, 'name': 'A Song', 'ar': [{'name': 'Artist'}], 'dt': 200000},
                {'id': 2, 'name': 'A Song', 'ar': [{'name': 'Artist'}], 'dt': 120000}]}}
        if 'client_search' in url:
            return {'data': {'song': {'list': [
                {'songmid': 'one', 'songname': 'A Song', 'singer': [{'name': 'Artist'}], 'interval': 200},
                {'songmid': 'two', 'songname': 'A Song', 'singer': [{'name': 'Artist'}], 'interval': 120}]}}}
        return {'lrc': {'lyric': '[00:01.00] Hello'}, 'lyric': '[00:01.00] Hello'}
    monkeypatch.setattr(service._lookup, '_json', request)
    actual = getattr(service._lookup, name)(form(), time.monotonic() + 8, lambda result: None)
    assert actual['syncedLyrics'] and len(seen) == 2
    assert ('id=2&' in seen[1]) or ('songmid=two&' in seen[1])


def test_lrclib_uses_compatible_release_at_tail_of_result_page(monkeypatch):
    import urllib.error
    service = LyricsService()
    def request(url, *args):
        if '/api/get?' in url:
            raise urllib.error.HTTPError(url, 404, 'not found', {}, None)
        return [{'trackName': 'A Song', 'artistName': 'Other', 'duration': 120,
                 'syncedLyrics': '[00:01.00] Wrong'}] * 19 + [
                 {'trackName': 'A Song', 'artistName': 'Artist', 'duration': 120,
                  'syncedLyrics': '[00:01.00] Right', 'plainLyrics': 'Right'}]
    monkeypatch.setattr(service._lookup, '_json', request)
    assert service._lookup.lrclib(form(), time.monotonic() + 8, lambda result: None)['plainLyrics'] == 'Right'


def test_untimed_provider_text_never_becomes_karaoke():
    service = LyricsService()
    actual = service._lookup.accept(form(), 'A Song', 'Artist', 120, 'Hello without timestamps', None, 'Test')
    assert actual['syncedLyrics'] is None and actual['plainLyrics'] == 'Hello without timestamps'


def test_disk_cache_missing_expired_corrupt_and_unavailable_are_misses(tmp_path, monkeypatch):
    path = tmp_path / 'cache' / 'lyrics.db'
    cache = LyricsDiskCache(path)
    assert cache.get(('missing',)) is None and not path.exists()
    cache.put(('offline',), {'status': 'unavailable'}, 30)
    assert not path.exists()
    cache.put(('song',), cached_record(), 60)
    assert cache.get(('song',))['status'] == 'found'
    monkeypatch.setattr('services.lyrics_cache.time.time', lambda: 10 ** 12)
    assert cache.get(('song',)) is None
    path.write_bytes(b'not a sqlite database')
    assert cache.get(('song',)) is None
    cache.put(('song',), cached_record(), 60)  # A broken optional cache never breaks playback.


def test_disk_cache_is_bounded_and_evicts_oldest(tmp_path):
    path = tmp_path / 'lyrics.db'
    cache = LyricsDiskCache(path, max_entries=2, max_bytes=1500)
    for number in range(3):
        cache.put((number,), cached_record(), 60)
    assert cache.get((0,)) is None and cache.get((2,))
    with closing(sqlite3.connect(path)) as conn:
        count, size = conn.execute('SELECT COUNT(*), SUM(length(payload)) FROM lyrics_cache').fetchone()
    assert count <= 2 and size <= 1500


def test_disk_cache_byte_budget_evicts_even_below_entry_count(tmp_path):
    path = tmp_path / 'lyrics.db'
    cache = LyricsDiskCache(path, max_entries=10, max_bytes=650)
    for number in range(3):
        cache.put((number,), cached_record(), 60)
    assert cache.get((0,)) is None and cache.get((2,))
    with closing(sqlite3.connect(path)) as conn:
        count, size = conn.execute('SELECT COUNT(*), SUM(length(payload)) FROM lyrics_cache').fetchone()
    assert count < 3 and size <= 650


def test_cancelled_lookup_is_not_negative_cached(monkeypatch):
    service = configure(LyricsService(), monkeypatch)
    assert service.get_lyrics('A Song', 'Artist', 120000, is_current=lambda: False)['status'] == 'unavailable'
    assert not service._cache
    monkeypatch.setattr(service._lookup, 'lrclib', lambda context, *args: result(service._lookup, context))
    assert service.get_lyrics('A Song', 'Artist', 120000)['status'] == 'found'


def test_executor_refusal_is_unavailable_not_negative_cached(monkeypatch):
    service = configure(LyricsService(), monkeypatch)
    monkeypatch.setattr(service, 'submit', lambda *args: None)
    assert service.get_lyrics('A Song', 'Artist', 120000)['status'] == 'unavailable'
    assert not service._cache


def test_disk_cache_rejects_malformed_payload_even_with_valid_identity(tmp_path):
    path = tmp_path / 'lyrics.db'
    cache = LyricsDiskCache(path)
    cache.put(('song',), cached_record(), 60)
    invalid = dict(cached_record(), match_type='base')
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute('UPDATE lyrics_cache SET payload = ?', (json.dumps(invalid),))
    assert cache.get(('song',)) is None


@pytest.mark.parametrize('changes', [{'confidence': float('nan')}, {'confidence': .2},
                                    {'syncedLyrics': 'No timestamps'}, {'source': None}])
def test_disk_cache_rejects_unverified_or_invalid_timing(tmp_path, changes):
    path = tmp_path / 'lyrics.db'
    cache = LyricsDiskCache(path)
    cache.put(('song',), dict(cached_record(), **changes), 60)
    assert not path.exists()


def test_disk_promotion_does_not_extend_expiration(tmp_path, monkeypatch):
    path = tmp_path / 'lyrics.db'
    first = configure(LyricsService(cache_path=path), monkeypatch)
    monkeypatch.setattr(first._lookup, 'lrclib', lambda context, *args: result(first._lookup, context))
    first.get_lyrics('A Song', 'Artist', 120000)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute('UPDATE lyrics_cache SET expires = ?', (time.time() + .5,))
    second = configure(LyricsService(cache_path=path), monkeypatch)
    assert second.get_lyrics('A Song', 'Artist', 120000)['status'] == 'found'
    ttl = next(iter(second._cache.values()))[0] - time.monotonic()
    assert 0 < ttl < .6


def test_embedded_lyrics_cache_changes_when_file_changes(tmp_path, monkeypatch):
    path, song = tmp_path / 'lyrics.db', tmp_path / 'song.mp3'
    song.write_bytes(b'first')
    monkeypatch.setattr('utils.tag_parser.extract_embedded_lyrics', lambda path: 'First lyrics')
    first = configure(LyricsService(cache_path=path), monkeypatch)
    assert first.get_lyrics('A Song', 'Artist', 120000, str(song))['plainLyrics'] == 'First lyrics'
    stamp = song.stat().st_mtime_ns
    import os
    os.utime(song, ns=(stamp + 1_000_000_000, stamp + 1_000_000_000))
    monkeypatch.setattr('utils.tag_parser.extract_embedded_lyrics', lambda path: 'Updated lyrics')
    second = configure(LyricsService(cache_path=path), monkeypatch)
    assert second.get_lyrics('A Song', 'Artist', 120000, str(song))['plainLyrics'] == 'Updated lyrics'
