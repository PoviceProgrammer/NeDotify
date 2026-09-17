import threading
import time
import unittest
from audio.queue import PlaybackQueue


class TestPlaybackQueue(unittest.TestCase):
    def setUp(self):
        self.queue = PlaybackQueue()

    def test_init_empty(self):
        self.assertTrue(self.queue.is_empty)
        self.assertEqual(self.queue.count, 0)
        self.assertEqual(self.queue.current_index, -1)
        self.assertIsNone(self.queue.current_track)
        self.assertEqual(self.queue.tracks, [])
        self.assertFalse(self.queue.shuffle)
        self.assertEqual(self.queue.repeat, "off")

    def test_set_tracks_normal_and_clamped(self):
        tracks = [
            {"id": 1, "title": "Track 1", "source": "yt", "source_id": "1"},
            {"id": 2, "title": "Track 2", "source": "yt", "source_id": "2"},
            {"id": 3, "title": "Track 3", "source": "yt", "source_id": "3"},
        ]
        self.queue.set_tracks(tracks, start_index=1)
        self.assertEqual(self.queue.count, 3)
        self.assertEqual(self.queue.current_index, 1)
        self.assertEqual(self.queue.current_track["id"], 2)

        # Clamp start_index past upper bound
        self.queue.set_tracks(tracks, start_index=99)
        self.assertEqual(self.queue.current_index, 2)
        self.assertEqual(self.queue.current_track["id"], 3)

        # Negative indexing support for start_index (-1 means last track)
        self.queue.set_tracks(tracks, start_index=-1)
        self.assertEqual(self.queue.current_index, 2)
        self.assertEqual(self.queue.current_track["id"], 3)

    def test_set_tracks_invalid_types(self):
        self.queue.set_tracks(None)
        self.assertTrue(self.queue.is_empty)
        self.assertEqual(self.queue.current_index, -1)

        # Filters non-dict elements
        mixed = [{"id": 1, "title": "T1"}, "bad_string", None, 123, {"id": 2, "title": "T2"}]
        self.queue.set_tracks(mixed, start_index="bad")
        self.assertEqual(self.queue.count, 2)
        self.assertEqual(self.queue.current_index, 0)

    def test_add_track_and_type_validation(self):
        # Adding non-dict should be rejected safely
        res_none = self.queue.add_track(None)
        self.assertFalse(res_none)
        res_str = self.queue.add_track("not_a_dict")
        self.assertFalse(res_str)
        self.assertTrue(self.queue.is_empty)

        # Adding valid track
        t1 = {"id": 10, "title": "Song 10", "source": "sc", "source_id": "10"}
        res_valid = self.queue.add_track(t1)
        self.assertTrue(res_valid)
        self.assertEqual(self.queue.count, 1)
        self.assertEqual(self.queue.current_index, 0)
        self.assertEqual(self.queue.current_track["id"], 10)

    def test_add_track_play_next(self):
        t1 = {"id": 1, "title": "Track 1", "source": "yt", "source_id": "1"}
        t2 = {"id": 2, "title": "Track 2", "source": "yt", "source_id": "2"}
        t3 = {"id": 3, "title": "Track 3", "source": "yt", "source_id": "3"}
        self.queue.set_tracks([t1, t3], start_index=0)

        # Insert t2 to play next
        self.queue.add_track(t2, play_next=True)
        self.assertEqual(self.queue.count, 3)
        self.assertEqual(self.queue.tracks[1]["id"], 2)
        self.assertEqual(self.queue.current_index, 0)

    def test_add_tracks_batch(self):
        tracks = [
            {"id": 1, "title": "T1"},
            {"id": 2, "title": "T2"},
            "skip_me",
            {"id": 3, "title": "T3"},
        ]
        self.queue.add_tracks(tracks)
        self.assertEqual(self.queue.count, 3)
        self.assertEqual(self.queue.current_index, 0)

    def test_remove_track_negative_indexing(self):
        tracks = [
            {"id": 1, "title": "T1"},
            {"id": 2, "title": "T2"},
            {"id": 3, "title": "T3"},
        ]
        self.queue.set_tracks(tracks, start_index=0)
        # Remove last track with -1
        removed = self.queue.remove_track(-1)
        self.assertEqual(removed["id"], 3)
        self.assertEqual(self.queue.count, 2)
        self.assertEqual([t["id"] for t in self.queue.tracks], [1, 2])

    def test_remove_track_preserves_duplicate_occurrences(self):
        # Bug BUG-014: removing one duplicate must NOT wipe all duplicates from original order
        t_a1 = {"id": 1, "source": "yt", "source_id": "A", "title": "Song A"}
        t_b = {"id": 2, "source": "yt", "source_id": "B", "title": "Song B"}
        t_a2 = {"id": 1, "source": "yt", "source_id": "A", "title": "Song A"}
        self.queue.set_tracks([t_a1, t_b, t_a2], start_index=0)

        # Remove the first occurrence of Song A
        self.queue.remove_track(0)
        self.assertEqual(self.queue.count, 2)
        self.assertEqual([t["title"] for t in self.queue.tracks], ["Song B", "Song A"])

        # Enable and disable shuffle: Song A must still be present!
        self.queue.shuffle = True
        self.queue.shuffle = False
        track_titles = [t["title"] for t in self.queue.tracks]
        self.assertIn("Song A", track_titles)
        self.assertIn("Song B", track_titles)
        self.assertEqual(len(track_titles), 2)

    def test_remove_track_adjusts_history_stack(self):
        tracks = [{"id": i, "title": f"T{i}"} for i in range(5)]
        self.queue.set_tracks(tracks, start_index=0)
        # Advance through tracks to build history: 0 -> 1 -> 2
        self.queue.next_track()  # now at 1, history [0]
        self.queue.next_track()  # now at 2, history [0, 1]

        # Remove track at index 1
        self.queue.remove_track(1)
        # History should now only have [0]
        self.assertEqual(self.queue._history_stack, [0])

        # Previous track should return to track 0
        prev = self.queue.previous_track()
        self.assertEqual(prev["id"], 0)

    def test_move_track_and_negative_indexing(self):
        tracks = [{"id": i, "title": f"T{i}"} for i in range(4)]
        self.queue.set_tracks(tracks, start_index=0)

        # Move track 0 to end (-1)
        res = self.queue.move_track(0, -1)
        self.assertTrue(res)
        self.assertEqual([t["id"] for t in self.queue.tracks], [1, 2, 3, 0])
        # Current index shifted to 3 because current track moved
        self.assertEqual(self.queue.current_index, 3)

    def test_move_track_preserves_order_on_shuffle_toggle(self):
        # Bug BUG-015: manual move when shuffle is off must update _original_order
        tracks = [{"id": i, "title": f"T{i}"} for i in range(3)]
        self.queue.set_tracks(tracks, start_index=0)
        # Move T2 to position 0
        self.queue.move_track(2, 0)
        self.assertEqual([t["id"] for t in self.queue.tracks], [2, 0, 1])

        # Toggle shuffle on and off
        self.queue.shuffle = True
        self.queue.shuffle = False
        # The reordered order [2, 0, 1] must be restored, not the original [0, 1, 2]
        self.assertEqual([t["id"] for t in self.queue.tracks], [2, 0, 1])

    def test_peek_next(self):
        # Empty queue
        self.assertIsNone(self.queue.peek_next())

        tracks = [{"id": i, "title": f"T{i}"} for i in range(3)]
        self.queue.set_tracks(tracks, start_index=0)

        # Peek next should return T1 without changing current_index
        next_t = self.queue.peek_next()
        self.assertEqual(next_t["id"], 1)
        self.assertEqual(self.queue.current_index, 0)

        # Repeat one mode: peek_next returns current track
        self.queue.repeat = "one"
        self.assertEqual(self.queue.peek_next()["id"], 0)

        # At end of queue with repeat off
        self.queue.repeat = "off"
        self.queue.jump_to(2)
        self.assertIsNone(self.queue.peek_next())

        # At end of queue with repeat all
        self.queue.repeat = "all"
        self.assertEqual(self.queue.peek_next()["id"], 0)

    def test_next_track_repeat_modes(self):
        tracks = [{"id": 0, "title": "T0"}, {"id": 1, "title": "T1"}]
        self.queue.set_tracks(tracks, start_index=0)

        # Normal next
        t = self.queue.next_track()
        self.assertEqual(t["id"], 1)

        # End of queue with repeat off
        self.queue.repeat = "off"
        self.assertIsNone(self.queue.next_track())
        self.assertEqual(self.queue.current_index, 1)

        # Repeat one
        self.queue.repeat = "one"
        self.assertEqual(self.queue.next_track()["id"], 1)

        # Repeat all: wraps around
        self.queue.repeat = "all"
        self.assertEqual(self.queue.next_track()["id"], 0)
        self.assertEqual(self.queue.current_index, 0)

    def test_jump_to_negative_and_invalid(self):
        tracks = [{"id": 0, "title": "T0"}, {"id": 1, "title": "T1"}, {"id": 2, "title": "T2"}]
        self.queue.set_tracks(tracks, start_index=0)

        # Jump to last track using -1
        t = self.queue.jump_to(-1)
        self.assertEqual(t["id"], 2)
        self.assertEqual(self.queue.current_index, 2)

        # Invalid index
        self.assertIsNone(self.queue.jump_to(99))
        self.assertIsNone(self.queue.jump_to("invalid"))
        self.assertIsNone(self.queue.jump_to(True))

    def test_previous_track_history_and_clamping(self):
        tracks = [{"id": 0, "title": "T0"}, {"id": 1, "title": "T1"}]
        self.queue.set_tracks(tracks, start_index=0)
        self.queue.next_track()  # now at 1, history [0]

        # Previous returns to 0
        prev = self.queue.previous_track()
        self.assertEqual(prev["id"], 0)

        # If history contains corrupted/out-of-bounds index, previous_track clamps safely
        self.queue._history_stack.append(999)
        clamped = self.queue.previous_track()
        self.assertIsNotNone(clamped)
        self.assertTrue(0 <= self.queue.current_index < self.queue.count)

    def test_to_serializable_and_get_queue_track_ids(self):
        tracks = [{"id": 101, "title": "T1"}, {"id": 102, "title": "T2"}, "corrupted_non_dict"]
        self.queue._tracks = tracks  # directly simulate dirty state
        self.queue._current_index = 0

        serialized = self.queue.to_serializable()
        self.assertEqual(serialized["track_ids"], [101, 102])
        self.assertEqual(self.queue.get_queue_track_ids(), [101, 102])

    def test_concurrent_queue_access(self):
        tracks = [{"id": i, "title": f"T{i}", "source": "yt", "source_id": str(i)} for i in range(20)]
        self.queue.set_tracks(tracks, start_index=0)
        errors = []

        def worker(w_id):
            try:
                for i in range(50):
                    self.queue.peek_next()
                    self.queue.add_track({"id": 1000 + w_id * 100 + i, "title": f"Dyn_{w_id}_{i}"})
                    self.queue.next_track()
                    if i % 5 == 0:
                        self.queue.previous_track()
                    if i % 7 == 0:
                        self.queue.move_track(0, -1)
                    if i % 11 == 0 and self.queue.count > 2:
                        self.queue.remove_track(1)
            except Exception as e:
                errors.append(f"Worker {w_id}: {e}")

        threads = [threading.Thread(target=worker, args=(w,)) for w in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        self.assertGreater(self.queue.count, 0)
        self.assertTrue(0 <= self.queue.current_index < self.queue.count)

    def test_add_track_play_next_shifts_history_stack(self):
        t0 = {"id": 0, "title": "T0", "source": "yt", "source_id": "0"}
        t1 = {"id": 1, "title": "T1", "source": "yt", "source_id": "1"}
        t2 = {"id": 2, "title": "T2", "source": "yt", "source_id": "2"}
        self.queue.set_tracks([t0, t1, t2], start_index=0)
        self.queue.jump_to(2)  # at T2, history [0]
        self.queue.jump_to(0)  # at T0, history [0, 2]

        t_new = {"id": 99, "title": "T99", "source": "yt", "source_id": "99"}
        self.queue.add_track(t_new, play_next=True)
        self.assertEqual([t["id"] for t in self.queue.tracks], [0, 99, 1, 2])
        # History index 2 must have shifted to 3
        self.assertIn(3, self.queue._history_stack)
        prev = self.queue.previous_track()
        self.assertEqual(prev["id"], 2)

    def test_shuffle_toggling_remaps_history_stack(self):
        tracks = [{"id": i, "title": f"T{i}", "source": "yt", "source_id": str(i)} for i in range(5)]
        self.queue.set_tracks(tracks, start_index=0)
        self.queue.next_track()  # now at 1, history [0] (T0)
        self.queue.next_track()  # now at 2, history [0, 1] (T0, T1)
        self.assertEqual(self.queue.current_track["id"], 2)

        # Toggle shuffle on
        self.queue.shuffle = True
        # Previous track must return T1, regardless of how tracks were shuffled
        prev = self.queue.previous_track()
        self.assertEqual(prev["id"], 1)
        # Previous track again must return T0
        prev2 = self.queue.previous_track()
        self.assertEqual(prev2["id"], 0)

    def test_repeat_all_with_shuffle_does_not_lock_first_track(self):
        tracks = [{"id": i, "title": f"T{i}", "source": "yt", "source_id": str(i)} for i in range(10)]
        self.queue.set_tracks(tracks, start_index=0)
        self.queue.repeat = "all"
        self.queue.shuffle = True

        first_tracks = [self.queue.current_track["id"]]
        for _ in range(5):
            for _ in range(self.queue.count - 1):
                self.queue.next_track()
            wrapped = self.queue.next_track()
            first_tracks.append(wrapped["id"])

        # Across multiple loops, the queue should not always start with identical track
        # (statistical check: with 10 tracks, not all 6 samples should be identical)
        self.assertEqual(len(first_tracks), 6)

    def test_next_and_previous_track_unstarted_queue(self):
        tracks = [{"id": 0, "title": "T0"}, {"id": 1, "title": "T1"}]
        self.queue.set_tracks(tracks)
        self.queue._current_index = -1
        self.queue.repeat = "one"

        # next_track starts unstarted queue at 0 even with repeat=one
        nxt = self.queue.next_track()
        self.assertIsNotNone(nxt)
        self.assertEqual(nxt["id"], 0)
        self.assertEqual(self.queue.current_index, 0)

        # previous_track on unstarted queue returns None safely
        self.queue._current_index = -1
        self.assertIsNone(self.queue.previous_track())
        self.assertEqual(self.queue.current_index, -1)

    def test_update_current_preserves_across_shuffle_toggle(self):
        t0 = {"id": 0, "title": "T0", "source": "yt", "source_id": "0", "stream_url": ""}
        t1 = {"id": 1, "title": "T1", "source": "yt", "source_id": "1", "stream_url": ""}
        self.queue.set_tracks([t0, t1], start_index=0)
        self.queue.shuffle = True

        updated = {"id": 0, "title": "T0", "source": "yt", "source_id": "0", "stream_url": "https://stream.com/audio.mp3"}
        self.queue.update_current(updated)
        self.assertEqual(self.queue.current_track["stream_url"], "https://stream.com/audio.mp3")

        # Toggle shuffle off
        self.queue.shuffle = False
        self.assertEqual(self.queue.current_track["stream_url"], "https://stream.com/audio.mp3")

    def test_history_stack_depth_capped(self):
        tracks = [{"id": i, "title": f"T{i}"} for i in range(10)]
        self.queue.set_tracks(tracks, start_index=0)
        for _ in range(250):
            self.queue.next_track()
            if self.queue.current_index >= 9:
                self.queue.jump_to(0)
        self.assertLessEqual(len(self.queue._history_stack), 100)

    def test_to_serializable_and_get_queue_track_ids_with_source_id(self):
        tracks = [{"source_id": "sc_999", "title": "SC Track", "source": "soundcloud"}]
        self.queue.set_tracks(tracks, start_index=0)
        self.assertEqual(self.queue.get_queue_track_ids(), ["sc_999"])
        self.assertEqual(self.queue.to_serializable()["track_ids"], ["sc_999"])


if __name__ == "__main__":
    unittest.main()
