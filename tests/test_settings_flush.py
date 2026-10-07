"""SettingsManager durability tests for P1-9 (guaranteed flush on hard exit).

Pre-fix there was no way to force a synchronous write: only ``atexit.register``,
which os._exit() skips, plus a writer thread that sleeps FLUSH_INTERVAL_SECONDS
before each flush. ``sync_flush_now()`` is the escape hatch the os._exit(3)
watchdog branch in main.py needs.
"""

import threading
import time

from core.settings import SettingsManager


class _FakeDb:
    """Minimal DB surface: set_settings_batch / get_all_settings."""

    def __init__(self, fail_keys=()):
        self.rows = {}
        self.fail_keys = set(fail_keys)
        self.batches = []
        self.lock = threading.Lock()

    def get_all_settings(self):
        return dict(self.rows)

    def get_setting(self, key, default=None):
        """Read-back helper so assertions check persisted state, not the cache."""
        return self.rows.get(key, default)

    def set_settings_batch(self, items):
        """All-or-nothing, like the real core/database.py batch write."""
        with self.lock:
            self.batches.append([(k, v, c) for k, v, c in items])
            staged = dict(self.rows)
            for key, value, category in items:
                if key in self.fail_keys:
                    raise RuntimeError(f"write failed for {key}")
                staged[key] = value
            self.rows.update(staged)
        return len(items)


def _manager(fail_keys=()):
    db = _FakeDb(fail_keys)
    return SettingsManager(db), db


# --- sync_flush_now() writes immediately -------------------------------------

def test_sync_flush_now_persists_without_waiting():
    """A set() followed by sync_flush_now() is visible in the DB at once."""
    sm, db = _manager()

    sm.set("audio", "volume", 11)
    sm.set("theme", "accent_color", "#123456")

    # Not written yet: the writer thread sleeps FLUSH_INTERVAL_SECONDS.
    assert "audio.volume" not in db.rows

    assert sm.sync_flush_now() is True

    assert db.get_setting("audio.volume") == 11
    assert db.get_setting("theme.accent_color") == "#123456"
    assert sm._dirty == set()


def test_sync_flush_now_returns_before_the_writer_interval():
    """It must not sleep: the point is to beat the os._exit() race."""
    sm, db = _manager()
    sm.FLUSH_INTERVAL_SECONDS = 30.0

    sm.set("audio", "volume", 7)
    started = time.monotonic()
    sm.sync_flush_now()
    elapsed = time.monotonic() - started

    assert db.get_setting("audio.volume") == 7
    assert elapsed < 5.0, f"sync_flush_now() blocked for {elapsed:.1f}s"


def test_sync_flush_now_is_idempotent():
    """Repeated calls with nothing pending are no-ops."""
    sm, db = _manager()
    sm.set("audio", "volume", 5)
    assert sm.sync_flush_now() is True
    batches = len(db.batches)

    assert sm.sync_flush_now() is True
    assert sm.sync_flush_now() is True

    assert len(db.batches) == batches, "an empty flush issued a DB write"
    assert db.get_setting("audio.volume") == 5


def test_sync_flush_now_with_nothing_ever_set():
    sm, _ = _manager()
    assert sm.sync_flush_now() is True


# --- failed writes stay pending (pre-existing contract, must not regress) ----

def test_failed_write_keeps_keys_pending():
    """Keys whose write failed must remain pending for the next flush."""
    sm, db = _manager(fail_keys={"bad.key"})

    sm.set("audio", "volume", 3)
    sm.set("bad", "key", 1)
    assert sm.sync_flush_now() is False

    assert ("bad", "key") in sm._dirty, "failed key was dropped from pending set"
    assert db.get_setting("audio.volume") is None, (
        "the whole batch is one transaction; nothing should have landed"
    )


def test_failed_write_is_retried_and_succeeds():
    """After the failure clears, the pending keys are written by the next flush."""
    sm, db = _manager(fail_keys={"bad.key"})

    sm.set("audio", "volume", 3)
    sm.set("bad", "key", 1)
    assert sm.sync_flush_now() is False

    db.fail_keys.clear()               # DB recovers
    assert sm.sync_flush_now() is True

    assert db.get_setting("bad.key") == 1
    assert sm._dirty == set()


def test_sync_flush_now_never_raises():
    """A raising flush must be reported, not propagated: callers are exiting."""
    sm, db = _manager()

    def _boom(payload):
        raise RuntimeError("db gone")

    sm._write_batch = _boom
    sm.set("audio", "volume", 9)

    assert sm.sync_flush_now() is False
    assert ("audio", "volume") in sm._dirty


# --- fallback path when the DB lacks set_settings_batch --------------------

def test_falls_back_to_set_setting_per_key():
    """Older DB shims only offer set_setting; the flush must still work."""
    class _OldDb:
        def __init__(self):
            self.rows = {}

        def get_all_settings(self):
            return {}

        def set_setting(self, key, value, category="general"):
            self.rows[key] = value

    db = _OldDb()
    sm = SettingsManager(db)
    sm.set("audio", "volume", 42)

    assert sm.sync_flush_now() is True
    assert db.rows["audio.volume"] == 42


# --- concurrent set() and sync_flush_now() --------------------------------

def test_concurrent_setters_and_sync_flush():
    """No deadlock, no lost write under mixed load."""
    sm, db = _manager()
    errors = []
    stop = threading.Event()

    def setter(base):
        try:
            i = 0
            while not stop.is_set():
                sm.set("audio", f"v{base}_{i}", i)
                i += 1
        except Exception as e:  # pragma: no cover - failure path
            errors.append(repr(e))

    def flusher():
        try:
            while not stop.is_set():
                sm.sync_flush_now()
        except Exception as e:  # pragma: no cover - failure path
            errors.append(repr(e))

    threads = [threading.Thread(target=setter, args=(n,)) for n in range(3)]
    threads.append(threading.Thread(target=flusher))
    for t in threads:
        t.start()
    time.sleep(0.3)
    stop.set()
    for t in threads:
        t.join(5)
        assert not t.is_alive(), "thread hung -> deadlock"

    assert not errors, errors
    assert sm.sync_flush_now() is True
    assert len(db.rows) > 0


# --- the main.py watchdog contract -----------------------------------------

def test_watchdog_pattern_flushes_before_db_close():
    """Document what main.py::_startup_watchdog relies on.

    The watchdog does sync_flush_now() -> cleanup() -> sync_flush_now() ->
    os._exit(3). This asserts each step works when driven in that order, and
    that a setting written between the two flushes is still persisted.
    """
    sm, db = _manager()

    sm.set("session", "last_volume", 33)
    assert sm.sync_flush_now() is True

    # cleanup() (core.app) flushes again; nothing pending.
    assert sm.sync_flush_now() is True

    # A service thread writes during teardown.
    sm.set("session", "last_position", 42.5)
    assert sm.sync_flush_now() is True

    assert db.get_setting("session.last_volume") == 33
    assert db.get_setting("session.last_position") == 42.5