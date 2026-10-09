"""core/database.py, core/settings.py and core/app.py fixes (agent F2).

Covers:
  * H1  download_queue_add re-arms a failed/cancelled row instead of leaving
       the track permanently unqueueable - and still refuses to disturb a row
       that is queued, downloading or completed.
  * M7/M11 close() checkpoints the WAL and logs a connection it cannot close
       instead of swallowing the ProgrammingError.
  * M8  create_playlist_ex tells the caller whether the playlist is new, so an
       import rollback can only undo what it created.
  * M9  listening history counts every play. Dedup lives in AppApi under
       _window_op_lock; the persistent claim that used to live here made each
       track count as played exactly once for the lifetime of the library.
  * LIKE wildcards are literal (user-supplied % and _ used to match anything).
  * set_settings_batch reports how many keys landed, and a short flush keeps
       its keys pending instead of pretending to have succeeded.
  * L2/L3 settings defaults are not shared objects, and the gapless /
       accent_color properties agree with DEFAULT_SETTINGS.
  * L4  zapret autostart cannot start a process after cleanup() stopped zapret.

Every test runs against a throwaway SQLite file; nothing here touches the real
~/.nedotify tree.
"""

import threading
import types

import pytest

from core.app import AppCore
from core.database import DatabaseManager
from core.settings import DEFAULT_SETTINGS, SettingsManager


def _no_fts(db):
    """Force the LIKE fallback path (FTS would answer some queries first)."""
    db._fts_available = False
    return db


# --- H1: download_queue_add ---------------------------------------------------

def test_queue_row_survives_a_re_add(tmp_db):
    """Pre-fix the row was neither deleted nor reset; the caller just saw False."""
    assert tmp_db.download_queue_add(1, "youtube", "v1") is True
    tmp_db.download_queue_set_status(1, "completed")

    assert tmp_db.download_queue_add(1, "youtube", "v1") is False
    assert tmp_db.download_queue_get_status(1) == "completed"


@pytest.mark.parametrize("terminal", ["failed", "cancelled"])
def test_terminal_row_is_rearmed(tmp_db, terminal):
    """A failed/cancelled download can be retried: same row, back to pending."""
    tmp_db.download_queue_add(2, "youtube", "v2")
    tmp_db.download_queue_set_status(2, terminal)

    assert tmp_db.download_queue_add(2, "youtube", "v2") is True
    assert tmp_db.download_queue_get_status(2) == "pending"

    rows = tmp_db.conn.execute(
        "SELECT COUNT(*) FROM download_queue WHERE track_id = 2"
    ).fetchone()[0]
    assert rows == 1, "the retry inserted a second row instead of re-arming one"


@pytest.mark.parametrize("live", ["pending", "downloading"])
def test_live_row_is_not_rearmed(tmp_db, live):
    """A double click must not start a second download of the same track."""
    tmp_db.download_queue_add(3, "youtube", "v3")
    tmp_db.download_queue_set_status(3, live)

    assert tmp_db.download_queue_add(3, "youtube", "v3") is False
    assert tmp_db.download_queue_get_status(3) == live


def test_rearm_then_claim_is_still_unique(tmp_db):
    """The unique index is still the arbiter: one row per track, no matter what."""
    tmp_db.download_queue_add(4, "youtube", "v4")
    tmp_db.download_queue_set_status(4, "failed")
    tmp_db.download_queue_add(4, "youtube", "v4")
    assert tmp_db.download_queue_add(4, "youtube", "v4") is False
    assert tmp_db.conn.execute("SELECT COUNT(*) FROM download_queue").fetchone()[0] == 1


# --- M7/M11: close() ----------------------------------------------------------

def _foreign_connection(db):
    """Open a connection owned by another thread and keep it alive.

    That connection is what makes close() interesting: it cannot be closed from
    this thread (sqlite3 raises ProgrammingError) and it keeps the -wal file
    from being deleted on close.
    """
    opened = threading.Event()
    keep = threading.Event()

    def worker():
        db.get_all_settings()
        opened.set()
        keep.wait(10)

    thread = threading.Thread(target=worker, name="ForeignConn", daemon=True)
    thread.start()
    assert opened.wait(5), "worker thread never opened its connection"
    return keep, thread


