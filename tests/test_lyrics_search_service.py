"""
Unit tests for LyricsSearchService.
"""
import pytest
from services.lyrics_search_service import LyricsSearchService, format_duration


def test_format_duration():
    assert format_duration(0) == ""
    assert format_duration(65) == "1:05"
    assert format_duration(180) == "3:00"
    assert format_duration(204.4) == "3:24"


def test_score_calculation():
    svc = LyricsSearchService()
    cand1 = {
        "trackName": "Smells Like Teen Spirit",
        "artistName": "Nirvana",
        "durationSeconds": 301,
        "hasTiming": True,
    }
    score1 = svc._calculate_score(
        cand1,
        query="Nirvana Smells Like Teen Spirit",
        artist="Nirvana",
        title="Smells Like Teen Spirit",
        duration_sec=301,
    )
    assert score1 >= 0.85

    cand2 = {
        "trackName": "Completely Unrelated Song",
        "artistName": "Random Artist",
        "durationSeconds": 120,
        "hasTiming": False,
    }
    score2 = svc._calculate_score(
        cand2,
        query="Nirvana Smells Like Teen Spirit",
        artist="Nirvana",
        title="Smells Like Teen Spirit",
        duration_sec=301,
    )
    assert score2 < score1


def test_resolve_candidate_lrclib():
    svc = LyricsSearchService()
    payload = {
        "source": "LRCLIB",
        "syncedLyrics": "[00:10.00]Hello world\n[00:15.00]Second line",
        "plainLyrics": "Hello world\nSecond line",
    }
    res = svc.resolve_candidate_lyrics(payload)
    assert res is not None
    assert res["source"] == "LRCLIB"
    assert res["syncedLyrics"] == payload["syncedLyrics"]
    assert res["plainLyrics"] == payload["plainLyrics"]
    assert res["syncType"] == "line"


def test_player_query_expands_censored_title_and_uses_primary_artist(monkeypatch):
    service = LyricsSearchService()
    calls = []

    def provider(query, artist, title, duration_sec):
        calls.append((query, title, duration_sec))
        return []

    for name in ('lrclib', 'kugou', 'netease', 'qq', 'genius'):
        monkeypatch.setattr(service, f'_search_{name}', provider)

    service.search_candidates('XXXTENTACION & Trippie Redd - F**k Love',
                              'XXXTENTACION & Trippie Redd', 'F**k Love', duration_sec=146)
    assert calls == [('XXXTENTACION fuck Love', 'fuck Love', 146)] * 5
