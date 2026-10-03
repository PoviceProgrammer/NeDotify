"""DatabaseManager regression tests for the P0/P2 data-integrity fixes.

Each test targets one audit finding and fails on the pre-fix code:

  P0-3   ensure_download_queue_table was defined twice (the first, cursor-less
         copy, shadowed by the second), _init_database calls it with a cursor,
         and both call modes have to keep working.
  P2-2   get_playlists() ran a DELETE + commit() from a getter, outside
         _write_lock, swallowing every exception.
  P2-3   get_tracks_missing_cover() gated the placeholder-name branch on
         cover_path IS NULL, hiding exactly the rows needing a name backfill.
  P2-12  bool is a subclass of int, so get(True) resolved to get_track(1).
"""

import inspect
import threading

from core.database import DatabaseManager


# --- P0-3: single, non-shadowed ensure_download_queue_table -------------------

def test_ensure_download_queue_table_defined_once():
    """One definition in the class body, not two with the later one winning."""
    source = inspect.getsource(DatabaseManager)
    defs = [
        line for line in source.splitlines()
        if line.strip().startswith("def ensure_download_queue_table")
    ]
    assert len(defs) == 1, f"ensure_download_queue_table defined {len(defs)}x: {defs}"

    # A shadowed pair also shows up as a lost function: the cursor-less copy
    # carries no `cursor` parameter, so this fails if the dead one wins.
    params = inspect.signature(DatabaseManager.ensure_download_queue_table).parameters
    assert "cursor" in params, (
        "the surviving definition must accept cursor=; "
        f"got {inspect.signature(DatabaseManager.ensure_download_queue_table)}"
    )


