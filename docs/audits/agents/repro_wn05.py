"""WN-05 reviewer A - reproductions. Read-only against the repo."""
import os
import sys
import types

REPO = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main"
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from audio.engine import AudioEngine
from core.api import AppApi
from core.database import DatabaseManager

import tempfile


class SettingsStub:
    def __init__(self):
        self._d = {}

    def get(self, category, key, default=None):
        return self._d.get((category, key), default)

    def set(self, category, key, value):
        self._d[(category, key)] = value

    def get_category(self, category):
        return {k: v for (c, k), v in self._d.items() if c == category}


def make_api(tmpdir):
    db = DatabaseManager(os.path.join(tmpdir, "t.db"))
    core = types.SimpleNamespace(
        db=db,
        settings=SettingsStub(),
        cache=None,
        engine=None,
        proxy=None,
    )
    engine = AudioEngine()
    core.engine = engine
    api = AppApi(core)
    engine._on_track_changed = None
    events = []
    api._emit = lambda name, data=None: events.append((name, data))
    return api, core, engine, events, db


class _TD(tempfile.TemporaryDirectory):
    def __enter__(self):
        self._td = super().__enter__()
        return self._td

    def cleanup(self):
        import shutil
        try:
            shutil.rmtree(self.name, ignore_errors=True)
        except Exception:
            pass


def test_race_solo_play_track_old_wins():
    """Two SOLO play_track calls; the FIRST to resolve must not win."""
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        pending = []

        def fake_async(source, source_id, callback=None, on_error=None, track=None, quality="high"):
            pending.append((source_id, callback, on_error))

        core.re_resolve_stream_url_async = fake_async

        A = {"id": 1, "title": "A", "artist": "x", "source": "youtube", "source_id": "A"}
        B = {"id": 2, "title": "B", "artist": "x", "source": "youtube", "source_id": "B"}

        api.play_track(dict(A))       # user clicks A
        api.play_track(dict(B))       # user clicks B  (most recent intent)

        print("pending resolutions:", [p[0] for p in pending])
        # resolve A first (A's provider was faster)
        pending[0][1]("https://cdn.test/A.m4a")
        print("after A resolved -> queue:", engine.queue.tracks,
              "current:", (engine.queue.current_track or {}).get("source_id"))
        pending[1][1]("https://cdn.test/B.m4a")
        print("after B resolved -> queue:", engine.queue.tracks,
              "current:", (engine.queue.current_track or {}).get("source_id"))
        cur = engine.queue.current_track or {}
        print("RESULT current source_id =", cur.get("source_id"))
        assert cur.get("source_id") == "B", (
            "STALE RACE CONFIRMED: expected B (latest click) but queue holds %r" % cur.get("source_id"))
        print("OK: latest click wins")


def test_race_with_track_list():
    """Same race but through the list path - is it protected?"""
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        pending = []
        core.re_resolve_stream_url_async = lambda source, source_id, callback=None, on_error=None, track=None, quality="high": pending.append((source_id, callback, on_error))

        A = {"id": 1, "title": "A", "artist": "x", "source": "youtube", "source_id": "A"}
        B = {"id": 2, "title": "B", "artist": "x", "source": "youtube", "source_id": "B"}
        api.play_track(dict(A), [dict(A)], 0)
        api.play_track(dict(B), [dict(B)], 0)
        pending[0][1]("https://cdn.test/A.m4a")
        cur = engine.queue.current_track or {}
        print("list path -> current source_id =", cur.get("source_id"))
        assert cur.get("source_id") == "B"
        print("OK list path protected")


def test_reorder_out_of_range():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        tracks = [{"id": i, "title": "t%d" % i, "source": "youtube", "source_id": "s%d" % i} for i in range(3)]
        api.play_track(dict(tracks[0]), [dict(t) for t in tracks], 0)
        before = [t["id"] for t in engine.queue.tracks]
        api.reorder_queue(0, 3)   # new_index == len(tracks) -> "move to end"
        after = [t["id"] for t in engine.queue.tracks]
        print("reorder_queue(0,3) before=%s after=%s (no error raised)" % (before, after))
        api.reorder_queue("0", 1)
        print("reorder_queue('0',1) did not raise")


