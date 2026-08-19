import os
import tempfile
import unittest
import sqlite3
from unittest.mock import MagicMock
from utils.tag_parser import parse_tags, write_tags
from core.database import DatabaseManager


class TestPhase1TagEditor(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_aura.db")
        self.db = DatabaseManager(self.db_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_database_update_track_metadata_and_fts(self):
        # 1. Insert a track
        track_id = self.db.add_track(
            title="Original Track Title",
            artist="Original Artist",
            album="Old Album",
            genre="Rock",
            year=2020,
            file_path=os.path.join(self.temp_dir, "song.mp3")
        )
        self.assertIsNotNone(track_id)

        # 2. Update metadata
        success = self.db.update_track_metadata(
            track_id=track_id,
            title="Brand New Super Hit",
            artist="Awesome Band",
            album="Masterpiece 2026",
            genre="Synthwave",
            year=2026
        )
        self.assertTrue(success)

        # 3. Verify updated row
        updated = self.db.get_track(track_id)
        self.assertEqual(updated["title"], "Brand New Super Hit")
        self.assertEqual(updated["artist"], "Awesome Band")
        self.assertEqual(updated["album"], "Masterpiece 2026")
        self.assertEqual(updated["genre"], "Synthwave")
        self.assertEqual(updated["year"], 2026)

        # 4. Verify FTS5 search finds the updated title
        search_res = self.db.search_tracks("Brand New Super Hit")
        self.assertTrue(any(t["id"] == track_id for t in search_res))

    def test_readonly_file_permission_error(self):
        # Create a dummy file
        dummy_file = os.path.join(self.temp_dir, "dummy_readonly.mp3")
        with open(dummy_file, "wb") as f:
            f.write(b"ID3" + b"\x00" * 100)

        # Make file read-only on Windows
        import stat
        os.chmod(dummy_file, stat.S_IREAD)

        try:
            with self.assertRaises(PermissionError):
                write_tags(dummy_file, title="New Title")
        finally:
            # Restore write permission for cleanup
            os.chmod(dummy_file, stat.S_IWRITE)


if __name__ == "__main__":
    unittest.main()