def test_close_checkpoints_the_wal(tmp_path):
    """close() folds the WAL back into the database file before it goes away."""
    path = str(tmp_path / "wal.db")
    db = DatabaseManager(path)
    db.set_setting("a.b", 1, "general")
    keep, thread = _foreign_connection(db)
    db.set_setting("a.c", 2, "general")

    db.close()

    wal = tmp_path / "wal.db-wal"
    assert wal.exists(), "the -wal file was removed: the checkpoint never ran"
    assert wal.stat().st_size == 0, (
        f"-wal still holds {wal.stat().st_size} bytes after close(): "
        "the WAL was not checkpointed"
    )

    keep.set()
    thread.join(5)

    reopened = DatabaseManager(path)
    try:
        assert reopened.get_setting("a.c") == 2
    finally:
        reopened.close()


def test_close_logs_an_unclosable_connection(tmp_path, caplog):
    """A foreign-thread handle raises ProgrammingError; it must be visible.

    Reported as ONE summary line: a long-running session can hold hundreds of
    these, and a warning per connection flooded app.log on every shutdown.
    """
    path = str(tmp_path / "foreign.db")
    db = DatabaseManager(path)
    db.set_setting("a.b", 1, "general")
    keep, thread = _foreign_connection(db)

    with caplog.at_level("WARNING"):
        db.close()
    close_logs = [r.message for r in caplog.records if "could not be closed" in r.message]
    assert close_logs, [r.message for r in caplog.records]
    assert len(close_logs) == 1, f"expected one summary line, got {len(close_logs)}"
    assert "1 database connection(s)" in close_logs[0]

    keep.set()
    thread.join(5)
    db.close()


def test_close_on_memory_db_is_harmless(tmp_path):
    """No WAL exists for :memory:; the pragma must not turn that into an error."""
    db = DatabaseManager(":memory:")
    db.get_all_settings()
    db.close()
    db.close()  # repeatable


# --- M8: create_playlist_ex ---------------------------------------------------

def test_create_playlist_ex_reports_a_new_playlist(tmp_db):
    pid, created = tmp_db.create_playlist_ex("Новая подборка")
    assert created is True
    assert isinstance(pid, int)
    assert pid in {p["id"] for p in tmp_db.get_playlists()}


def test_create_playlist_ex_reports_a_reused_playlist(tmp_db):
    # ASCII on purpose: SQLite's LOWER() is ASCII-only, so a Cyrillic name is
    # never folded ("ОБЩАЯ" and "общая" stay distinct). Pre-existing, unrelated
    # to created-vs-reused; see the handoff note.
    pid, created = tmp_db.create_playlist_ex("Shared")
    assert created is True
    again_pid, again_created = tmp_db.create_playlist_ex("SHARED")  # case-insensitive
    assert again_created is False
    assert again_pid == pid


def test_create_playlist_still_returns_only_the_id(tmp_db):
    """Back-compat: the old signature and return type are unchanged."""
    pid = tmp_db.create_playlist("Совместимость", "desc")
    assert isinstance(pid, int)
    assert tmp_db.create_playlist("Совместимость", "other") == pid
    # The description of a pre-existing playlist is not overwritten.
    rows = tmp_db.conn.execute(
        "SELECT description FROM playlists WHERE id = ?", (pid,)
    ).fetchone()
    assert rows[0] == "desc"


def test_create_playlist_ex_is_thread_safe(tmp_db):
    """Concurrent creators agree on one id and exactly one of them created it."""
    results = []
    lock = threading.Lock()

    def worker():
        pid, created = tmp_db.create_playlist_ex("Гонка")
        with lock:
            results.append((pid, created))

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    ids = {pid for pid, _ in results}
    assert len(ids) == 1, f"callers disagreed about the id: {ids}"
    assert sum(1 for _, created in results if created) == 1


# --- M9: listening history ----------------------------------------------------

def _history_rows(db, track_id):
    return db.conn.execute(
        "SELECT COUNT(*) FROM history WHERE track_id = ?", (track_id,)
    ).fetchone()[0]