def test_volume_clamp():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        api.set_volume(500)
        print("set_volume(500) -> get_volume() =", api.get_volume())
        api.set_volume(-20)
        print("set_volume(-20) -> get_volume() =", api.get_volume())
        api.set_volume("abc")
        print("set_volume('abc') -> get_volume() =", api.get_volume())


def test_mute_volume_restore():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        api.set_volume(42)
        print("mute ->", api.toggle_mute(), "volume still", api.get_volume())
        print("unmute ->", api.toggle_mute(), "volume still", api.get_volume())


def test_next_track_empty_queue_emits_queue_ended():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        api.next_track()
        print("events after next_track on empty queue:", [e[0] for e in events])


def test_listening_session_eviction():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        # create 40 distinct sessions, each with a history row
        for i in range(40):
            tr = {"id": 1000 + i, "title": "t%d" % i, "artist": "a", "source": "youtube", "source_id": "s%d" % i}
            api._on_track_changed(tr)
            api.report_state("playing", 0, api._current_track.get("listening_session"))
        print("sessions kept:", len(api._listening_sessions))
        rows = db.conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
        print("history rows:", rows)
        # the earliest session was evicted without being closed/persisted
        api.flush_listening()
        rows2 = db.conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
        print("history rows after flush:", rows2)
        durs = db.conn.execute("SELECT duration_listened FROM history ORDER BY id").fetchall()
        print("durations:", [d[0] for d in durs][:5])


def test_report_position_double_count():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        tr = {"id": 7, "title": "t", "artist": "a", "source": "youtube", "source_id": "s7"}
        api._on_track_changed(tr)
        tok = api._current_track.get("listening_session")
        api.report_state("playing", 0, tok)
        api.report_listening_state(tok, True, False, 100.0, 1.0)
        for _ in range(5):
            api.report_position(1000, 100000)
        sess = api._listening_sessions.get(tok)
        print("session seconds:", sess.seconds, "media:", sess.media_seconds,
              "history rows:", db.conn.execute("SELECT COUNT(*) FROM history").fetchone()[0])
        rows = db.conn.execute("SELECT duration_listened, media_listened FROM history").fetchall()
        print("history:", rows)


def test_paused_counts_time():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        tr = {"id": 8, "title": "t", "artist": "a", "source": "youtube", "source_id": "s8"}
        api._on_track_changed(tr)
        tok = api._current_track.get("listening_session")
        api.report_state("playing", 0, tok)
        api.report_listening_state(tok, True, False, 100.0, 1.0)
        api.report_state("paused", 0, tok)
        for _ in range(3):
            api.report_position(1000, 100000)
        sess = api._listening_sessions.get(tok)
        print("paused session seconds (should not grow while paused):", sess.seconds)


def test_remove_current_and_clear():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        tracks = [{"id": i, "title": "t%d" % i, "source": "youtube", "source_id": "s%d" % i} for i in range(3)]
        api.play_track(dict(tracks[0]), [dict(t) for t in tracks], 0)
        print("remove current:", api.remove_from_queue(0))
        print("remove negative:", api.remove_from_queue(-1))
        print("remove oob:", api.remove_from_queue(99))
        print("remove non-int:", api.remove_from_queue("x"))
        print("clear:", api.clear_queue(), "queue:", engine.queue.tracks,
              "current:", engine.queue.current_track)


def test_add_to_queue_non_dict():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        print("add_to_queue(None):", api.add_to_queue(None))
        print("queue:", engine.queue.tracks, "current:", engine.queue.current_track)


def test_get_setting_secret():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        core.settings.set("auth", "yandex_token", "SECRET")
        print("get_setting('auth.yandex_token') =", repr(api.get_setting("auth.yandex_token")))
        print("get_setting('audio.volume') =", api.get_setting("audio.volume", 70))


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
