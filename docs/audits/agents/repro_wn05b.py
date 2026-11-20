"""WN-05 reviewer A - reproductions, round 2. Read-only against the repo."""
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
    core.re_resolve_stream_url_async = lambda *a, **k: None
    return api, core, engine, events, db


def real_track(db, i):
    tid = db.add_track(title="t%d" % i, artist="a", source="youtube", source_id="s%d" % i)
    return {"id": tid, "title": "t%d" % i, "artist": "a", "source": "youtube", "source_id": "s%d" % i}


def test_A_stale_resolution_race_solo():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        pending = []
        core.re_resolve_stream_url_async = (
            lambda source, source_id, callback=None, on_error=None, track=None, quality="high":
            pending.append((source_id, callback, on_error)))
        A = {"id": 1, "title": "A", "artist": "x", "source": "youtube", "source_id": "A"}
        B = {"id": 2, "title": "B", "artist": "x", "source": "youtube", "source_id": "B"}
        api.play_track(dict(A))
        api.play_track(dict(B))
        pending[0][1]("https://cdn.test/A.m4a")   # A resolves first
        pending[1][1]("https://cdn.test/B.m4a")   # B resolves later
        cur = engine.queue.current_track or {}
        print("A) solo race -> queue current source_id =", cur.get("source_id"))
        print("   audio_error emitted:", [e[0] for e in events if e[0] == "audio_error"])
        assert cur.get("source_id") == "B", "expected B, got %r" % cur.get("source_id")
    print("   OK")


def test_B_stale_resolution_race_list_then_solo():
    """list click for A, then solo click for B (the player.js:1704 pattern)."""
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        pending = []
        core.re_resolve_stream_url_async = (
            lambda source, source_id, callback=None, on_error=None, track=None, quality="high":
            pending.append((source_id, callback, on_error, track)))
        A = {"id": 1, "title": "A", "artist": "x", "source": "youtube", "source_id": "A"}
        B = {"id": 2, "title": "B", "artist": "x", "source": "youtube", "source_id": "B"}
        api.play_track(dict(A), [dict(A)], 0)       # list click for A
        api.play_track(dict(B))                     # solo click for B
        print("B) pending:", [(p[0], p[3].get("title") if p[3] else None) for p in pending])
        for p in pending:
            p[1]("https://cdn.test/%s.m4a" % p[0])
        cur = engine.queue.current_track or {}
        print("   queue current source_id =", cur.get("source_id"))
        assert cur.get("source_id") == "B", "expected B, got %r" % cur.get("source_id")
    print("   OK")


def test_C_reorder_out_of_range():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        tracks = [{"id": i, "title": "t%d" % i, "source": "youtube", "source_id": "s%d" % i} for i in range(3)]
        api.play_track(dict(tracks[0]), [dict(t) for t in tracks], 0)
        before = [t["id"] for t in engine.queue.tracks]
        api.reorder_queue(0, 3)
        after = [t["id"] for t in engine.queue.tracks]
        print("C) reorder_queue(0, 3): before=%s after=%s  (no error, no change)" % (before, after))
        try:
            api.reorder_queue("0", 1)
            print("   reorder_queue('0', 1) -> no exception")
        except Exception as e:
            print("   reorder_queue('0', 1) raised %s: %s" % (type(e).__name__, e))
        try:
            api.reorder_queue(0, 1.0)
            print("   reorder_queue(0, 1.0) -> no exception")
        except Exception as e:
            print("   reorder_queue(0, 1.0) raised %s: %s" % (type(e).__name__, e))


def test_D_volume_no_clamp():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        for v in (500, -20, "abc", 150):
            api.set_volume(v)
            print("D) set_volume(%r) -> get_volume() = %r" % (v, api.get_volume()))


def test_E_set_setting_bare_key_goes_to_zapret():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        print("E) set_setting('autostart', True) ->", api.set_setting("autostart", True))
        print("   core.settings.get('zapret','autostart') =", core.settings.get("zapret", "autostart"))
        print("   core.settings.get('general','autostart') =", core.settings.get("general", "autostart"))
        print("   get_setting('autostart') ->", repr(api.get_setting("autostart", "MISSING")))
        print("   set_setting('general.autostart', True) ->", api.set_setting("general.autostart", True))
        print("   core.settings.get('general','autostart') =", core.settings.get("general", "autostart"))
        print("   save_setting('autostart', True, 'general') ->", api.save_setting("autostart", True, "general"))


def test_F_get_next_track_at_end():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        tracks = [{"id": i, "title": "t%d" % i, "source": "youtube", "source_id": "s%d" % i} for i in range(2)]
        api.play_track(dict(tracks[0]), [dict(t) for t in tracks], 0)
        engine.queue._current_index = 1
        print("F) get_next_track at end (repeat off):", api.get_next_track())
        engine.queue.repeat = "all"
        print("   get_next_track at end (repeat all):", (api.get_next_track() or {}).get("title"))
        engine.queue.repeat = "one"
        print("   get_next_track (repeat one):", (api.get_next_track() or {}).get("title"))
        print("   toggle_repeat ->", api.toggle_repeat(), api.toggle_repeat(), api.toggle_repeat())


