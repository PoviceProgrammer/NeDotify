"""
Unit tests for Worker M2 requirements:
- LastFMService (queries, key rotation, TTL caching, offline fallback)
- UserTasteProfile (build_from_db, seed artists/tracks, time of day vibe)
- TrackResolver (local, SoundCloud, YouTube resolution cascade & UI track dictionary formatting)
"""

import time
import sqlite3
import pytest
from unittest.mock import MagicMock, patch
from services.lastfm_service import LastFMService, API_KEYS, RECOMMENDATION_TTL, CHART_TTL
from services.taste_profile import UserTasteProfile
from services.track_resolver import TrackResolver, resolve_track
from core.database import DatabaseManager


# ---------------------------------------------------------------------------
# LastFMService Tests
# ---------------------------------------------------------------------------

def test_lastfm_key_rotation():
    service = LastFMService()
    keys_seen = []
    for _ in range(len(API_KEYS) * 2):
        keys_seen.append(service._get_next_api_key())
    
    assert keys_seen[0] == API_KEYS[0]
    assert keys_seen[1] == API_KEYS[1]
    assert keys_seen[2] == API_KEYS[2]
    assert keys_seen[3] == API_KEYS[3]
    assert keys_seen[len(API_KEYS)] == API_KEYS[0]  # full cycle wraps around


def test_lastfm_api_queries_mocked():
    service = LastFMService()
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    
    # 1. artist.getSimilar
    mock_response.json.return_value = {
        "similarartists": {
            "artist": [
                {"name": "Dua Lipa", "match": "0.95", "url": "http://last.fm/dua", "image": [{"#text": "http://img.jpg"}]},
                {"name": "Rita Ora", "match": "0.85", "url": "http://last.fm/rita", "image": [{"#text": "http://img2.jpg"}]}
            ]
        }
    }
    with patch.object(service._session, 'get', return_value=mock_response):
        similar = service.artist.getSimilar("Ava Max", limit=2)
        assert len(similar) == 2
        assert similar[0]['name'] == "Dua Lipa"
        assert similar[0]['match'] == 0.95

    # 2. artist.getTopTracks
    mock_response.json.return_value = {
        "toptracks": {
            "track": [
                {"name": "Levitating", "artist": {"name": "Dua Lipa"}, "playcount": "5000", "listeners": "1000"}
            ]
        }
    }
    with patch.object(service._session, 'get', return_value=mock_response):
        top_tracks = service.artist.getTopTracks("Dua Lipa", limit=1)
        assert len(top_tracks) == 1
        assert top_tracks[0]['name'] == "Levitating"

    # 3. artist.getTopTags
    mock_response.json.return_value = {
        "toptags": {
            "tag": [
                {"name": "pop", "count": "100"},
                {"name": "dance", "count": "80"}
            ]
        }
    }
    with patch.object(service._session, 'get', return_value=mock_response):
        tags = service.artist.getTopTags("Dua Lipa")
        assert len(tags) == 2
        assert tags[0]['name'] == "pop"

    # 4. track.getSimilar
    mock_response.json.return_value = {
        "similartracks": {
            "track": [
                {"name": "Don't Start Now", "artist": {"name": "Dua Lipa"}, "match": "0.9", "duration": "183"}
            ]
        }
    }
    with patch.object(service._session, 'get', return_value=mock_response):
        sim_trks = service.track.getSimilar("Dua Lipa", "Levitating", limit=1)
        assert len(sim_trks) == 1
        assert sim_trks[0]['name'] == "Don't Start Now"

    # 5. chart.getTopTracks
    mock_response.json.return_value = {
        "tracks": {
            "track": [
                {"name": "Blinding Lights", "artist": {"name": "The Weeknd"}, "playcount": "10000"}
            ]
        }
    }
    with patch.object(service._session, 'get', return_value=mock_response):
        chart_trks = service.chart.getTopTracks(limit=1)
        assert len(chart_trks) == 1
        assert chart_trks[0]['name'] == "Blinding Lights"

    # 6. chart.getTopArtists
    mock_response.json.return_value = {
        "artists": {
            "artist": [
                {"name": "The Weeknd", "playcount": "20000"}
            ]
        }
    }
    with patch.object(service._session, 'get', return_value=mock_response):
        chart_arts = service.chart.getTopArtists(limit=1)
        assert len(chart_arts) == 1
        assert chart_arts[0]['name'] == "The Weeknd"


def test_lastfm_caching_and_ttl():
    service = LastFMService()
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "similarartists": {"artist": [{"name": "Cached Artist", "match": "1.0"}]}
    }
    
    with patch.object(service._session, 'get', return_value=mock_response) as mock_get:
        unique_artist = f"Test Artist {time.time()}"
        res1 = service.artist_get_similar(unique_artist, limit=1)
        res2 = service.artist_get_similar(unique_artist, limit=1)
        assert res1 == res2
        assert mock_get.call_count == 1  # Second call served from cache


def test_lastfm_offline_graceful_fallback():
    service = LastFMService()
    with patch.object(service._session, 'get', side_effect=Exception("Network Offline")):
        res = service.artist_get_similar("Unknown Artist", limit=5)
        assert res == []


