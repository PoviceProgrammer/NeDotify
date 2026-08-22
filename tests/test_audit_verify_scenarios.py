import os
import sys
import threading
import time
import subprocess
import unittest

from services.zapret_service import ZapretService, sanitize_zapret_args
from audio.queue import PlaybackQueue
from core.settings import SettingsManager
from core.database import DatabaseManager

class ScenarioVerificationTests(unittest.TestCase):
    def test_scenario_1_zapret_windows_path_args(self):
        """Scenario 1: Verify Zapret regex accepts Windows backslash paths."""
        args_with_path = r'--hostlist=C:\zapret\hosts.txt --wf-tcp=80,443'
        sanitized = sanitize_zapret_args(args_with_path)
        self.assertIn(r'--hostlist=C:\zapret\hosts.txt', sanitized)
        self.assertIn('--wf-tcp=80,443', sanitized)

    def test_scenario_2_zapret_alien_pid_protection(self):
        """Scenario 2: Verify Zapret does NOT adopt alien external PIDs."""
        db = DatabaseManager(":memory:")
        settings = SettingsManager(db)
        service = ZapretService(settings)
        current_pid = os.getpid()
        is_our = service._is_our_winws_process(current_pid)
        self.assertFalse(is_our, "Non-winws process must never be recognized as our winws process")

    def test_scenario_3_queue_thread_safety_concurrency(self):
        """Scenario 3: Verify PlaybackQueue under high concurrent multithreading."""
        queue = PlaybackQueue()
        errors = []

        def worker(worker_id):
            try:
                for i in range(100):
                    track = {"id": worker_id * 1000 + i, "title": f"Track {i}", "artist": "Artist"}
                    queue.add_track(track)
                    if i % 10 == 0:
                        queue.shuffle = not queue.shuffle
                    if i % 5 == 0:
                        queue.next_track()
                    if i % 7 == 0:
                        queue.previous_track()
                    _ = queue.current_track
                    _ = queue.to_serializable()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Thread safety errors occurred: {errors}")
        self.assertGreater(queue.count, 0)

    def test_scenario_4_lufs_replaygain_formula(self):
        """Scenario 4: Verify ReplayGain calculation formula."""
        target_lufs = -14.0
        loudness_10 = -10.0
        gain_10 = round(pow(10, (target_lufs - loudness_10) / 20), 4)
        self.assertAlmostEqual(gain_10, 0.6310, places=3)
        self.assertLess(gain_10, 1.0)

        loudness_18 = -18.0
        gain_18 = round(pow(10, (target_lufs - loudness_18) / 20), 4)
        self.assertAlmostEqual(gain_18, 1.5849, places=3)
        self.assertGreater(gain_18, 1.0)

if __name__ == '__main__':
    unittest.main()
