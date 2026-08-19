import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from services.recommendation_service import RecommendationService
from core.api import AppApi


class TestPhase3Phase4FlowPrefetch(unittest.TestCase):
    def setUp(self):
        self.mock_settings = MagicMock()
        self.mock_db = MagicMock()
        self.mock_sc = MagicMock()
        self.mock_yt = MagicMock()

        self.rec_service = RecommendationService(
            settings=self.mock_settings,
            db=self.mock_db,
            soundcloud_service=self.mock_sc,
            youtube_service=self.mock_yt
        )

    def test_get_flow_tracks_sync_soundcloud_fallback_yt(self):
        seed = {"source": "soundcloud", "source_id": "12345", "title": "Song 1", "artist": "Artist 1"}

        # 1. SC returns 2 related tracks
        self.mock_sc.get_related_tracks_sync.return_value = [
            {"source": "soundcloud", "source_id": "101", "title": "Related 1", "artist": "Artist 1"},
            {"source": "soundcloud", "source_id": "102", "title": "Related 2", "artist": "Artist 2"}
        ]
        # 2. YT returns 2 fallback tracks
        self.mock_yt.search_sync.return_value = [
            {"source": "youtube", "source_id": "yt01", "title": "YT Hit 1", "artist": "Artist 1"},
            {"source": "youtube", "source_id": "yt02", "title": "YT Hit 2", "artist": "Artist 3"}
        ]

        tracks = self.rec_service.get_flow_tracks_sync(seed, limit=4, exclude_ids=["101"])
        self.assertIsInstance(tracks, list)
        # Excluded track 101 should not be in results
        self.assertFalse(any(str(t.get("source_id")) == "101" for t in tracks))
        # 102 and YT tracks should be present
        self.assertTrue(any(str(t.get("source_id")) == "102" for t in tracks))

    def test_get_flow_tracks_all_providers_fail_gracefully(self):
        seed = {"source": "youtube", "source_id": "xyz", "title": "Rare Song", "artist": "Unknown"}
        self.mock_sc.get_related_tracks_sync.side_effect = Exception("SC down")
        self.mock_yt.search_sync.side_effect = Exception("YT down")
        self.mock_db.get_history.return_value = []

        tracks = self.rec_service.get_flow_tracks_sync(seed, limit=6)
        self.assertEqual(tracks, [])

    def test_api_get_flow_tracks_and_prefetch(self):
        mock_core = MagicMock()
        mock_core.recommendations = self.rec_service
        self.mock_sc.get_related_tracks_sync.return_value = [
            {"source": "soundcloud", "source_id": "999", "title": "Flow Hit", "artist": "Star"}
        ]

        api = AppApi(mock_core)
        res = api.get_flow_tracks({"source": "soundcloud", "source_id": "123", "title": "A", "artist": "B"}, limit=1)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["title"], "Flow Hit")

        # Test prefetch_track call
        prefetch_res = api.prefetch_track({"source": "soundcloud", "source_id": "999"})
        self.assertTrue(prefetch_res)


if __name__ == "__main__":
    unittest.main()
