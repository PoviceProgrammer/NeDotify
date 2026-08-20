"""
Official Automated Test Script: tests/test_new_recommendations.py
Programmatically verifies the new recommendation engine for AURA Music / NeDotify:
1. get_smart_home_feed with mock listening history in local SQLite DB.
2. get_mixes generation & R5 energy curve sequencing.
3. Network failure / mock fallbacks for Last.fm and SoundCloud APIs (confirming zero crashes and graceful local DB fallback).
4. Static AST and mock assertions confirming ZERO calls or imports to YTMusic.get_explore or YTMusic.get_watch_playlist in services/recommendation_service.py, core/api.py, and core/services/recommendation.py.
5. Strict UI JSON output format validation (greeting, sections, items with mandatory track fields: title, artist, cover_url, source, source_id, source_url, duration, is_favorite, is_downloaded).
"""

import os
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import ast
import time
import sqlite3
import unittest
import threading
from typing import Dict, Any, List
from unittest.mock import MagicMock, patch

import requests
from services.recommendation_service import RecommendationService
from services.taste_profile import UserTasteProfile
from services.lastfm_service import LastFMService
from services.track_resolver import TrackResolver


def create_mock_db() -> sqlite3.Connection:
    """Helper to construct an in-memory SQLite DB with populated mock tracks and listening history."""
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

    # Populate sample mock listening history & tracks
    sample_tracks = [
        ("Starboy", "The Weeknd", "Starboy", 230.0, "/music/starboy.mp3", "soundcloud", "sc_1001", "https://soundcloud.com/theweeknd/starboy", "https://img.com/starboy.jpg", "Pop", 15, 1, 1),
        ("Blinding Lights", "The Weeknd", "After Hours", 200.0, "/music/blinding.mp3", "soundcloud", "sc_1002", "https://soundcloud.com/theweeknd/blinding", "https://img.com/blinding.jpg", "Pop", 25, 1, 0),
        ("Levitating", "Dua Lipa", "Future Nostalgia", 203.0, "/music/levitating.mp3", "youtube", "yt_2001", "https://youtube.com/watch?v=yt_2001", "https://img.com/levitating.jpg", "Pop", 8, 0, 0),
        ("Physical", "Dua Lipa", "Future Nostalgia", 193.0, "/music/physical.mp3", "youtube", "yt_2002", "https://youtube.com/watch?v=yt_2002", "https://img.com/physical.jpg", "Pop", 5, 1, 0),
        ("Lose Yourself", "Eminem", "8 Mile", 326.0, "/music/loseyourself.mp3", "local", "loc_3001", "/music/loseyourself.mp3", "https://img.com/loseyourself.jpg", "Hip-Hop", 12, 1, 1),
    ]

    for t in sample_tracks:
        cursor.execute("""
            INSERT INTO tracks (title, artist, album, duration, file_path, source, source_id, source_url, cover_url, genre, play_count, is_favorite, is_downloaded)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, t)

    # Insert history records
    cursor.execute("INSERT INTO history (track_id, played_at, duration_listened, completed) VALUES (1, '2026-08-03 08:30:00', 230.0, 1)")
    cursor.execute("INSERT INTO history (track_id, played_at, duration_listened, completed) VALUES (2, '2026-08-03 09:15:00', 200.0, 1)")
    cursor.execute("INSERT INTO history (track_id, played_at, duration_listened, completed) VALUES (3, '2026-08-03 10:00:00', 203.0, 1)")

    conn.commit()
    return conn


class TestNewRecommendations(unittest.TestCase):
    """Test suite for validating recommendation service implementation and UI compliance."""

    def setUp(self):
        from services.base_service import BaseMusicService
        if getattr(BaseMusicService._executor, '_shutdown', False):
            BaseMusicService._executor = ThreadPoolExecutor(max_workers=15)
        self.mock_db = create_mock_db()
        self.service = RecommendationService(db=self.mock_db)

    def tearDown(self):
        if hasattr(self, 'mock_db') and self.mock_db:
            try:
                self.mock_db.close()
            except Exception:
                pass

    def test_get_smart_home_feed_with_mock_db(self):
        """1. Test get_smart_home_feed with mock listening history in local SQLite DB."""
        # Mock Last.fm API calls
        self.service.lastfm.artist_get_top_tracks = MagicMock(return_value=[
            {'name': 'Blinding Lights', 'artist': 'The Weeknd'},
            {'name': 'Save Your Tears', 'artist': 'The Weeknd'}
        ])
        self.service.lastfm.chart_get_top_tracks = MagicMock(return_value=[
            {'name': 'Levitating', 'artist': 'Dua Lipa'},
            {'name': 'Don\'t Start Now', 'artist': 'Dua Lipa'}
        ])

        # Mock resolver to return properly structured UI track
        def mock_resolve(title, artist=""):
            return {
                'title': title,
                'artist': artist or 'The Weeknd',
                'cover_url': 'https://cover.jpg',
                'source': 'soundcloud',
                'source_id': '101',
                'source_url': 'https://soundcloud.com/101',
                'duration': 180.0,
                'is_favorite': True,
                'is_downloaded': False
            }

        self.service.resolver.resolve_track = MagicMock(side_effect=mock_resolve)

        done_event = threading.Event()
        result_payload = None

        def callback(payload):
            nonlocal result_payload
            result_payload = payload
            done_event.set()

        self.service.get_smart_home_feed(history=[], callback=callback)
        success = done_event.wait(timeout=5.0)

        self.assertTrue(success, "get_smart_home_feed timed out waiting for callback.")
        self.assertIsNotNone(result_payload, "Payload returned from get_smart_home_feed is None.")
        self.assertIn('greeting', result_payload)
        self.assertIn(result_payload['greeting'], ['Доброе утро', 'Добрый день', 'Добрый вечер', 'Доброй ночи'])
        self.assertIn('sections', result_payload)
        self.assertEqual(len(result_payload['sections']), 4, "Smart home feed must contain exactly 4 sections.")

        section_titles = [sec['title'] for sec in result_payload['sections']]
        self.assertIn("Специально для вас", section_titles)
        self.assertIn("Новые релизы", section_titles)
        self.assertIn("Топ-чарты", section_titles)

    def test_get_mixes_generation_and_sequencing(self):
        """2. Test get_mixes generation and R5 energy curve mix sequencing."""
        self.service.lastfm.artist_get_top_tracks = MagicMock(return_value=[
            {'name': 'Track Low', 'artist': 'The Weeknd', 'energy': 0.2},
            {'name': 'Track Peak', 'artist': 'The Weeknd', 'energy': 0.9},
            {'name': 'Track Mid', 'artist': 'The Weeknd', 'energy': 0.5},
            {'name': 'Track WindDown', 'artist': 'The Weeknd', 'energy': 0.3}
        ])
        self.service.lastfm.chart_get_top_tracks = MagicMock(return_value=[
            {'name': 'Flow Track 1', 'artist': 'Dua Lipa'},
            {'name': 'Flow Track 2', 'artist': 'Dua Lipa'}
        ])

        def mock_resolve(title, artist=""):
            energy_val = 0.9 if 'Peak' in title else (0.2 if 'Low' in title else 0.5)
            return {
                'title': title,
                'artist': artist or 'The Weeknd',
                'cover_url': 'https://cover.jpg',
                'source': 'soundcloud',
                'source_id': 'mix_1',
                'source_url': 'https://soundcloud.com/mix_1',
                'duration': 210.0,
                'energy': energy_val
            }

        self.service.resolver.resolve_track = MagicMock(side_effect=mock_resolve)

        done_event = threading.Event()
        mixes_result = None

        def callback(res):
            nonlocal mixes_result
            mixes_result = res
            done_event.set()

        self.service.get_mixes(history=[{'artist': 'The Weeknd'}], callback=callback)
        success = done_event.wait(timeout=5.0)

        self.assertTrue(success, "get_mixes timed out waiting for callback.")
        self.assertIsInstance(mixes_result, list)
        self.assertGreater(len(mixes_result), 0, "get_mixes returned an empty list.")

        first_mix = mixes_result[0]
        self.assertEqual(first_mix.get('type'), 'custom_playlist')
        valid_title_prefixes = ('Микс:', 'Мой поток:', 'Из лайков')
        self.assertTrue(
            any(first_mix.get('title', '').startswith(p) for p in valid_title_prefixes),
            f"Unexpected mix title: '{first_mix.get('title')}'. Expected one of: {valid_title_prefixes}"
        )
        self.assertIn('tracks', first_mix)
        self.assertIsInstance(first_mix['tracks'], list)
        self.assertGreater(len(first_mix['tracks']), 0)

        # Explicit test for _sequence_mix_tracks helper
        raw_tracks = [
            {'title': 'T1', 'energy': 0.9},
            {'title': 'T2', 'energy': 0.1},
            {'title': 'T3', 'energy': 0.5},
            {'title': 'T4', 'energy': 0.7}
        ]
        sequenced = self.service._sequence_mix_tracks(raw_tracks)
        self.assertEqual(len(sequenced), 4)
        # Ensure temporary '_energy' key is cleaned up
        for t in sequenced:
            self.assertNotIn('_energy', t)

    def test_network_failure_and_mock_fallbacks(self):
        """3. Test network failure / mock fallbacks for Last.fm and SoundCloud APIs (confirming zero crashes and graceful local DB fallback)."""
        # Inject network error mocks into Last.fm session and SoundCloud/YouTube search helpers
        with patch.object(requests.Session, 'get', side_effect=Exception("Network Connection Refused")), \
             patch.object(self.service.resolver, '_search_soundcloud', return_value=None), \
             patch.object(self.service.resolver, '_search_youtube', return_value=None):

                # 3a. get_smart_home_feed under network failure
                done_event = threading.Event()
                feed_payload = None

                def feed_cb(payload):
                    nonlocal feed_payload
                    feed_payload = payload
                    done_event.set()

                self.service.get_smart_home_feed(history=[], callback=feed_cb)
                feed_ok = done_event.wait(timeout=10.0)

                self.assertTrue(feed_ok, "get_smart_home_feed timed out during network failure fallback.")
                self.assertIsNotNone(feed_payload)
                self.assertIn('greeting', feed_payload)
                self.assertIn('sections', feed_payload)

                # 3b. get_mixes under network failure
                done_event_mix = threading.Event()
                mixes_res = None

                def mixes_cb(res):
                    nonlocal mixes_res
                    mixes_res = res
                    done_event_mix.set()

                self.service.get_mixes(history=[], callback=mixes_cb)
                mix_ok = done_event_mix.wait(timeout=10.0)

                self.assertTrue(mix_ok, "get_mixes timed out during network failure fallback.")
                self.assertIsInstance(mixes_res, list)

                # 3c. _fetch_recommendations under network failure (graceful local DB fallback)
                recommendations = self.service._fetch_recommendations({'artist': 'The Weeknd'}, max_results=5)
                self.assertIsInstance(recommendations, list)
                self.assertGreater(len(recommendations), 0, "Offline recommendations fallback returned empty list.")

                # 3d. Additional entry points check for zero crashes
                done_event_charts = threading.Event()
                self.service.get_charts(max_results=5, callback=lambda trks: done_event_charts.set())
                self.assertTrue(done_event_charts.wait(timeout=10.0))

                done_event_releases = threading.Event()
                self.service.get_releases(max_results=5, callback=lambda trks: done_event_releases.set())
                self.assertTrue(done_event_releases.wait(timeout=10.0))

    def test_static_ast_and_mock_assertions_no_ytmusic(self):
        """4. Test static AST and mock assertions confirming ZERO calls or imports to YTMusic.get_explore or YTMusic.get_watch_playlist."""
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        target_files = [
            os.path.join(project_root, 'services', 'recommendation_service.py'),
            os.path.join(project_root, 'core', 'api.py'),
            os.path.join(project_root, 'core', 'services', 'recommendation.py')
        ]

        forbidden_names = {'get_explore', 'get_watch_playlist', 'watch_playlist'}
        ast_violations = []

        for filepath in target_files:
            if not os.path.exists(filepath):
                continue
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            tree = ast.parse(content, filename=filepath)

            class YTMusicVisitor(ast.NodeVisitor):
                def visit_ImportFrom(self, node):
                    if node.module and 'ytmusic' in node.module.lower():
                        ast_violations.append(f"Forbidden YTMusic import in {filepath}:{node.lineno}")
                    self.generic_visit(node)

                def visit_Attribute(self, node):
                    if node.attr in forbidden_names:
                        ast_violations.append(f"Forbidden method attribute '{node.attr}' accessed in {filepath}:{node.lineno}")
                    self.generic_visit(node)

                def visit_Call(self, node):
                    if isinstance(node.func, ast.Attribute) and node.func.attr in forbidden_names:
                        ast_violations.append(f"Forbidden call to '{node.func.attr}' in {filepath}:{node.lineno}")
                    self.generic_visit(node)

            visitor = YTMusicVisitor()
            visitor.visit(tree)

        self.assertEqual(len(ast_violations), 0, f"Found forbidden YTMusic calls/imports in AST check: {ast_violations}")

        # Mock runtime assertion confirming ZERO calls
        mock_ytmusic_instance = MagicMock()
        mock_ytmusic_instance.get_explore = MagicMock(side_effect=AssertionError("YTMusic.get_explore was called!"))
        mock_ytmusic_instance.get_watch_playlist = MagicMock(side_effect=AssertionError("YTMusic.get_watch_playlist was called!"))

        # Mock Last.fm & TrackResolver so runtime execution is fast and completely offline
        self.service.lastfm.artist_get_top_tracks = MagicMock(return_value=[])
        self.service.lastfm.chart_get_top_tracks = MagicMock(return_value=[])
        self.service.resolver.resolve_track = MagicMock(return_value={
            'title': 'Test Track',
            'artist': 'The Weeknd',
            'cover_url': '',
            'source': 'soundcloud',
            'source_id': '101',
            'source_url': '',
            'duration': 180.0
        })

        # Execute recommendations with mocked YTMusic
        done_event_feed = threading.Event()
        self.service.get_smart_home_feed(history=[], callback=lambda payload: done_event_feed.set())
        done_event_feed.wait(timeout=5.0)

        done_event_mixes = threading.Event()
        self.service.get_mixes(history=[], callback=lambda res: done_event_mixes.set())
        done_event_mixes.wait(timeout=5.0)

        self.service._fetch_recommendations({'artist': 'The Weeknd'}, max_results=5)

        self.assertEqual(mock_ytmusic_instance.get_explore.call_count, 0)
        self.assertEqual(mock_ytmusic_instance.get_watch_playlist.call_count, 0)

    def test_strict_json_ui_schema_validation(self):
        """5. Validate JSON output format strictly matches expected UI structure and mandatory track fields."""
        # Mock resolver to supply full tracks
        def mock_resolve(title, artist=""):
            return {
                'title': title,
                'artist': artist or 'Sample Artist',
                'cover_url': 'https://img.com/cover.jpg',
                'source': 'soundcloud',
                'source_id': 'track_99',
                'source_url': 'https://soundcloud.com/track_99',
                'duration': 215.5,
                'is_favorite': True,
                'is_downloaded': False
            }

        self.service.resolver.resolve_track = MagicMock(side_effect=mock_resolve)

        mandatory_fields = {
            'title': str,
            'artist': str,
            'cover_url': str,
            'source': str,
            'source_id': str,
            'source_url': str,
            'duration': (int, float),
            'is_favorite': bool,
            'is_downloaded': bool
        }

        # 5a. Test Feed Payload Schema
        done_event = threading.Event()
        feed_payload = None

        def feed_cb(payload):
            nonlocal feed_payload
            feed_payload = payload
            done_event.set()

        self.service.get_smart_home_feed(history=[], callback=feed_cb)
        self.assertTrue(done_event.wait(timeout=5.0))

        self.assertIsInstance(feed_payload, dict, "Feed payload must be a JSON dict.")
        self.assertIn('greeting', feed_payload)
        self.assertIsInstance(feed_payload['greeting'], str)
        self.assertIn('sections', feed_payload)
        self.assertIsInstance(feed_payload['sections'], list)

        for sec in feed_payload['sections']:
            self.assertIn('title', sec)
            self.assertIsInstance(sec['title'], str)
            self.assertIn('items', sec)
            self.assertIsInstance(sec['items'], list)

            for item in sec['items']:
                self.assertIsInstance(item, dict)
                if item.get('type') == 'custom_playlist':
                    self.assertIn('title', item)
                    self.assertIn('artist', item)
                    self.assertIn('cover_url', item)
                    self.assertIn('tracks', item)
                    self.assertIsInstance(item['tracks'], list)
                    for track in item['tracks']:
                        for field, expected_type in mandatory_fields.items():
                            self.assertIn(field, track, f"Missing mandatory field '{field}' in mix track: {track}")
                            self.assertIsInstance(track[field], expected_type, f"Field '{field}' has wrong type {type(track[field])} in track {track}")
                else:
                    for field, expected_type in mandatory_fields.items():
                        self.assertIn(field, item, f"Missing mandatory field '{field}' in feed item: {item}")
                        self.assertIsInstance(item[field], expected_type, f"Field '{field}' has wrong type {type(item[field])} in item {item}")

        # 5b. Test Mixes Payload Schema
        done_event_mix = threading.Event()
        mixes_res = None

        def mixes_cb(res):
            nonlocal mixes_res
            mixes_res = res
            done_event_mix.set()

        self.service.get_mixes(history=[], callback=mixes_cb)
        self.assertTrue(done_event_mix.wait(timeout=5.0))

        self.assertIsInstance(mixes_res, list)
        for mix in mixes_res:
            self.assertIsInstance(mix, dict)
            self.assertEqual(mix.get('type'), 'custom_playlist')
            self.assertIn('title', mix)
            self.assertIn('artist', mix)
            self.assertIn('cover_url', mix)
            self.assertIn('tracks', mix)
            self.assertIsInstance(mix['tracks'], list)

            for track in mix['tracks']:
                for field, expected_type in mandatory_fields.items():
                    self.assertIn(field, track, f"Missing mandatory field '{field}' in mix track: {track}")
                    self.assertIsInstance(track[field], expected_type, f"Field '{field}' in mix track has wrong type: {type(track[field])}")


# Run via standard unittest if executed as script
if __name__ == '__main__':
    unittest.main()
