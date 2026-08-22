"""Apply / revert the "Level 0" GPU experiment settings.

Level 0 changes *only* stored settings (no code), so the cost of the visual
effects can be measured before any refactor. Every touched key is snapshotted to
benchmarks/level0_settings_backup.json on `apply`, and `revert` restores exactly
that snapshot (deleting keys that did not exist before).

The app writes settings with a write-behind cache, so run this with the app
STOPPED, then start it and sample.

    & ".venv\\Scripts\\python.exe" scripts/level0_settings.py apply
    & ".venv\\Scripts\\python.exe" scripts/level0_settings.py revert
    & ".venv\\Scripts\\python.exe" scripts/level0_settings.py show
"""
import json
import os
import sqlite3
import sys

DB = os.path.expanduser("~/.nedotify/nedotify_storage.db")
BACKUP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "benchmarks", "level0_settings_backup.json")

# Values are stored exactly as SettingsManager writes them: JSON for bools/ints,
# bare strings for string values (see the current rows in the settings table).
LEVEL0 = {
    "theme.transparency_level": "65",     # was 10 -> panels ~90% transparent
    "theme.glass_blur": "12",             # was 27
    "theme.bg_blur": "8",                 # was 18
    "optimization.blur_quality": "balanced",   # was hq
    "optimization.glow_quality": "reduced",    # was full
    "ui.particles_enabled": "0",          # already off; kept explicit
    "app.particles_enabled": "false",     # stale duplicate key, was true
    "particles_enabled": "false",         # stale duplicate key, was true
    "efficiency.unfocus_enabled": "true",  # was false -> throttling never engaged
    "efficiency.unfocus_blur_reduction": "true",
    "efficiency.unfocus_disable_animations": "true",
}


def _connect():
    return sqlite3.connect(DB, timeout=10)


def show():
    with _connect() as conn:
        rows = dict(conn.execute("select key, value from settings").fetchall())
    for key in LEVEL0:
        print(f"{key:42} = {rows.get(key, '<absent>')!r}")


def apply():
    with _connect() as conn:
        rows = dict(conn.execute("select key, value from settings").fetchall())
        snapshot = {k: rows.get(k, None) for k in LEVEL0}
        os.makedirs(os.path.dirname(BACKUP), exist_ok=True)
        with open(BACKUP, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, ensure_ascii=False, indent=2)
        for key, value in LEVEL0.items():
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
    print(f"applied {len(LEVEL0)} keys; snapshot -> {BACKUP}")
    show()


def revert():
    if not os.path.exists(BACKUP):
        sys.exit(f"no snapshot at {BACKUP}; refusing to guess original values")
    with open(BACKUP, encoding="utf-8") as fh:
        snapshot = json.load(fh)
    with _connect() as conn:
        for key, value in snapshot.items():
            if value is None:
                conn.execute("DELETE FROM settings WHERE key = ?", (key,))
            else:
                conn.execute(
                    "INSERT INTO settings(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, value),
                )
    print(f"reverted {len(snapshot)} keys from snapshot")
    show()


if __name__ == "__main__":
    action = (sys.argv[1] if len(sys.argv) > 1 else "show").lower()
    {"apply": apply, "revert": revert, "show": show}.get(action, show)()