def test_ensure_download_queue_table_both_call_modes(tmp_db):
    """cursor= (from _init_database) and bare (DownloadManager) both work."""
    tmp_db.ensure_download_queue_table(cursor=tmp_db.conn.cursor())
    tmp_db.ensure_download_queue_table()  # bare, takes _write_lock itself

    names = {
        row["name"] for row in
        tmp_db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "download_queue" in names

    # Still fully functional afterwards: unique index enforced, dedup collapse.
    assert tmp_db.download_queue_add(500, "youtube", "dq1") is True
    assert tmp_db.download_queue_add(500, "youtube", "dq1") is False


# --- P2-2: get_playlists is a pure reader; cleanup moved to create_playlist ---

def _seed_duplicate_system_playlists(db):
    """Two empty 'Локальные' rows plus one 'Локальные треки'."""
    db.conn.execute("INSERT INTO playlists (name) VALUES ('Локальные')")
    db.conn.execute("INSERT INTO playlists (name) VALUES ('Локальные')")
    db.conn.execute("INSERT INTO playlists (name) VALUES ('Локальные треки')")
    db.conn.commit()
    return db.get_playlists_count()


def test_get_playlists_does_not_write(tmp_db):
    """Reading playlists must not delete rows or commit anything."""
    assert _seed_duplicate_system_playlists(tmp_db) == 3

    first = tmp_db.get_playlists()
    assert len(first) == 3, "get_playlists() must return rows as stored"
    assert tmp_db.get_playlists_count() == 3, "get_playlists() deleted rows"

    # Idempotent and side-effect free.
    second = tmp_db.get_playlists()
    assert [r["id"] for r in second] == [r["id"] for r in first]
    assert tmp_db.get_playlists_count() == 3


def test_get_playlists_does_not_commit_foreign_work(tmp_db):
    """The getter used to commit() this thread's connection, publishing
    unrelated unfinished writes made by the same thread."""
    other = tmp_db.create_playlist("Чужой плейлист")

    # An uncommitted INSERT sitting in this thread's connection.
    tmp_db.conn.execute("INSERT INTO playlists (name) VALUES ('Незакоммичено')")
    assert tmp_db.get_playlists_count() == 2  # inside the transaction

    tmp_db.get_playlists()  # pre-fix: this committed the row above

    # Prove the row is still only visible inside the open transaction, i.e. it
    # was NOT committed by the getter.
    tmp_db.conn.rollback()
    assert other is not None
    assert tmp_db.get_playlists_count() == 1


def test_get_playlists_does_not_swallow_exceptions(tmp_db, monkeypatch):
    """A broken cleanup path must not be hidden by a bare `except: pass`."""
    calls = []

    class _Boom:
        def execute(self, *a, **kw):
            calls.append(a)
            raise RuntimeError("cleanup exploded")

        def __getattr__(self, item):
            return self.execute

    monkeypatch.setattr(
        DatabaseManager, "_cleanup_duplicate_empty_system_playlists",
        lambda self, cursor=None: self.conn.execute("SELECT 1") and 0,
    )
    # get_playlists() must not touch the cleanup at all; if it did, the rows
    # would disappear. Assert via rowcount instead of exception type.
    _seed_duplicate_system_playlists(tmp_db)
    monkeypatch.setattr(
        DatabaseManager, "_cleanup_duplicate_empty_system_playlists",
        lambda self, cursor=None: (_ for _ in ()).throw(
            AssertionError("get_playlists() must not run cleanup")
        ),
    )
    rows = tmp_db.get_playlists()
    assert len(rows) == 3


def test_cleanup_runs_on_create_playlist(tmp_db):
    """Duplicate system playlists are collapsed when a playlist is created."""
    assert _seed_duplicate_system_playlists(tmp_db) == 3

    pid = tmp_db.create_playlist("Моя подборка")

    names = sorted(r["name"] for r in tmp_db.get_playlists())
    assert names == ["Локальные", "Локальные треки", "Моя подборка"]
    # Idempotent: creating again neither duplicates nor removes rows.
    assert tmp_db.create_playlist("Моя подборка") == pid
    assert tmp_db.get_playlists_count() == 3


def test_cleanup_keeps_system_playlists_that_have_tracks(tmp_db):
    """Only *empty* duplicates are dropped; a filled one must survive."""
    first = tmp_db.create_playlist("Локальные")
    dup = tmp_db.conn.execute(
        "INSERT INTO playlists (name) VALUES ('Локальные')"
    ).lastrowid
    tid = tmp_db.add_track(title="T", artist="A", source="youtube", source_id="cl1")
    tmp_db.add_to_playlist(dup, tid)

    tmp_db.create_playlist("Другая")

    ids = {r["id"] for r in tmp_db.get_playlists()}
    assert first in ids, "empty original was deleted while a filled duplicate existed"
    assert dup in ids, "a system playlist holding tracks was deleted"


def test_cleanup_logs_instead_of_passing(tmp_db, caplog):
    """A failing cleanup is logged, not silently ignored, and never raises."""
    dead_cursor = tmp_db.conn.cursor()
    dead_cursor.close()  # executing on it raises ProgrammingError

    with caplog.at_level("WARNING"):
        assert tmp_db._cleanup_duplicate_empty_system_playlists(dead_cursor) == 0
    assert any("system playlists" in r.message for r in caplog.records)


def test_cleanup_without_cursor_takes_the_write_lock(tmp_db):
    """The cursor=None form (standalone call) works and takes _write_lock."""
    assert _seed_duplicate_system_playlists(tmp_db) == 3
    assert tmp_db._cleanup_duplicate_empty_system_playlists() == 1
    assert tmp_db.get_playlists_count() == 2
    # Idempotent: nothing left to delete.
    assert tmp_db._cleanup_duplicate_empty_system_playlists() == 0
    assert tmp_db.get_playlists_count() == 2


def test_cleanup_is_serialised_against_other_writers(tmp_db):
    """Concurrent creators + cleanup must not raise or lose rows."""
    errors = []

    def worker(i):
        try:
            for _ in range(20):
                tmp_db.create_playlist(f"Плейлист {i}")
                tmp_db.get_playlists()
                tmp_db._cleanup_duplicate_empty_system_playlists()
        except Exception as e:  # pragma: no cover - failure path
            errors.append(repr(e))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors


# --- P2-3: get_tracks_missing_cover picks up placeholder-named rows -----------

def test_missing_cover_includes_placeholder_names_with_cover(tmp_db):
    """A row with artwork but 'Unknown Title' must still be selected."""
    good = tmp_db.add_track(
        title="Unknown Title", artist="Unknown Artist",
        source="youtube", source_id="ph1",
    )
    tmp_db.conn.execute(
        "UPDATE tracks SET cover_path = ?, cover_url = ? WHERE id = ?",
        ("C:/cover.jpg", "http://x/1.jpg", good),
    )
    tmp_db.conn.commit()

    ids = {r["id"] for r in tmp_db.get_tracks_missing_cover(limit=50)}
    assert good in ids, "placeholder-named row with artwork was skipped"


def test_missing_cover_still_includes_artworkless_rows(tmp_db):
    """The original case (no cover at all) must keep working."""
    tid = tmp_db.add_track(title="Song", artist="Artist",
                           source="youtube", source_id="nc1")
    ids = {r["id"] for r in tmp_db.get_tracks_missing_cover(limit=50)}
    assert tid in ids


def test_missing_cover_excludes_complete_rows(tmp_db):
    """A row with artwork *and* real names must not be returned (no refetch loop)."""
    tid = tmp_db.add_track(title="Real", artist="Artist",
                           source="youtube", source_id="ok1",
                           cover_url="http://x/ok.jpg")
    tmp_db.conn.execute(
        "UPDATE tracks SET cover_path = ? WHERE id = ?", ("C:/ok.jpg", tid)
    )
    tmp_db.conn.commit()
    ids = {r["id"] for r in tmp_db.get_tracks_missing_cover(limit=50)}
    assert tid not in ids


def test_missing_cover_skips_local_and_sourceless_rows(tmp_db):
    """Pre-existing filters stay in place."""
    local = tmp_db.add_track(title="Local", artist="A",
                             source="local", source_id="l1")
    nosrc = tmp_db.add_track(title="NoSrc", artist="A",
                             source="youtube", source_id="")
    ids = {r["id"] for r in tmp_db.get_tracks_missing_cover(limit=50)}
    assert local not in ids
    assert nosrc not in ids


def test_missing_cover_backfill_clears_the_row(tmp_db):
    """End-to-end: after a backfill the row drops out of the selection."""
    tid = tmp_db.add_track(title="Unknown Title", artist="Unknown Artist",
                           source="youtube", source_id="bf1",
                           cover_url="http://x/bf.jpg")
    tmp_db.conn.execute(
        "UPDATE tracks SET cover_path = ? WHERE id = ?", ("C:/bf.jpg", tid)
    )
    tmp_db.conn.commit()
    assert tid in {r["id"] for r in tmp_db.get_tracks_missing_cover(limit=50)}

    tmp_db.backfill_track_metadata(tid, "http://x/bf.jpg",
                                   title="Real Title", artist="Real Artist")

    assert tid not in {r["id"] for r in tmp_db.get_tracks_missing_cover(limit=50)}


# --- P2-12: bool must not be treated as a track id ---------------------------

def test_get_bool_is_not_a_track_lookup(tmp_db):
    """bool subclasses int, so get(True) used to return track #1."""
    first = tmp_db.add_track(title="Track One", artist="A",
                             source="youtube", source_id="bt1")
    assert first == 1, "precondition: first inserted row must be id 1"

    assert tmp_db.get(True) is None
    assert tmp_db.get(False) is None


def test_get_int_still_returns_track(tmp_db):
    """The int path is unaffected."""
    tid = tmp_db.add_track(title="Song", artist="A",
                           source="youtube", source_id="bt2")
    row = tmp_db.get(tid)
    assert row is not None and row["id"] == tid


def test_get_bool_uses_string_path(tmp_db):
    """A bool is not a setting key either, so it falls back to default."""
    assert tmp_db.get(True, default="fallback") == "fallback"
    assert tmp_db.get(False, default="fallback") == "fallback"


def test_get_str_path_unchanged(tmp_db):
    """Pin the string path so the bool fix cannot silently alter it.

    NOTE a separate, pre-existing defect is visible here and was deliberately
    NOT changed in this pass: get() calls get_setting("general", key_or_id),
    but get_setting's signature is (key, default=None). So the string path never
    looks the key up -- it returns the key itself as the default. DatabaseManager
    .get() has no callers anywhere in the repo, so the defect is latent; fixing it
    would be an unrelated behaviour change. Pinned as-is here.
    """
    tmp_db.set_setting("volume", 42, category="general")
    assert tmp_db.get("volume") == "volume"      # key echoed back, not 42
    assert tmp_db.get("absent-key", default=7) == "absent-key"


# --- close_thread_connection: the 'conn' branch was dead ---------------------

def test_close_thread_connection_handles_absent_slot(tmp_db):
    """No connection yet: must be a silent no-op (and stay repeatable)."""
    fresh = DatabaseManager(":memory:")
    try:
        fresh.close_thread_connection()
        fresh.close_thread_connection()
    finally:
        fresh.close()


def test_close_thread_connection_closes_and_reopens(tmp_db):
    """A real connection is closed, forgotten, and transparently reopened."""
    tmp_db.get_tracks_count()
    assert getattr(tmp_db._local, "connection", None) is not None
    tmp_db.close_thread_connection()
    assert getattr(tmp_db._local, "connection", None) is None
    assert tmp_db.get_tracks_count() >= 0