def test_G_listening_history_count():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        tr = real_track(db, 1)
        api._on_track_changed(tr)
        tok = api._current_track.get("listening_session")
        api.report_state("playing", 0, tok)
        api.report_listening_state(tok, True, False, 100.0, 1.0)
        for _ in range(5):
            api.report_position(1000, 100000)
        rows = db.conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
        pc = db.conn.execute("SELECT play_count FROM tracks WHERE id=?", (tr["id"],)).fetchone()[0]
        print("G) history rows=%s play_count=%s (1 track, 1 play)" % (rows, pc))
        assert rows == 1, rows
        assert pc == 1, pc
    print("   OK")


def test_H_listening_session_eviction():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        for i in range(40):
            tr = real_track(db, i)
            api._on_track_changed(tr)
            tok = api._current_track.get("listening_session")
            api.report_state("playing", 0, tok)
            api.report_listening_state(tok, True, False, 100.0, 1.0)
            for _ in range(3):
                api.report_position(1000, 100000)
        print("H) sessions kept:", len(api._listening_sessions))
        rows = db.conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
        print("   history rows:", rows)
        api.flush_listening()
        rows2 = db.conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
        durs = db.conn.execute("SELECT COUNT(*) FROM history WHERE session_finished=1").fetchone()[0]
        print("   history rows after flush:", rows2, " session_finished=1:", durs)
        assert durs == rows, "some history rows were never closed (evicted session)"


def test_I_stale_token_rejected():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        tr = real_track(db, 1)
        api._on_track_changed(tr)
        tok = api._current_track.get("listening_session")
        api.report_state("playing", 0, tok)
        api.report_listening_state(tok, True, False, 100.0, 1.0)
        before = api._listening_sessions[tok].seconds
        r = api.report_position(1000, 100000, 0, "deadbeef")
        print("I) report_position with stale token ->", r, " seconds unchanged:",
              api._listening_sessions[tok].seconds == before)
        r2 = api.report_state("playing", 0, "deadbeef")
        print("   report_state with stale token ->", r2)


def test_J_add_to_queue_non_dict_and_count():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        print("J) add_to_queue(None) ->", api.add_to_queue(None))
        print("   queue:", engine.queue.tracks, "current:", engine.queue.current_track)
        print("   add_tracks_to_queue([1,2,'x']) ->", api.add_tracks_to_queue([1, 2, "x"]))
        print("   queue:", engine.queue.tracks)


def test_K_next_track_empty_queue():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        api.next_track()
        print("K) next_track() on empty queue -> events:", [e[0] for e in events])
        api.prev_track()
        print("   prev_track() -> events:", [e[0] for e in events])


def test_L_queue_ended_on_repeat_one():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        tracks = [{"id": i, "title": "t%d" % i, "source": "youtube", "source_id": "s%d" % i} for i in range(2)]
        api.play_track(dict(tracks[0]), [dict(t) for t in tracks], 0)
        engine.queue.repeat = "one"
        api.next_track()
        print("L) next_track() with repeat=one -> events:", [e[0] for e in events])


def test_M_audio_error_then_queue_continues():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        pending = []
        core.re_resolve_stream_url_async = (
            lambda source, source_id, callback=None, on_error=None, track=None, quality="high":
            pending.append((source_id, callback, on_error)))
        A = {"id": 1, "title": "A", "artist": "x", "source": "youtube", "source_id": "A"}
        api.play_track(dict(A), [dict(A)], 0)
        pending[0][2]("boom")
        print("M) after resolve error -> events:", [e[0] for e in events])
        print("   queue count:", engine.queue.count, "current:", engine.queue.current_track)


def test_N_yandex_device_auth_double_start():
    with _TD() as td:
        api, core, engine, events, db = make_api(td)
        calls = []

        class FakeClient:
            def device_auth(self, on_code=None, timeout=None):
                calls.append((on_code, timeout))
                return None

        class FakeYandex:
            def _get_client(self):
                return FakeClient()

            def reset_client(self):
                pass

        core.yandex = FakeYandex()
        import sys as _s
        mod = types.ModuleType("yandex_music")
        mod.Client = FakeClient
        _s.modules["yandex_music"] = mod
        r1 = api.yandex_device_auth()
        r2 = api.yandex_device_auth()
        import time as _t
        _t.sleep(0.3)
        print("N) yandex_device_auth x2 ->", r1, r2, " device_auth calls:", len(calls))
        print("   events:", [e[0] for e in events])


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
