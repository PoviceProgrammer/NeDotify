"""Regression tests for the Netease lyrics source, on the REAL cascade path.

Two bugs are covered:

1. The fetcher queried ``/api/search/pc``, which now answers ``code=-462`` with
   zero songs for *every* query, so Netease was silently dead and no Russian
   track ever found lyrics. It must use ``/api/cloudsearch/pc``.
2. Netease's search is fuzzy: asking for "бойсбенд" returned a completely
   different song. Accepting ``songs[0]`` would have displayed the wrong
   lyrics, so a candidate must pass the shared strict accept first.

The tests drive ``LyricsLookup.netease`` itself (BUG-L2-006: the legacy
``LyricsService._fetch_netease`` wrapper is gone) with a mocked ``_json`` -- no
network.
"""
import os
import sys
import time
import urllib.error
from urllib.parse import parse_qs, unquote, urlparse

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.lyrics_service import LyricsService  # noqa: E402
from services.music_matching import similarity, title_metadata  # noqa: E402


@pytest.fixture
def svc():
    return LyricsService()


def form(title='Бойсбенд', artist='Фараон', duration=0):
    return {'metadata': title_metadata(title, artist), 'query_title': title,
            'query_artist': artist, 'duration': duration, 'album': '', 'fallback': False}


def run_netease(svc, monkeypatch, payload, form_obj=None):
    """Route LyricsLookup.netease through a mocked _json and count requests."""
    calls = []
    lyric_calls = []

    def fake_json(url, *args, **kwargs):
        calls.append(url)
        if 'song/lyric' in url:
            lyric_calls.append(url)
        return payload(url)

    monkeypatch.setattr(svc._lookup, '_json', fake_json)
    result = svc._lookup.netease(form_obj or form(), time.monotonic() + 8, lambda res: None)
    return result, calls, lyric_calls


# --- endpoint selection -------------------------------------------------

def fake_response(payload_bytes):
    return type('Resp', (), {
        'read': lambda self, *a: payload_bytes,
        '__enter__': lambda self: self, '__exit__': lambda self, *a: False,
    })()


def open_netease(svc, monkeypatch, payload_bytes):
    """Drive LyricsLookup.netease through a mocked _open_url; return seen URLs."""
    seen = {}

    def fake_open(req, timeout=None, context=None):
        seen.setdefault("urls", []).append(req.full_url)
        seen["headers"] = {k.lower(): v for k, v in (req.header_items() if hasattr(req, "header_items") else [])}
        return fake_response(payload_bytes)

    monkeypatch.setattr(svc, "_open_url", fake_open)
    return seen


def test_netease_uses_working_cloudsearch_endpoint(svc, monkeypatch):
    """Must hit the endpoint that still resolves.

    /api/search/pc answers code=-462 with zero songs for every query, and
    /api/search returns an empty body, so Netease was silently dead.
    """
    seen = open_netease(svc, monkeypatch, b'{"code":200,"result":{"songs":[]}}')
    result = svc._lookup.netease(form(), time.monotonic() + 8, lambda res: None)

    assert any("cloudsearch/pc" in url for url in seen["urls"]), seen["urls"]
    assert all("/api/search" not in url for url in seen["urls"]), seen["urls"]
    # A Referer is required for the music.163.com endpoints to answer at all.
    assert seen["headers"].get("referer"), f"no Referer sent: {seen['headers']}"
    assert result is None


def test_netease_fetches_several_candidates(svc, monkeypatch):
    """A single fuzzy hit is not enough to trust, so limit must be > 1."""
    seen = open_netease(svc, monkeypatch, b'{"code":200,"result":{"songs":[]}}')
    assert svc._lookup.netease(form(), time.monotonic() + 8, lambda res: None) is None
    search = next((url for url in seen["urls"] if 'cloudsearch' in url), '')
    limit = parse_qs(urlparse(search).query).get('limit', [None])[0]
    assert limit and int(limit) > 1


# --- title matching -----------------------------------------------------

@pytest.mark.parametrize(
    "want,got,minimum",
    [
        ("бойсбенд", "Бойсбенд", 0.6),
        ("Yesterday", "Yesterday", 0.6),
        ("Ванава", "ВАНАВА", 0.6),
        ("Мой кайф (Remix)", "Мой кайф", 0.6),
        ("бойсбенд", "Прощай навеки последняя любовь", 1.1),  # must be rejected
        ("Yesterday", "Comfortably Numb", 1.1),               # must be rejected
        ("", "anything", 1.1),
        ("something", "", 1.1),
    ],
)
def test_title_match_score(want, got, minimum):
    """The title gate is the shared strict similarity over base titles."""
    score = similarity(title_metadata(want)['base_title'], title_metadata(got)['base_title'])
    if minimum > 1.0:
        assert score < 0.85, f"{got!r} should not be accepted as {want!r} (score={score})"
    else:
        assert score >= 0.85, f"{got!r} should be accepted as {want!r} (score={score})"