def test_log_listening_history_counts_every_call(tmp_db):
    """Every call is a real play. Dedup is the caller's business
    (AppApi._history_logged_key), not something the database may swallow: a
    persistent per-key claim made each track count once for the whole library."""
    tid = tmp_db.add_track(title="Song", artist="A", source="youtube", source_id="m1")
    tmp_db.update_track(tid, duration=210.0)

    for _ in range(3):
        tmp_db.log_listening_history(tid)

    assert _history_rows(tmp_db, tid) == 3
    assert tmp_db.get_track(tid)["play_count"] == 3


def test_log_listening_history_falls_back_to_the_track_duration(tmp_db):
    tid = tmp_db.add_track(title="Song", artist="A", source="youtube", source_id="m2")
    tmp_db.update_track(tid, duration=210.0)

    tmp_db.log_listening_history(tid, duration_listened=0)

    row = tmp_db.conn.execute(
        "SELECT duration_listened FROM history WHERE track_id = ?", (tid,)
    ).fetchone()
    assert row[0] == 210.0


def test_log_listening_history_records_an_honest_zero_for_unknown_length(tmp_db):
    """A track with no known duration must store 0, not a fabricated 180 s."""
    tid = tmp_db.add_track(title="Song", artist="A", source="youtube", source_id="m3")

    tmp_db.log_listening_history(tid, duration_listened=0)

    row = tmp_db.conn.execute(
        "SELECT duration_listened FROM history WHERE track_id = ?", (tid,)
    ).fetchone()
    assert row[0] == 0


def test_listening_history_does_not_touch_the_settings_table(tmp_db):
    """Regression: the removed dedup claim wrote one settings row per play."""
    from core.settings import SettingsManager as SM

    tid = tmp_db.add_track(title="Song", artist="A", source="youtube", source_id="m6")
    for _ in range(4):
        tmp_db.log_listening_history(tid)

    keys = [r[0] for r in tmp_db.conn.execute("SELECT key FROM settings").fetchall()]
    assert not [k for k in keys if "listen" in str(k).lower()]

    sm = SM(tmp_db)
    assert not [c for c in sm._cache if str(c).startswith("listen_dedup")]
    assert sm.sync_flush_now() is True


# --- LIKE escaping ------------------------------------------------------------

def test_percent_is_a_literal_in_search_tracks(tmp_db):
    _no_fts(tmp_db)
    tmp_db.add_track(title="100% Pure Love", artist="A", source="local", source_id="l1")
    tmp_db.add_track(title="Ordinary Track", artist="A", source="local", source_id="l2")

    found = {t["title"] for t in tmp_db.search_tracks("%")}
    assert found == {"100% Pure Love"}, (
        "'%' matched every row: the user still owns the wildcard"
    )
    assert {t["title"] for t in tmp_db.search_tracks("100%")} == {"100% Pure Love"}


def test_underscore_is_a_literal_in_search_tracks(tmp_db):
    _no_fts(tmp_db)
    keep = tmp_db.add_track(title="AC_DC", artist="X", source="local", source_id="l3")
    tmp_db.add_track(title="ACDC Tribute", artist="X", source="local", source_id="l4")

    found = {t["id"] for t in tmp_db.search_tracks("AC_D")}
    assert found == {keep}, "'_' acted as a single-character wildcard"


def test_underscore_is_a_literal_in_search_artists(tmp_db):
    _no_fts(tmp_db)
    tmp_db.add_track(title="T", artist="A_B", source="local", source_id="l5")
    tmp_db.add_track(title="T2", artist="AXB", source="local", source_id="l6")

    artists = {a["artist"] for a in tmp_db.search_artists("A_B")}
    assert artists == {"A_B"}


def test_underscore_is_a_literal_in_search_albums(tmp_db):
    _no_fts(tmp_db)
    tmp_db.add_track(title="T", artist="A", album="Back_In_Black",
                     source="local", source_id="l7")
    tmp_db.add_track(title="T2", artist="A", album="Back In Black",
                     source="local", source_id="l8")

    albums = {a["title"] for a in tmp_db.search_albums("Back_In")}
    assert albums == {"Back_In_Black"}


def test_underscore_is_a_literal_in_search_playlists(tmp_db):
    _no_fts(tmp_db)
    keep = tmp_db.create_playlist("Rock_N_Roll")
    tmp_db.create_playlist("Rock N Roll")

    found = {p["id"] for p in tmp_db.search_playlists("Rock_N")}
    assert found == {keep}


