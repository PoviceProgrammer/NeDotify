"""Focused regression coverage for legacy database schema migrations."""

import sqlite3

import pytest

from core.database import DatabaseManager


class _FailingAlterCursor(sqlite3.Cursor):
    def execute(self, sql, parameters=()):
        normalized = " ".join(sql.lower().split())
        if normalized == "alter table tracks add column is_downloaded integer default 0":
            raise sqlite3.OperationalError("disk I/O error injected by migration regression test")
        return super().execute(sql, parameters)


class _FailingAlterConnection(sqlite3.Connection):
    def cursor(self, factory=sqlite3.Cursor):
        return super().cursor(factory=_FailingAlterCursor)


def test_non_duplicate_alter_operational_error_propagates(tmp_path, monkeypatch):
    """A failed schema ALTER must stop initialization instead of being hidden."""
    real_connect = sqlite3.connect

    def connect_with_failing_cursor(*args, **kwargs):
        return real_connect(*args, factory=_FailingAlterConnection, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect_with_failing_cursor)

    with pytest.raises(sqlite3.OperationalError, match="disk I/O error injected"):
        DatabaseManager(str(tmp_path / "alter-failure.db"))


def test_legacy_settings_table_gets_category_without_losing_values(tmp_path):
    """Opening a pre-category settings table migrates it and preserves rows."""
    db_path = tmp_path / "legacy-settings.db"
    with sqlite3.connect(db_path) as legacy:
        legacy.execute(
            "CREATE TABLE settings ("
            "key TEXT PRIMARY KEY, value TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        legacy.execute("INSERT INTO settings(key, value) VALUES (?, ?)", ("theme", '"forest"'))

    db = DatabaseManager(str(db_path))
    try:
        columns = {row["name"] for row in db.conn.execute("PRAGMA table_info(settings)")}
        assert "category" in columns
        row = db.conn.execute(
            "SELECT key, value, category FROM settings WHERE key = ?", ("theme",)
        ).fetchone()
        assert tuple(row) == ("theme", '"forest"', "general")
    finally:
        db.close()
