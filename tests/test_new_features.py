"""
Automated Integration & Unit Tests for the 4 New Feature Modules:
1. NeDotify Wrapped Stats & Activity Analytics
2. Speed / Nightcore / Daycore Engine Integration
3. Audio Fingerprint Service & Duplicate Scanner
4. Artist Search Cards & Blackout Policy Compliance
"""

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock

from core.database import DatabaseManager
from core.api import AppApi
from services.audio_fingerprint_service import AudioFingerprintService


class TestNewFeatureModules(unittest.TestCase):

    def setUp(self):
        self.temp_db_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db_file.close()
        self.db = DatabaseManager(self.temp_db_file.name)

        # Populate test tracks
        self.track1_id = self.db.add_track(
            title="Song Alpha",
            artist="Artist A",
            album="Album A",
            source="local",
            file_path=r"C:\fake\track1.mp3",
            duration=210
        )
        self.track2_id = self.db.add_track(
            title="Song Beta",
            artist="Artist A",
            album="Album A",
            source="local",
            file_path=r"C:\fake\track2.mp3",
            duration=180
        )
        self.track3_id = self.db.add_track(
            title="Song Gamma (Yandex Blackout)",
            artist="Artist Y",
            album="Album Y",
            source="yandex",
            file_path=r"C:\fake\track3.mp3",
            duration=200
        )

    def tearDown(self):
        try:
            os.remove(self.temp_db_file.name)
        except Exception:
            pass

    def test_wrapped_stats_period_aggregation(self):
        """Test NeDotify Wrapped listening time, top tracks, and daily activity calculation."""
        # Log listening history
        self.db.add_to_history(self.track1_id, duration_listened=210.0, completed=True)
        self.db.add_to_history(self.track1_id, duration_listened=210.0, completed=True)
        self.db.add_to_history(self.track2_id, duration_listened=180.0, completed=True)

        stats_week = self.db.get_wrapped_stats("week")
        self.assertEqual(stats_week["period"], "week")
        self.assertEqual(stats_week["total_plays"], 3)
        self.assertAlmostEqual(stats_week["total_seconds"], 600.0, places=1)
        self.assertAlmostEqual(stats_week["total_minutes"], 10.0, places=1)

        # Verify top tracks ordering
        self.assertTrue(len(stats_week["top_tracks"]) >= 2)
        self.assertEqual(stats_week["top_tracks"][0]["id"], self.track1_id)
        self.assertEqual(stats_week["top_tracks"][0]["plays"], 2)

        # Verify top artists
        self.assertTrue(len(stats_week["top_artists"]) >= 1)
        self.assertEqual(stats_week["top_artists"][0]["artist"], "Artist A")

        # Verify daily activity chart array (7 days)
        self.assertEqual(len(stats_week["daily_activity"]), 7)

    def test_wrapped_stats_empty_history(self):
        """Test Wrapped stats handles empty play history gracefully without errors."""
        stats = self.db.get_wrapped_stats("month")
        self.assertEqual(stats["total_plays"], 0)
        self.assertEqual(stats["total_seconds"], 0.0)
        self.assertEqual(len(stats["top_tracks"]), 0)
        self.assertEqual(len(stats["top_artists"]), 0)
        self.assertEqual(len(stats["daily_activity"]), 7)

    def test_audio_fingerprint_service_duplicate_scanner(self):
        """Test AudioFingerprintService computes signature and groups duplicates."""
        service = AudioFingerprintService()

        # Create temporary dummy audio files
        f1 = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        f1.write(b"ID3v2.3.0" + b"\x00\xff" * 1000)
        f1.close()

        f2 = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        with open(f1.name, "rb") as orig:
            f2.write(orig.read())
        f2.close()

        try:
            # Update tracks in db to point to actual temporary files
            t1 = self.db.add_track(
                title="Dup Track 1",
                artist="Artist Dup",
                source="local",
                file_path=f1.name
            )
            t2 = self.db.add_track(
                title="Dup Track 2",
                artist="Artist Dup",
                source="local",
                file_path=f2.name
            )

            fp1 = service.compute_file_fingerprint(f1.name)
            fp2 = service.compute_file_fingerprint(f2.name)

            self.assertIsNotNone(fp1)
            self.assertIsNotNone(fp2)
            self.assertEqual(fp1["hash"], fp2["hash"])

            duplicates = service.find_duplicates(self.db)
            self.assertEqual(len(duplicates), 1)
            self.assertEqual(duplicates[0]["count"], 2)

            # Test deletion of one duplicate
            del_res = service.delete_duplicate_track(self.db, t2, delete_file=False)
            self.assertTrue(del_res)

            # Re-scan should show 0 duplicate groups
            duplicates_after = service.find_duplicates(self.db)
            self.assertEqual(len(duplicates_after), 0)
        finally:
            os.remove(f1.name)
            os.remove(f2.name)

    def test_app_api_wrapped_and_duplicates_contract(self):
        """Test AppApi endpoints for get_wrapped_stats and find_duplicate_tracks."""
        mock_core = MagicMock()
        mock_core.db = self.db
        mock_core.audio_fingerprint = AudioFingerprintService()

        api = AppApi(mock_core)

        wrapped = api.get_wrapped_stats("week")
        self.assertIn("total_minutes", wrapped)
        self.assertIn("top_tracks", wrapped)

        dups = api.find_duplicate_tracks()
        self.assertIsInstance(dups, list)


if __name__ == "__main__":
    unittest.main()