def test_plain_search_still_works(tmp_db):
    """Escaping must not break ordinary substring queries."""
    _no_fts(tmp_db)
    tid = tmp_db.add_track(title="Midnight City", artist="M83",
                           source="local", source_id="l9")
    assert {t["id"] for t in tmp_db.search_tracks("midnight")} == {tid}
    assert {a["artist"] for a in tmp_db.search_artists("m83")} == {"M83"}
    assert tmp_db.search_albums("midnight") == []
    pid = tmp_db.create_playlist("Rock Collection")
    assert {p["id"] for p in tmp_db.search_playlists("Collection")} == {pid}


# --- set_settings_batch -------------------------------------------------------

def test_set_settings_batch_reports_the_written_count(tmp_db):
    assert tmp_db.set_settings_batch(
        [("audio.volume", 42, "audio"), ("theme.name", "Dark", "theme")]
    ) == 2
    assert tmp_db.get_setting("audio.volume") == 42


def test_set_settings_batch_reports_zero_on_failure(tmp_db, caplog):
    """A failed batch must be reported, not swallowed as a silent success."""
    def boom(value):
        raise RuntimeError("serializer refused the value")

    tmp_db._serialize_setting = boom
    with caplog.at_level("ERROR"):
        assert tmp_db.set_settings_batch([("audio.volume", 1, "audio")]) == 0
    assert any("set_settings_batch" in r.message for r in caplog.records)
    assert tmp_db.get_setting("audio.volume") is None


def test_set_settings_batch_of_nothing_is_zero(tmp_db):
    assert tmp_db.set_settings_batch([]) == 0


# --- settings flush -----------------------------------------------------------

class _StubDb:
    """Reports a short write without raising (what the real batch writer does)."""

    def __init__(self, written):
        self._written = written
        self.calls = 0

    def get_all_settings(self):
        return {}

    def set_settings_batch(self, items):
        self.calls += 1
        return self._written


class _RaisingDb(_StubDb):
    def set_settings_batch(self, items):
        self.calls += 1
        raise RuntimeError("db gone")


def test_short_write_keeps_the_keys_pending():
    sm = SettingsManager(_StubDb(0))
    sm.set("audio", "volume", 11)

    assert sm.sync_flush_now() is False
    assert ("audio", "volume") in sm._dirty, "a failed write was reported as a success"


def test_short_write_is_retried_and_succeeds():
    db = _StubDb(0)
    sm = SettingsManager(db)
    sm.set("audio", "volume", 11)
    assert sm.sync_flush_now() is False

    db._written = 1
    assert sm.sync_flush_now() is True
    assert sm._dirty == set()


def test_raising_batch_writer_still_restores_the_keys():
    sm = SettingsManager(_RaisingDb(0))
    sm.set("audio", "volume", 11)
    assert sm.sync_flush_now() is False
    assert ("audio", "volume") in sm._dirty


def test_batch_writer_without_a_count_is_not_treated_as_a_failure():
    """An older shim returns None; that is 'unknown', not 'failed'."""

    class _NoneDb(_StubDb):
        def set_settings_batch(self, items):
            self.calls += 1
            return None

    sm = SettingsManager(_NoneDb(None))
    sm.set("audio", "volume", 11)
    assert sm.sync_flush_now() is True


def test_full_write_clears_pending():
    sm = SettingsManager(_StubDb(2))
    sm.set("audio", "volume", 11)
    sm.set("theme", "name", "Dark")
    assert sm.sync_flush_now() is True
    assert sm._dirty == set()


# --- L2: defaults are not shared mutable objects ------------------------------

def test_mutable_defaults_are_not_shared(tmp_db):
    sm = SettingsManager(tmp_db)
    folders = sm.get("storage", "scan_folders")
    assert isinstance(folders, list)
    folders.append("C:/music")

    assert DEFAULT_SETTINGS["storage"]["scan_folders"] == [], (
        "the cache handed out the DEFAULT_SETTINGS list itself"
    )
    assert SettingsManager(tmp_db).get("storage", "scan_folders") == []