def test_wrong_song_is_rejected_even_when_lyrics_exist(svc, monkeypatch):
    """A mismatched hit must return None rather than someone else's lyrics."""
    wrong = {
        "code": 200,
        "result": {"songs": [{"id": 1, "name": "Прощай навеки последняя любовь"}]},
    }

    def payload(url):
        if 'song/lyric' in url:
            raise AssertionError("lyric fetch must not run for a mismatched song")
        return wrong

    result, calls, lyric_calls = run_netease(svc, monkeypatch, payload)
    assert result is None
    assert not lyric_calls, f"lyric endpoint was hit for a rejected song: {lyric_calls}"
    assert calls, "the search itself must have run"


def test_matching_song_returns_lyrics(svc, monkeypatch):
    search = {"code": 200, "result": {"songs": [
        {"id": 42, "name": "Прощай навеки"},
        {"id": 99, "name": "Бойсбенд", "ar": [{"name": "PHARAOH"}], "dt": 120000},
    ]}}
    lyric = {"lrc": {"lyric": "[00:12.00] тест"}, "tlyric": {"lyric": ""}}
    asked = []

    def payload(url):
        if 'cloudsearch' in url:
            return search
        asked.append(url)
        return lyric

    result, calls, lyric_calls = run_netease(svc, monkeypatch, payload)

    assert asked, "lyric endpoint was never called"
    assert "id=99" in asked[0], f"picked the wrong candidate: {asked[0]}"
    assert result and result["weight"] == 2  # unknown requested duration cannot validate timing
    assert "тест" in result["plainLyrics"]


def test_cascade_budget_covers_netease_latency(monkeypatch):
    service = LyricsService()
    budgets = []
    def provider(form_obj, deadline, offer):
        budgets.append(deadline - time.monotonic())
        return None
    for name in ('lrclib', 'netease', 'qqmusic', 'genius', 'megalobiz'):
        monkeypatch.setattr(service._lookup, name, provider)
    service.get_lyrics('Yesterday', 'The Beatles')
    assert budgets and max(budgets) >= 5.0


# --- variant / remix title handling -------------------------------------
#
# Providers index the BASE recording. If a title like "Track (Hardstyle
# Bootleg)" is treated as a different song nothing matches, and the app claims
# the lyrics are missing for a song whose words are indexed fine. On the real
# path the version is detected by services/music_matching.title_metadata: the
# qualifier becomes metadata['version'] (matched against the provider's own
# edition) and is stripped from base_title so the base recording can be found.

@pytest.mark.parametrize(
    "raw,version",
    [
        ("Some Track (Hardstyle Bootleg)", "remix"),
        ("Sandstorm (Radio Edit)", "remix"),
        ("Track [Extended Mix]", "remix"),
        ("Track (Remix)", "remix"),
        ("Track (Slowed + Reverb)", "slowed"),
        ("Song (Sped Up)", "sped"),
        ("Song (Club Mix)", "remix"),
        ("Song (Nightcore)", "sped"),
        ("Song (Live)", "live"),
        ("Song (Acoustic)", "acoustic"),
        ("Song (Instrumental)", "instrumental"),
        ("Замигает свет (SWEEQTY hardstyle remix)", "remix"),
        ("Song - Extended Mix", "remix"),
        ("Song – Radio Edit", "remix"),
    ],
)
def test_version_qualifiers_are_recognized_and_stripped(raw, version):
    meta = title_metadata(raw, 'Artist')
    assert meta['version'] == version, meta
    assert version not in meta['base_title'].lower()
    assert raw.split('(')[0].split('[')[0].split(' - ')[0].split(' – ')[0].strip() in meta['base_title']


@pytest.mark.parametrize(
    "raw",
    [
        # genre words alone are not a version marker, real titles survive
        "Love (Hardstyle)",
        "Song (House)",
        "Song (Radio Ga Ga)",
        "(I Love You)",
        "The Remix Album",
    ],
)
def test_real_titles_survive_untouched(raw):
    meta = title_metadata(raw)
    assert meta['version'] == ''
    assert meta['base_title'] == raw


def test_embedded_artist_is_tried_as_a_fallback_query(svc, monkeypatch):
    seen = []
    def lookup(form_obj, deadline, offer):
        seen.append((form_obj['query_artist'], form_obj['query_title']))
        if form_obj['query_artist'] == 'KENTUKKI' and form_obj['query_title'] == 'Замигает свет (SWEEQTY hardstyle remix)':
            return svc._lookup.accept(form_obj, 'Замигает свет', 'KENTUKKI', 120, '[00:01.00] Фонари', 'Фонари', 'Test')
        return None
    monkeypatch.setattr(svc._lookup, 'lrclib', lookup)
    for name in ('netease', 'qqmusic', 'genius', 'megalobiz'):
        monkeypatch.setattr(svc._lookup, name, lambda *a: None)
    result = svc.get_lyrics('KENTUKKI - Замигает свет (SWEEQTY hardstyle remix)', 'SWEEQTY', 120000)
    assert ('KENTUKKI', 'Замигает свет (SWEEQTY hardstyle remix)') in seen
    assert result['weight'] == 2 and result['match_type'] == 'base'
    assert result['syncedLyrics'] is None and result['plainLyrics'] == 'Фонари'
