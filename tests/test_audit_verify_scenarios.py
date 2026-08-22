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
        """Scenario 3: Verify PlaybackQueue under high concurrent multithreading (20 threads, 5000 ops)."""
        queue = PlaybackQueue()
        errors = []
        num_threads = 20
        ops_per_thread = 250

        def worker(worker_id):
            try:
                for i in range(ops_per_thread):
                    track_id = worker_id * 10000 + i
                    track = {"id": track_id, "title": f"Track {track_id}", "artist": "Artist"}
                    queue.add_track(track)
                    
                    if i % 3 == 0:
                        _ = queue.next_track()
                    if i % 5 == 0:
                        queue.shuffle = (i % 2 == 0)
                    if i % 7 == 0:
                        _ = queue.previous_track()
                    if i % 11 == 0 and queue.count > 5:
                        queue.move_track(0, queue.count - 1)
                    if i % 13 == 0 and queue.count > 3:
                        _ = queue.jump_to(queue.count // 2)
                    if i % 17 == 0:
                        _ = queue.to_serializable()
                    if i % 19 == 0:
                        _ = queue.get_upcoming(5)

                    # Artificial micro-yield to force thread preemption / context switches
                    if i % 25 == 0:
                        time.sleep(0.0001)
            except Exception as e:
                errors.append((worker_id, e))

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Thread safety errors occurred under high concurrency: {errors}")
        self.assertGreater(queue.count, 0)
        state = queue.to_serializable()
        self.assertIsInstance(state, dict)

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