def test_reset_category_copies_the_defaults(tmp_db):
    sm = SettingsManager(tmp_db)
    sm.set("personalization", "favorite_genres", ["metal"])

    sm.reset_category("personalization")

    genres = sm.get("personalization", "favorite_genres")
    genres.append("rock")
    assert DEFAULT_SETTINGS["personalization"]["favorite_genres"] == []
    assert sm.get("personalization", "favorite_genres") == ["rock"]
    assert DEFAULT_SETTINGS["equalizer"]["bands"] == [0] * 10


# --- L3: property defaults match DEFAULT_SETTINGS -----------------------------

def _bare_manager():
    """A manager with an empty cache, so the property's own literal is used."""
    sm = SettingsManager.__new__(SettingsManager)
    sm.db = _StubDb(0)
    sm._cache = {}
    sm._dirty = set()
    sm._lock = threading.RLock()
    return sm


def test_gapless_property_default_matches_the_schema():
    sm = _bare_manager()
    assert sm.gapless is DEFAULT_SETTINGS["audio"]["gapless_playback"]


def test_accent_color_property_default_matches_the_schema():
    sm = _bare_manager()
    assert sm.accent_color == DEFAULT_SETTINGS["theme"]["accent_color"]


# --- L4: zapret autostart cannot outlive cleanup() ---------------------------

class _ZapretSettings:
    def get(self, category, key, default=None):
        if (category, key) == ("zapret", "auto_start"):
            return True
        return default


def _zapret_core(order):
    return types.SimpleNamespace(
        settings=_ZapretSettings(),
        zapret=types.SimpleNamespace(
            start=lambda **kw: order.append("zapret.start"),
            stop=lambda: order.append("zapret.stop"),
        ),
        _shutting_down=threading.Event(),
        _zapret_start_thread=None,
        _service_lock=threading.RLock(),
    )


def test_autostart_runs_while_the_app_is_live():
    order = []
    core = _zapret_core(order)
    AppCore.start_zapret_if_enabled(core)
    core._zapret_start_thread.join(5)
    assert order == ["zapret.start"]


def test_autostart_is_refused_once_shutdown_started():
    order = []
    core = _zapret_core(order)
    core._shutting_down.set()

    AppCore.start_zapret_if_enabled(core)
    if core._zapret_start_thread is not None:
        core._zapret_start_thread.join(5)

    assert order == [], "zapret.start ran after cleanup() had begun"


def test_autostart_race_loses_no_process(caplog):
    """Shutdown flips between the two checks: the worker must still stand down."""
    order = []
    core = _zapret_core(order)

    real_start = core.zapret.start

    def start_after_stop(**kw):
        order.append("zapret.start")
        return real_start(**kw)

    core.zapret.start = start_after_stop

    def flip():
        core._shutting_down.set()

    flipper = threading.Thread(target=flip)
    flipper.start()
    AppCore.start_zapret_if_enabled(core)
    flipper.join(5)
    if core._zapret_start_thread is not None:
        core._zapret_start_thread.join(5)

    assert order == [], (
        "zapret started concurrently with shutdown - an orphaned winws process"
    )


def test_cleanup_flags_shutdown_before_stopping_zapret(monkeypatch):
    """The flag must be set first, or a start could slip in after stop()."""
    order = []

    class _Flag:
        def __init__(self):
            self._event = threading.Event()

        def set(self):
            order.append("shutdown.set")
            self._event.set()

        def is_set(self):
            return self._event.is_set()

    core = _zapret_core(order)
    core._shutting_down = _Flag()
    core._cache_cleanup_stop = None
    for name in ("watchdog", "lufs_scanner", "downloader", "plugins",
                 "discord_rpc", "proxy", "settings", "db", "cache",
                 "youtube", "_soundcloud", "_yandex", "spotify"):
        setattr(core, name, None)

    # cleanup() shuts the shared service executor down; keep it alive for the
    # rest of the suite.
    from services.base_service import BaseMusicService
    monkeypatch.setattr(BaseMusicService, "shutdown_executor", lambda: None, raising=False)

    AppCore.cleanup(core)

    assert "shutdown.set" in order
    assert order.index("shutdown.set") < order.index("zapret.stop")
    assert core._shutting_down.is_set()