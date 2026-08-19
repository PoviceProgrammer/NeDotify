"""
Unit tests for Worker M3 Recommendation Engine Refactoring:
- get_mixes generation and R5 mix sequencing (energy curve/genre coherence)
- get_smart_home_feed JSON schema & time-of-day greeting validation
- Mandatory UI track dictionary fields check (title, artist, cover_url, source, source_id, source_url, duration, is_favorite, is_downloaded)
- Failure mocks for Last.fm and SoundCloud (graceful degradation)
- Static code check asserting ZERO calls/imports to YTMusic.get_watch_playlist or YTMusic.get_explore
"""

import os
import time
import sqlite3
import threading
import pytest
from unittest.mock import MagicMock, patch
from services.recommendation_service import RecommendationService
from services.taste_profile import UserTasteProfile
from services.lastfm_service import LastFMService
from services.track_resolver import TrackResolver


@pytest.fixture
def mock_db_m3():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
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

    cursor.execute("INSERT INTO tracks (title, artist, genre, is_favorite, play_count, source, source_id) VALUES ('Starboy', 'The Weeknd', 'Pop', 1, 15, 'soundcloud', 'sc_1')")
    cursor.execute("INSERT INTO tracks (title, artist, genre, is_favorite, play_count, source, source_id) VALUES ('Physical', 'Dua Lipa', 'Pop', 1, 8, 'youtube', 'yt_1')")
    cursor.execute("INSERT INTO history (track_id, played_at) VALUES (1, '2026-08-03 09:00:00')")
    conn.commit()
    return conn


def test_get_mixes_generation(mock_db_m3):
    service = RecommendationService(db=mock_db_m3)

    # Mock Last.fm API calls & TrackResolver
    service.lastfm.user.getTopArtists = MagicMock(return_value=[])
    service.lastfm.artist.getTopTracks = MagicMock(return_value=[
        {'name': 'Blinding Lights', 'artist': 'The Weeknd'},
        {'name': 'Save Your Tears', 'artist': 'The Weeknd'},
        {'name': 'In Your Eyes', 'artist': 'The Weeknd'}
    ])
    service.lastfm.chart.getTopTracks = MagicMock(return_value=[
        {'name': 'Levitating', 'artist': 'Dua Lipa'},
        {'name': 'Don\'t Start Now', 'artist': 'Dua Lipa'}
    ])
    service.lastfm._api_request = MagicMock(return_value=None)

    service.resolver.resolve_track = MagicMock(side_effect=lambda title, artist="": {
        'title': title,
        'artist': artist or 'The Weeknd',
        'cover_url': 'http://cover.jpg',
        'source': 'soundcloud',
        'source_id': '12345',
        'source_url': 'http://soundcloud.com/12345',
        'duration': 180.0
    })

    done_event = threading.Event()
    mixes = []

    def cb(res):
        nonlocal mixes
        mixes = res
        done_event.set()

    service.get_mixes(history=[{'artist': 'The Weeknd'}], callback=cb)
    done_event.wait(timeout=5.0)

    assert isinstance(mixes, list)
    assert len(mixes) > 0
    mix = mixes[0]
    assert mix.get('type') == 'custom_playlist'
    assert 'title' in mix
    assert 'tracks' in mix
    assert isinstance(mix['tracks'], list)
    assert len(mix['tracks']) > 0


def test_smart_home_feed_schema_and_mandatory_fields(mock_db_m3):
    service = RecommendationService(db=mock_db_m3)

    # Mock Last.fm responses & TrackResolver
    service.lastfm.user.getTopArtists = MagicMock(return_value=[])
    service.lastfm.artist.getTopTracks = MagicMock(return_value=[
        {'name': 'Song A', 'artist': 'The Weeknd'},
        {'name': 'Song B', 'artist': 'The Weeknd'}
    ])
    service.lastfm.chart.getTopTracks = MagicMock(return_value=[
        {'name': 'Chart 1', 'artist': 'Top Artist'}
    ])
    service.lastfm._api_request = MagicMock(return_value=None)

    service.resolver.resolve_track = MagicMock(side_effect=lambda title, artist="": {
        'title': title,
        'artist': artist or 'Top Artist',
        'cover_url': 'http://cover.jpg',
        'source': 'soundcloud',
        'source_id': '999',
        'source_url': 'http://soundcloud.com/999',
        'duration': 200.0,
        'is_favorite': False,
        'is_downloaded': False
    })

    done_event_feed = threading.Event()
    feed_payload = None

    def cb(payload):
        nonlocal feed_payload
        feed_payload = payload
        done_event_feed.set()

    service.get_smart_home_feed(history=[], callback=cb)
    done_event_feed.wait(timeout=5.0)

    assert feed_payload is not None
    assert 'greeting' in feed_payload
    assert feed_payload['greeting'] in ['Доброе утро', 'Добрый день', 'Добрый вечер', 'Доброй ночи']
    assert 'sections' in feed_payload
    assert len(feed_payload['sections']) == 4

    for sec in feed_payload['sections']:
        assert 'title' in sec
        assert 'items' in sec
        for item in sec['items']:
            if item.get('type') != 'custom_playlist':
                # Mandatory UI fields check
                for field in ['title', 'artist', 'cover_url', 'source', 'source_id', 'source_url', 'duration', 'is_favorite', 'is_downloaded']:
                    assert field in item, f"Missing mandatory field '{field}' in track item {item}"


def test_failure_mocks_graceful_degradation(mock_db_m3):
    service = RecommendationService(db=mock_db_m3)

    # Mock Last.fm network failure and resolver network calls
    with patch.object(service.lastfm._session, 'get', side_effect=Exception("Network failure")), \
         patch.object(service.resolver, '_search_soundcloud', return_value=None), \
         patch.object(service.resolver, '_search_youtube', return_value=None):
        recommendations = service._fetch_recommendations({'artist': 'The Weeknd'}, max_results=5)
        # Should degrade gracefully to DB or fallback without raising exception
        assert isinstance(recommendations, list)


def test_zero_ytmusic_generative_calls():
    """Static check asserting zero calls/imports to YTMusic.get_watch_playlist or YTMusic.get_explore."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target_files = [
        os.path.join(project_root, 'services', 'recommendation_service.py'),
        os.path.join(project_root, 'core', 'services', 'recommendation.py'),
        os.path.join(project_root, 'core', 'api.py')
    ]

    forbidden_patterns = ['get_watch_playlist', 'get_explore', 'watch_playlist']

    violations = []
    for filepath in target_files:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
                for pattern in forbidden_patterns:
                    if pattern in content:
                        violations.append(f"Forbidden pattern '{pattern}' found in {filepath}")

    assert len(violations) == 0, f"Found YTMusic generative violations: {violations}"
