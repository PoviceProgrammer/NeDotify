"""
Unit test suite for RecommendationEngine (core/services/recommendation.py)
and current RecommendationService wave/format contracts.
Pre-port get_flow_tracks_sync and ALLOWED_RECOMMENDATION_SOURCES expectations
remain in tests/legacy_pre_parity; current radio uses get_wave_for_track.
"""

import sqlite3
import unittest
from unittest.mock import MagicMock, patch

from core.services.recommendation import RecommendationEngine, build_real_engine
from services.recommendation_service import RecommendationService
from tests.helpers import recommendations, track, fetch


class TestRecommendationEngine(unittest.TestCase):
    """Test robustness and edge cases of RecommendationEngine."""

    def setUp(self):
        self.sample_catalog = [
            {
                "id": "trk_1",
                "title": "Track One",
                "artist": "Artist A",
                "artist_id": "art_a",
                "bpm": None,
                "energy": None,
                "mood": None,
                "acoustics": None,
                "bass": None,
                "global_streams": None,
                "viral_velocity": None,
                "is_new_release": True,
            },
            {
                "id": "trk_2",
                "title": "Track Two",
                "artist": "Artist B",
                "artist_id": "art_b",
                "bpm": 128,
                "energy": 0.8,
                "mood": 0.7,
                "acoustics": 0.2,
                "bass": 0.9,
                "global_streams": 1000,
                "viral_velocity": 50,
                "is_new_release": False,
            },
            {
                "id": "trk_3",
                "title": "Track Three",
                "artist": "Artist A",
                "artist_id": "art_a",
                "bpm": "110",
                "energy": "0.4",
                "mood": "0.5",
                "acoustics": "0.6",
                "bass": "0.3",
                "global_streams": 5000,
                "viral_velocity": None,
                "is_new_release": True,
            },
            {
                # Track missing 'id' attribute completely
                "title": "Malformed Track",
                "artist": "Artist C",
            }
        ]

        self.null_profile = {
            "history": None,
            "favorites": None,
            "subscriptions": None,
            "genres": None,
            "moods": None,
            "skips": None,
            "repeats": None,
        }

        self.context = {
            "time_of_day": "evening",
            "device": "desktop",
            "activity": "workout",
        }

    def test_engine_handles_null_profile_and_missing_features(self):
        """RecommendationEngine must not crash with TypeError on null profile fields or None features."""
        engine = RecommendationEngine(self.null_profile, self.context, self.sample_catalog)
        all_recs = engine.generate_all()
        self.assertIsInstance(all_recs, dict)
        self.assertIn("dynamic_mixes", all_recs)
        self.assertIn("smart_recs", all_recs)
        self.assertIn("dynamic_charts", all_recs)

    def test_dynamic_charts_sorting_with_none_values(self):
        """Dynamic charts must safely sort tracks with None global_streams and viral_velocity."""
        engine = RecommendationEngine(self.null_profile, self.context, self.sample_catalog)
        charts = engine.generate_dynamic_charts()
        self.assertIn("global_top_50", charts)
        self.assertIn("viral_72h", charts)
        self.assertIn("personal_top", charts)
        self.assertTrue(all(isinstance(tid, str) for tid in charts["global_top_50"]))

    def test_euclidean_distance_with_none_and_strings(self):
        """_euclidean_distance handles None, strings, and missing features gracefully."""
        engine = RecommendationEngine(self.null_profile, self.context, self.sample_catalog)
        t1 = {"bpm": None, "energy": None}
        t2 = {"bpm": "130", "energy": "0.7"}
        dist = engine._euclidean_distance(t1, t2)
        self.assertIsInstance(dist, float)
        self.assertGreaterEqual(dist, 0.0)

    def test_build_real_engine_with_mock_db(self):
        """build_real_engine constructs valid engine without mutating corrupt data."""
        mock_db = MagicMock()
        mock_db.get_all_tracks.return_value = [
            {"id": 1, "bpm": None, "energy": None, "title": "DB Track"}
        ]
        mock_db.get_history.return_value = [{"track_id": "1"}]
        mock_db.get_favorite_tracks.return_value = [{"id": "1"}]
        mock_db.get_most_played.return_value = [{"id": "1", "play_count": 5}]

        engine = build_real_engine(mock_db, personalization=None)
        self.assertIsInstance(engine, RecommendationEngine)
        res = engine.generate_all()
        self.assertIsInstance(res, dict)


