import os
import sys
import tempfile
import unittest

# Add root folder to python path to import core modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.database import DatabaseManager

class TestPlaylistVerification(unittest.TestCase):
    def setUp(self):
        # Create a temporary database file
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self.db = DatabaseManager(self.db_path)

    def tearDown(self):
        # Close database connection and clean up temporary database file
        self.db.close()
        os.close(self.db_fd)
        try:
            os.remove(self.db_path)
        except OSError:
            pass

    def test_playlist_creation_and_addition(self):
        print("\n[VERIFICATION] Running Playlist Creation and Addition Checks...")
        
        # 1. Create a playlist
        playlist_name = "Rock Classics"
        playlist_desc = "Timeless rock hits"
        pid = self.db.create_playlist(playlist_name, playlist_desc)
        print(f"Created playlist '{playlist_name}' with ID: {pid}")
        self.assertIsNotNone(pid)
        self.assertGreater(pid, 0)
        
        # 2. Get playlists and verify
        playlists = self.db.get_playlists()
        print(f"Current playlists in database: {playlists}")
        self.assertEqual(len(playlists), 1)
        self.assertEqual(playlists[0]['name'], playlist_name)
        self.assertEqual(playlists[0]['description'], playlist_desc)
        self.assertEqual(playlists[0]['track_count'], 0)
        
        # 3. Add tracks to database
        t1_id = self.db.add_track(title="Comfortably Numb", artist="Pink Floyd", duration=379.0, source="local", source_id="numb.mp3")
        t2_id = self.db.add_track(title="Hotel California", artist="Eagles", duration=390.0, source="local", source_id="hotel.mp3")
        print(f"Added track 'Comfortably Numb' with ID: {t1_id}")
        print(f"Added track 'Hotel California' with ID: {t2_id}")
        self.assertIsNotNone(t1_id)
        self.assertIsNotNone(t2_id)
        
        # 4. Add tracks to the playlist
        print("Adding tracks to the playlist...")
        self.db.add_to_playlist(pid, t1_id)
        self.db.add_to_playlist(pid, t2_id)
        
        # 5. Verify tracks in playlist
        ptracks = self.db.get_playlist_tracks(pid)
        print(f"Tracks in playlist: {ptracks}")
        self.assertEqual(len(ptracks), 2)
        self.assertEqual(ptracks[0]['title'], "Comfortably Numb")
        self.assertEqual(ptracks[0]['position'], 1)
        self.assertEqual(ptracks[1]['title'], "Hotel California")
        self.assertEqual(ptracks[1]['position'], 2)
        
        # 6. Verify playlist track count updated
        playlists = self.db.get_playlists()
        self.assertEqual(playlists[0]['track_count'], 2)
        print("Playlist creation and track addition verification passed without crashes!")

if __name__ == "__main__":
    unittest.main()
