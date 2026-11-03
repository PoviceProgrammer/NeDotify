"""Lyrics identity, incremental karaoke, cache expiry and request isolation."""
import threading
import time

import pytest

from services.lyrics_service import LyricsService
from services.music_matching import title_metadata


@pytest.fixture
def lyrics(monkeypatch):
    service = LyricsService()
    for name in ('lrclib', 'netease', 'qqmusic', 'genius', 'megalobiz'):
        monkeypatch.setattr(service._lookup, name, lambda *a: None)
    return service


def form(title='A Song', artist='Artist', duration=120):
    return {'metadata': title_metadata(title, artist), 'duration': duration, 'album': '', 'fallback': False,
            'query_artist': artist, 'query_title': title}


def candidate(engine, context=None, title='A Song', artist='Artist', duration=120, synced='[00:01.00] Hello', plain='Hello'):
    return engine.accept(context or form(), title, artist, duration, synced, plain, 'Test')


def test_same_title_by_another_artist_is_rejected(lyrics):
    assert candidate(lyrics._lookup, artist='Other Artist') is None
    assert candidate(lyrics._lookup, title='A Different Song') is None


@pytest.mark.parametrize('duration,expected', [(120, True), (122, True), (123, True), (127, False), (136, False), (0, False)])
def test_karaoke_needs_compatible_duration(lyrics, duration, expected):
    result = candidate(lyrics._lookup, duration=duration)
    # Current contract: timing within 6s, verified plain text within 15s.
    if duration == 136:
        assert result is None
        return
    assert bool(result['syncedLyrics']) is expected
    assert result['plainLyrics'] == 'Hello'


def test_unknown_duration_keeps_valid_plain_text(lyrics):
    assert candidate(lyrics._lookup, form(duration=0))['syncedLyrics'] is None


@pytest.mark.parametrize('marker', ['Remix', 'rmx', 'Bootleg', 'sped up', 'speed up', 'speedup', 'nightcore', 'slowed + reverb', 'ускоренная', 'замедленная', 'ремикс'])
def test_variant_original_is_explicitly_plain(lyrics, marker):
    result = candidate(lyrics._lookup, form(f'A Song ({marker})'))
    assert result['match_type'] == 'base'
    assert result['syncedLyrics'] is None


@pytest.mark.parametrize('marker', ['Instrumental', 'Live', 'Cover', 'Acoustic', 'инструментал', 'кавер'])
def test_other_versions_cannot_silently_use_original(lyrics, marker):
    assert candidate(lyrics._lookup, form(f'A Song ({marker})')) is None


def test_exact_variant_can_use_its_own_timing(lyrics):
    result = candidate(lyrics._lookup, form('A Song (sped up)'), title='A Song (sped up)')
    assert result['syncedLyrics'] and result['match_type'] == 'exact'


def test_artist_alias_is_allowed_but_mixed_homoglyph_is_not(lyrics):
    assert candidate(lyrics._lookup, form(artist='Фараон'), artist='PHARAOH')
    assert candidate(lyrics._lookup, form(artist='PHАRAOH'), artist='PHARAOH') is None


def test_plain_is_published_before_delayed_synced_upgrade(lyrics, monkeypatch):
    seen = []
    delivered = threading.Event()
    def first(context, deadline, offer):
        plain = candidate(lyrics._lookup, context, synced=None)
        offer(plain)
        delivered.set()
        return plain
    def timed(context, deadline, offer):
        assert delivered.wait(1)
        time.sleep(.03)
        return candidate(lyrics._lookup, context)
    monkeypatch.setattr(lyrics._lookup, 'lrclib', first)
    monkeypatch.setattr(lyrics._lookup, 'netease', timed)
    result = lyrics.get_lyrics('A Song', 'Artist', 120000, on_update=seen.append)
    assert seen[0]['plainLyrics'] and seen[0]['syncedLyrics'] is None
    assert result['syncedLyrics']
    assert [x['revision'] for x in seen] == sorted(set(x['revision'] for x in seen))
    assert seen[-1]['phase'] == 'final'


def test_unavailable_is_not_cached_and_success_uses_metadata_key(lyrics, monkeypatch):
    calls = []
    def unavailable(*args):
        calls.append(1)
        raise ConnectionError('offline')
    monkeypatch.setattr(lyrics._lookup, 'lrclib', unavailable)
    assert lyrics.get_lyrics('A Song', 'Artist', 120000)['status'] == 'unavailable'
    assert lyrics.get_lyrics('A Song', 'Artist', 120000)['status'] == 'unavailable'
    assert len(calls) == 2 and not lyrics._cache
    monkeypatch.setattr(lyrics._lookup, 'lrclib', lambda context, *a: candidate(lyrics._lookup, context))
    assert lyrics.get_lyrics('A Song', 'Artist', 120000)['weight'] == 1
    monkeypatch.setattr(lyrics._lookup, 'lrclib', lambda *a: (_ for _ in ()).throw(AssertionError('cache miss')))
    assert lyrics.get_lyrics('A Song', 'Artist', 120000)['weight'] == 1
    assert lyrics.get_lyrics('A Song', 'Artist', 100000)['status'] == 'unavailable'