class TestRecommendationService(unittest.TestCase):
    """Test RecommendationService formatting, provider fallbacks, and sync flow."""

    def setUp(self):
        self.service = RecommendationService(settings=None, db=None)
        self.service._collect_candidates = lambda *args, **kwargs: []

    def tearDown(self):
        self.service._candidate_executor.shutdown(wait=True, cancel_futures=True)

    def test_format_ui_track_with_sqlite_row(self):
        """_format_ui_track must correctly extract data from sqlite3.Row objects."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 42 as id, 'Test Title' as title, 'Test Artist' as artist, "
            "'https://example.com/cover.jpg' as cover_url, 'vk' as source, "
            "'vk_123' as source_id, 'https://vk.com/audio123' as source_url, "
            "180.5 as duration"
        )
        row = cursor.fetchone()

        formatted = self.service._format_ui_track(row)
        self.assertIsInstance(formatted, dict)
        self.assertEqual(formatted.get("title"), "Test Title")
        self.assertEqual(formatted.get("artist"), "Test Artist")
        self.assertEqual(formatted.get("source"), "vk")
        self.assertEqual(formatted.get("source_id"), "vk_123")
        self.assertEqual(formatted.get("duration"), 180.5)

    def test_format_ui_track_invalid_types(self):
        """_format_ui_track gracefully handles None, numbers, strings, empty input."""
        self.assertEqual(self.service._format_ui_track(None), {})
        self.assertEqual(self.service._format_ui_track(123), {})
        self.assertEqual(self.service._format_ui_track("invalid"), {})
        self.assertEqual(self.service._format_ui_track([]), {})



    def test_get_wave_for_track_with_none_seed(self):
        """get_wave_for_track must not crash with AttributeError when seed_track is None or empty."""
        results = self.service.get_wave_for_track(None, limit=5, callback=None)
        self.assertIsInstance(results, list)


def test_current_wave_returns_playable_related_tracks_and_excludes_seed(recommendations):
    seed = track('dQw4w9WgXcQ', 'Seed', 'Seed Artist')
    recommendations.youtube_service.get_related_tracks_sync = lambda *args, **kwargs: [
        seed, track('new-song', 'New Song', 'Related Artist')]
    rows = recommendations.get_wave_for_track(seed, limit=2)
    assert [item['source_id'] for item in rows] == ['new-song']
    assert rows[0]['recommendation_origin'] == 'wave'
    assert rows[0]['recommendation_reason'] == 'По музыке Seed Artist'
    assert fetch(recommendations.get_wave_for_track, seed, limit=2) == rows


def test_current_wave_accepts_empty_seed_without_network_or_synthetic_candidates(recommendations):
    recommendations._collect_candidates = lambda *args, **kwargs: []
    assert recommendations.get_wave_for_track(None, limit=5) == []


def test_current_recommendations_keep_downloaded_linux_tracks_usable_offline(recommendations):
    from services.taste_profile import UserTasteProfile
    profile = UserTasteProfile()
    local = track('local-track', 'Offline Song', 'Offline Artist', source='local', id=12,
                  is_downloaded=True, file_path='/home/user/Music/song.flac', cover_path='/home/user/Music/cover.jpg')
    profile.favorite_tracks = [local]
    rows = recommendations._rank_tracks([local], profile, 1)
    assert len(rows) == 1
    assert rows[0]['file_path'] == local['file_path']
    assert rows[0]['cover_path'] == local['cover_path']