# ---------------------------------------------------------------------------
# UserTasteProfile Tests
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            artist TEXT,
            album TEXT,
            duration REAL,
            file_path TEXT,
            source TEXT,
            source_id TEXT,
            source_url TEXT,
            cover_path TEXT,
            cover_url TEXT,
            genre TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            play_count INTEGER DEFAULT 0,
            is_favorite INTEGER DEFAULT 0,
            is_downloaded INTEGER DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_id INTEGER,
            played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            duration_listened REAL DEFAULT 0,
            completed INTEGER DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE playlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE playlist_tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            playlist_id INTEGER NOT NULL,
            track_id INTEGER NOT NULL,
            position INTEGER DEFAULT 0,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Insert sample tracks
    cursor.execute("INSERT INTO tracks (title, artist, genre, is_favorite, play_count) VALUES ('Blinding Lights', 'The Weeknd', 'Pop', 1, 10)")
    cursor.execute("INSERT INTO tracks (title, artist, genre, is_favorite, play_count) VALUES ('Levitating', 'Dua Lipa', 'Pop', 1, 5)")
    cursor.execute("INSERT INTO tracks (title, artist, genre, is_favorite, play_count) VALUES ('Lose Yourself', 'Eminem', 'Hip-Hop', 0, 2)")
    
    # Insert history (morning: 09:00, evening: 20:00)
    cursor.execute("INSERT INTO history (track_id, played_at) VALUES (1, '2026-08-03 09:15:00')")
    cursor.execute("INSERT INTO history (track_id, played_at) VALUES (1, '2026-08-03 09:30:00')")
    cursor.execute("INSERT INTO history (track_id, played_at) VALUES (2, '2026-08-03 20:00:00')")
    conn.commit()
    return conn


def test_user_taste_profile_build_from_db(mock_db):
    profile = UserTasteProfile().build_from_db(mock_db)
    
    # Top seed artists
    seed_artists = profile.get_seed_artists(limit=2)
    assert "The Weeknd" in seed_artists
    
    # Top seed tracks
    seed_tracks = profile.get_seed_tracks(limit=2)
    assert len(seed_tracks) > 0
    
    # Vibe slot
    vibe = profile.get_time_of_day_vibe()
    assert vibe in ['morning', 'afternoon', 'evening', 'night']
    
    # Favorites
    assert len(profile.favorite_tracks) == 2
    
    # Genre distribution
    assert "Pop" in profile.genre_distribution
    
    # Serialization
    profile_dict = profile.to_dict()
    assert 'top_artists' in profile_dict
    assert 'seed_artists' in profile_dict


# ---------------------------------------------------------------------------
# TrackResolver Tests
# ---------------------------------------------------------------------------

def test_track_resolver_local_match(mock_db):
    resolver = TrackResolver(db=mock_db)
    resolved = resolver.resolve_track("Blinding Lights", "The Weeknd")
    
    assert resolved['title'] == "Blinding Lights"
    assert resolved['artist'] == "The Weeknd"
    assert resolved['source'] == "local"


def test_track_resolver_soundcloud_fallback(mock_db):
    mock_sc = MagicMock()
    def sc_search_impl(query, max_results=1, callback=None, error_callback=None):
        if callback:
            callback([{
                'title': 'SoundCloud Track',
                'artist': 'SC Artist',
                'cover_url': 'http://sc.jpg',
                'source': 'soundcloud',
                'source_id': '12345',
                'source_url': 'http://soundcloud.com/12345',
                'duration': 200
            }])
    mock_sc.search.side_effect = sc_search_impl
    
    resolver = TrackResolver(db=mock_db, soundcloud_service=mock_sc)
    resolved = resolver.resolve_track("Nonexistent Song", "SC Artist")
    
    assert resolved['title'] == "SoundCloud Track"
    assert resolved['source'] == "soundcloud"
    assert resolved['source_id'] == "12345"


def test_track_resolver_youtube_fallback(mock_db):
    mock_sc = MagicMock()
    mock_sc.search.side_effect = lambda q, max_results=1, callback=None, error_callback=None: callback([]) if callback else None

    mock_yt = MagicMock()
    def yt_search_impl(query, max_results=1, callback=None, error_callback=None):
        if callback:
            callback([{
                'title': 'YouTube Track',
                'artist': 'YT Artist',
                'cover_url': 'http://yt.jpg',
                'source': 'youtube',
                'source_id': 'yt987',
                'source_url': 'http://youtube.com/watch?v=yt987',
                'duration': 180
            }])
    mock_yt.search.side_effect = yt_search_impl

    resolver = TrackResolver(db=mock_db, soundcloud_service=mock_sc, youtube_service=mock_yt)
    resolved = resolver.resolve_track("Unknown Song", "YT Artist")
    
    assert resolved['title'] == "YouTube Track"
    assert resolved['source'] == "youtube"
    assert resolved['source_id'] == "yt987"
    assert resolved['duration'] == 180.0
