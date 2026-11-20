"""WN-05 reviewer A - reproductions, round 3."""
import os
import shutil
import sys
import tempfile
import types

REPO = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main"
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from audio.engine import AudioEngine
from core.api import AppApi
from core.database import DatabaseManager


class SettingsStub:
    def __init__(self):
        self._d = {}

    def get(self, category, key, default=None):
        return self._d.get((category, key), default)

    def set(self, category, key, value):
        self._d[(category, key)] = value

    def get_category(self, category):
        return {k: v for (c, k), v in self._d.items() if c == category}


class _TD(tempfile.TemporaryDirectory):
    def cleanup(self):
        try:
            shutil.rmtree(self.name, ignore_errors=True)
        except Exception:
            pass


def make_api(tmpdir):
    db = DatabaseManager(os.path.join(tmpdir, "t.db"))
    core = types.SimpleNamespace(db=db, settings=SettingsStub(), cache=None, engine=None, proxy=None)
    engine = AudioEngine()
    core.engine = engine
    api = AppApi(core)
    engine._on_track_changed = None
    events = []
    api._emit = lambda name, data=None: events.append((name, data))
    core.re_resolve_stream_url_async = lambda *a, **k: None
    return api, core, engine, events, db


def real_track(db, i):
    tid = db.add_track(title="t%d" % i, artist="a", source="youtube", source_id="s%d" % i)
    return {"id": tid, "title": "t%d" % i, "artist": "a", "source": "youtube", "source_id": "s%d" % i}


def test_O_play_track_returns_none():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        r = api.play_track({"id": 1, "title": "A", "source": "youtube", "source_id": "A"})
        print("O) play_track() returns:", repr(r), " (offline branch returns a dict, online returns None)")


def test_P_play_track_local_missing_no_queue_change():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        tr = {"id": 1, "title": "Gone", "source": "local", "source_id": "g1",
              "file_path": os.path.join(td, "nope.mp3")}
        r = api.play_track(tr, [tr], 0)
        print("P) play_track(local missing) ->", repr(r), " events:", [e[0] for e in events],
              " queue count:", engine.queue.count)


def test_Q_on_audio_error_emits_two_events():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        api._on_audio_error("boom")
        print("Q) _on_audio_error -> events:", [(e[0], e[1]) for e in events])


def test_R_emit_off_ui_thread():
    """Does _on_audio_error / report_state call _emit from the calling thread only?"""
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        threads = set()

        def cap(name, data=None):
            threads.add(threading.current_thread().name)
        api._emit = cap
        api._on_audio_error("boom")
        api.report_state("playing", 0)
        print("R) emit threads:", threads)


def test_S_reorder_current_index_tracking():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        tracks = [{"id": i, "title": "t%d" % i, "source": "youtube", "source_id": "s%d" % i} for i in range(4)]
        api.play_track(dict(tracks[0]), [dict(t) for t in tracks], 0)
        api.play_track(dict(tracks[1]), [dict(t) for t in tracks], 1)
        print("S) before: idx=%s current=%s" % (engine.queue.current_index,
                                                engine.queue.current_track["title"]))
        api.reorder_queue(1, 0)   # move current (idx1) to front
        print("   after reorder_queue(1,0): idx=%s current=%s order=%s" % (
            engine.queue.current_index, engine.queue.current_track["title"],
            [t["title"] for t in engine.queue.tracks]))


def test_T_remove_before_current():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        tracks = [{"id": i, "title": "t%d" % i, "source": "youtube", "source_id": "s%d" % i} for i in range(4)]
        api.play_track(dict(tracks[2]), [dict(t) for t in tracks], 2)
        print("T) start idx=%s current=%s" % (engine.queue.current_index, engine.queue.current_track["title"]))
        print("   remove_from_queue(0) ->", api.remove_from_queue(0))
        print("   after: idx=%s current=%s" % (engine.queue.current_index, engine.queue.current_track["title"]))
        print("   remove_from_queue(current) ->", api.remove_from_queue(engine.queue.current_index))


def test_U_clear_queue_keeps_current():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        tracks = [{"id": i, "title": "t%d" % i, "source": "youtube", "source_id": "s%d" % i} for i in range(4)]
        api.play_track(dict(tracks[2]), [dict(t) for t in tracks], 2)
        print("U) before clear: count=%s idx=%s current=%s" % (
            engine.queue.count, engine.queue.current_index, engine.queue.current_track["title"]))
        print("   clear_queue ->", api.clear_queue())
        print("   after clear: count=%s idx=%s current=%s" % (
            engine.queue.count, engine.queue.current_index,
            (engine.queue.current_track or {}).get("title")))


def test_V_play_next_when_no_current():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        tr = real_track(db, 1)
        print("V) play_next on empty queue ->", api.play_next(tr))
        print("   queue:", [t["title"] for t in engine.queue.tracks], "idx:", engine.queue.current_index)


def test_W_get_queue_payload_shape():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        tr = real_track(db, 1)
        api.play_track(tr, [tr], 0)
        q = api.get_queue()
        print("W) get_queue keys:", sorted(q.keys()))
        print("   shuffle=%r repeat=%r current_index=%r" % (q["shuffle"], q["repeat"], q["current_index"]))
        print("   current_track is queue.current_track:", q["current_track"] is engine.queue.current_track)


def test_X_report_state_playing_logs_history_once_per_session():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        tr = real_track(db, 1)
        api._on_track_changed(tr)
        tok = api._current_track.get("listening_session")
        for _ in range(5):
            api.report_state("playing", 0, tok)
        rows = db.conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
        pc = db.conn.execute("SELECT play_count FROM tracks WHERE id=?", (tr["id"],)).fetchone()[0]
        print("X) 5x report_state('playing') -> history rows=%s play_count=%s" % (rows, pc))
        assert rows == 1 and pc == 1


def test_Y_listening_identity_same_title_diff_source():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        t1 = {"id": 1, "title": "Song", "artist": "A", "source": "youtube", "source_id": "1"}
        t2 = {"id": 2, "title": "Song", "artist": "A", "source": "soundcloud", "source_id": "1"}
        api._on_track_changed(t1)
        s1 = api._active_listening_token
        api._on_track_changed(t2)
        s2 = api._active_listening_token
        print("Y) same title/artist, different source -> same session?", s1 == s2)
        assert s1 != s2
        t3 = {"id": 3, "title": "Song", "artist": "A", "source": "youtube", "source_id": "1"}
        api._on_track_changed(t3)
        s3 = api._active_listening_token
        print("   same source+source_id re-notified -> same session?", s3 == s2)
    print("   OK")


def test_Z_report_position_negative_and_jumps():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        tr = real_track(db, 1)
        api._on_track_changed(tr)
        tok = api._current_track.get("listening_session")
        api.report_state("playing", 0, tok)
        api.report_listening_state(tok, True, False, 100.0, 1.0)
        api.report_position(-5000, 100000)
        api.report_position(10 ** 12, 100000)
        s = api._listening_sessions[tok]
        print("Z) seconds after negative/huge positions:", s.seconds)
        print("   engine._last_reported_position:", engine._last_reported_position)


import threading  # noqa: E402

if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        print("=" * 70)
        print("RUN", fn.__name__)
        try:
            fn()
        except AssertionError as e:
            print("ASSERTION FAILED:", e)
        except Exception as e:
            import traceback
            print("EXCEPTION:", type(e).__name__, e)
            traceback.print_exc()