def test_identical_pending_requests_share_work(lyrics, monkeypatch):
    started, release = threading.Event(), threading.Event()
    calls, results = [], []
    def provider(context, *a):
        calls.append(1)
        started.set()
        assert release.wait(1)
        return candidate(lyrics._lookup, context)
    monkeypatch.setattr(lyrics._lookup, 'lrclib', provider)
    threads = [threading.Thread(target=lambda: results.append(lyrics.get_lyrics('A Song', 'Artist', 120000))) for _ in range(2)]
    threads[0].start(); assert started.wait(1)
    threads[1].start(); time.sleep(.02); release.set()
    for thread in threads:
        thread.join(2)
    assert calls == [1] and len(results) == 2
    assert all(result['syncedLyrics'] for result in results)


def test_superseded_requests_do_not_publish(lyrics, monkeypatch):
    current = [True]
    observed = []
    def provider(context, *a):
        current[0] = False
        return candidate(lyrics._lookup, context)
    monkeypatch.setattr(lyrics._lookup, 'lrclib', provider)
    lyrics.get_lyrics('A Song', 'Artist', 120000, on_update=observed.append, is_current=lambda: current[0])
    assert not observed


def test_lyrics_ready_keeps_request_id_and_progress_revisions(api, core_ns, emitted):
    finished = threading.Event()
    def get_lyrics(*args, on_update, **kwargs):
        on_update({'status': 'found', 'plainLyrics': 'Hello', 'revision': 1, 'phase': 'partial'})
        on_update({'status': 'found', 'syncedLyrics': '[00:01] Hello', 'revision': 2, 'phase': 'final'})
        finished.set()
        return {}
    core_ns.lyrics = type('Service', (), {'get_lyrics': staticmethod(get_lyrics)})()
    response = api.get_lyrics('A Song', 'Artist', request_id='lyrics-id')
    assert response['request_id'] == 'lyrics-id' and finished.wait(1)
    assert [event for event, _ in emitted] == ['lyrics_ready', 'lyrics_ready']
    assert [data['revision'] for _, data in emitted] == [1, 2]
    assert all(data['request_id'] == 'lyrics-id' for _, data in emitted)


def test_changing_track_cancels_previous_lyrics_before_new_lookup(api, core_ns, emitted):
    started, release, finished = (threading.Event() for _ in range(3))
    observed = []
    def get_lyrics(*args, on_update, is_current, **kwargs):
        started.set()
        assert release.wait(2)
        observed.append(is_current())
        on_update({'status': 'found', 'plainLyrics': 'Old text'})
        finished.set()
        return {}
    core_ns.lyrics = type('Service', (), {'get_lyrics': staticmethod(get_lyrics)})()
    api.get_lyrics('A Song', 'Artist', request_id='old')
    assert started.wait(1)
    try:
        api.next_track()
    finally:
        release.set()
    assert finished.wait(1)
    assert observed == [False]
    assert not any(name == 'lyrics_ready' for name, _ in emitted)


def test_lrclib_search_ignores_first_synced_hit_from_wrong_artist(lyrics, monkeypatch):
    import urllib.error
    engine = lyrics._lookup
    def request(url, *args):
        if '/api/get?' in url:
            raise urllib.error.HTTPError(url, 404, 'not found', {}, None)
        return [{'trackName': 'A Song', 'artistName': 'Other', 'duration': 120, 'syncedLyrics': '[00:01] Wrong'},
                {'trackName': 'A Song', 'artistName': 'Artist', 'duration': 120, 'syncedLyrics': '[00:01] Right', 'plainLyrics': 'Right'}]
    monkeypatch.setattr(engine, '_json', request)
    observed = []
    result = type(engine).lrclib(engine, form(), time.monotonic() + 8, observed.append)
    assert result['plainLyrics'] == 'Right'
    assert all(item['matched_artist'] == 'Artist' for item in observed)


def test_upload_with_unknown_artist_uses_explicit_title_credit(lyrics, monkeypatch):
    def provider(context, *args):
        return candidate(lyrics._lookup, context, title='A Song', artist='Artist')
    monkeypatch.setattr(lyrics._lookup, 'lrclib', provider)
    assert lyrics.get_lyrics('Artist - A Song', '?', 120000)['matched_artist'] == 'Artist'


def test_reversed_upload_credit_with_feature_is_verified(lyrics, monkeypatch):
    def provider(context, *args):
        return candidate(lyrics._lookup, context, title='A Song', artist='Artist')
    monkeypatch.setattr(lyrics._lookup, 'lrclib', provider)
    result = lyrics.get_lyrics('A Song - Artist feat. Guest', 'Uploader', 120000)
    assert result['matched_artist'] == 'Artist' and result['plainLyrics'] == 'Hello'
