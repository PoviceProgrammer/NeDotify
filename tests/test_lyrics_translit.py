"""BUG-L2-002: Cyrillic<->Latin artist forms in the lyrics cascade.

Providers index Russian artists under both scripts; the cascade must try the
alternate spelling as an extra query form while every acceptance check stays
strict. All tests run on mocked _json responses -- no network.
"""
import os
import sys
import urllib.error
from urllib.parse import unquote

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.lyrics_translit import alt_script_artist, to_cyrillic, to_latin  # noqa: E402
from services.lyrics_service import LyricsService  # noqa: E402


PROVIDERS = ('netease', 'qqmusic', 'genius', 'megalobiz')


@pytest.fixture
def service(monkeypatch):
    svc = LyricsService()
    for name in PROVIDERS:
        monkeypatch.setattr(svc._lookup, name, lambda *args: None)
    return svc


def lrclib_search(monkeypatch, svc, respond):
    """Route the real LyricsLookup.lrclib through a mocked _json: /api/get
    answers 404, /api/search hands its decoded q to respond()."""
    import urllib.parse

    def request(url, *args, **kwargs):
        if '/api/get?' in url:
            raise urllib.error.HTTPError(url, 404, 'not found', {}, None)
        query_string = url.split('?', 1)[1]
        query = urllib.parse.parse_qs(query_string).get('q', [''])[0]
        return respond(unquote(query))

    monkeypatch.setattr(svc._lookup, '_json', request)


# --- unit: table and eligibility -----------------------------------------

def test_forward_transcription_is_deterministic():
    assert to_latin('Скриптонит') == 'skriptonit'
    assert to_latin('Мот') == 'mot'
    assert to_latin('Ёлка') == 'elka'
    assert to_latin('Miyagi') == 'Miyagi'  # latin passes through unchanged


def test_reverse_transcription_uses_digraphs():
    assert to_cyrillic('skriptonit') == 'скриптонит'
    assert to_cyrillic('dzhigan') == 'джиган'
    assert to_cyrillic('skripka') == 'скрипка'


def test_alt_script_artist_both_directions():
    assert alt_script_artist('Скриптонит') == 'skriptonit'
    assert alt_script_artist('Skriptonit') == 'скриптонит'
    assert alt_script_artist('Мот') == 'mot'
    assert alt_script_artist('Mot') == 'мот'


def test_alt_script_artist_rejects_pseudo_transcriptions():
    # Оксимирон is a different word, not a transcription of Oxxxymiron.
    assert alt_script_artist('Oxxxymiron') is None
    assert alt_script_artist('') is None
    assert alt_script_artist('123') is None


# --- cascade: the alternate form actually finds and accepts ---------------

def test_cyrillic_metadata_finds_latin_indexed_record(service, monkeypatch):
    """Metadata artist 'Скриптонит', LRCLIB record 'Skriptonit': the latin
    query form must run and the record must pass the strict accept."""
    record = {'trackName': 'Апрель', 'artistName': 'Skriptonit', 'duration': 120,
              'syncedLyrics': '[00:01.00] Апрель', 'plainLyrics': 'Апрель'}
    queries = []

    def respond(query):
        queries.append(query)
        if 'скриптонит' in query.lower():
            return []  # original-script search misses
        return [record]  # alternate-script search hits

    lrclib_search(monkeypatch, service, respond)
    result = service.get_lyrics('Апрель', 'Скриптонит', 120000)
    assert any('skriptonit' in q for q in queries), queries
    assert result['status'] == 'found'
    assert result['matched_artist'] == 'Skriptonit'
    assert result['syncedLyrics'] == '[00:01.00] Апрель'


def test_latin_metadata_finds_cyrillic_indexed_record(service, monkeypatch):
    record = {'trackName': 'Апрель', 'artistName': 'Скриптонит', 'duration': 120,
              'syncedLyrics': None, 'plainLyrics': 'Апрель'}
    queries = []

    def respond(query):
        queries.append(query)
        if 'скриптонит' in query.lower():
            return [record]
        return []

    lrclib_search(monkeypatch, service, respond)
    result = service.get_lyrics('Апрель', 'Skriptonit', 120000)
    assert any('скриптонит' in q.lower() for q in queries), queries
    assert result['status'] == 'found'
    assert result['matched_artist'] == 'Скриптонит'


def test_cross_script_accept_still_requires_same_title(service, monkeypatch):
    """Transliteration widens the artist comparison only: a latin-artist
    record with a different cyrillic title stays rejected."""
    record = {'trackName': 'Май', 'artistName': 'Skriptonit', 'duration': 120,
              'syncedLyrics': None, 'plainLyrics': 'Май'}

    def respond(query):
        return [record]

    lrclib_search(monkeypatch, service, respond)
    assert service.get_lyrics('Апрель', 'Скриптонит', 120000)['status'] == 'not_found'


def test_homophone_latin_names_stay_rejected(service):
    """'ШОК' transcribes to 'shok', not 'shock': unrelated latin names must
    not become acceptable through the extra pass."""
    engine = service._lookup
    from services.music_matching import title_metadata
    form = {'metadata': title_metadata('Мой кайф', 'ШОК'), 'duration': 120, 'album': '',
            'fallback': False, 'query_artist': 'ШОК', 'query_title': 'Мой кайф'}
    assert engine.accept(form, 'Мой кайф', 'Shock', 120, None, 'text', 'Test') is None
    assert engine.accept(form, 'Мой кайф', 'SHOK', 120, None, 'text', 'Test') is not None
