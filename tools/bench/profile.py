"""Profile isolation and deterministic fixtures for the NeDotify benchmark.

Every production path builds its state under ``os.path.expanduser("~") +
".nedotify"`` and the project has **no** ``NEDOTIFY_HOME``-style override. On
Windows ``ntpath.expanduser`` consults ``USERPROFILE`` first, so redirecting
that one variable in the child environment moves the whole profile - DB,
logs, covers, WebView2 storage - into a scratch directory. Verified: after
redirecting it, the app created every file under the scratch path and left the
real ``%USERPROFILE%\\.nedotify`` untouched.

Fixtures are deterministic by construction: fixed titles/artists, locally
generated cover PNGs (never a remote URL, which would make both the timing and
the screenshots depend on the network), and a fixed play-history distribution.
"""

from __future__ import annotations

import hashlib
import os
import random
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE_DIR_NAME = ".nedotify"

# --------------------------------------------------------------------------
# deterministic content generators
# --------------------------------------------------------------------------
_ADJ = ["Neon", "Velvet", "Crimson", "Amber", "Static", "Midnight", "Paper",
        "Glass", "Iron", "Sunset", "Hollow", "Electric", "Quiet", "Wild"]
_NOUN = ["Harbour", "Signal", "Circuit", "Ember", "Marble", "Tunnel", "Prism",
         "Anchor", "Static", "Meridian", "Cascade", "Lantern", "Orbit", "Cinder"]
_SOURCES = ["local", "youtube", "soundcloud", "spotify"]
_GENRES = ["pop", "rock", "electronic", "jazz", "hip-hop", "classical", "ambient"]


def _rng(seed: int) -> random.Random:
    return random.Random(seed)


def make_track_specs(count: int, seed: int = 20261003) -> list[dict]:
    """`count` tracks with unique non-placeholder title+artist.

    Unique titles matter: ``DatabaseManager.add_track`` collapses rows whose
    lowercased title AND artist match (or that hit the placeholder set
    "unknown"/"none"/...), which would silently shrink the fixture.
    """
    r = _rng(seed)
    out = []
    for i in range(count):
        adj = _ADJ[i % len(_ADJ)]
        noun = _NOUN[(i // len(_ADJ)) % len(_NOUN)]
        # index embedded in the title guarantees uniqueness
        out.append({
            "title": f"{adj} {noun} #{i:04d}",
            "artist": f"Artist {i % 250:03d}",
            "album": f"Album {(i // 25) % 80:02d}",
            "duration": round(90 + (i % 210) + (i % 7) * 0.35, 2),
            "source": _SOURCES[i % len(_SOURCES)],
            "source_id": f"fixture-{i:05d}",
            "source_url": None,
            "cover_path": None,          # filled in by write_covers()
            "cover_url": None,
            "bitrate": 320,
            "sample_rate": 44100,
            "format": "mp3",
            "file_size": (i % 9 + 3) * 1_048_576,
            "genre": _GENRES[i % len(_GENRES)],
            "year": 2000 + (i % 25),
            "track_number": (i % 12) + 1,
            "play_count": i % 40,
            "is_favorite": 1 if i % 17 == 0 else 0,
            "is_downloaded": 1 if i % 29 == 0 else 0,
            "index": i,
        })
    return out


def write_covers(profile_root: Path, n: int = 12, size: int = 300) -> list[str]:
    """Generate `n` deterministic local cover PNGs; return their absolute paths.

    Local files (not remote URLs) keep the frontend's cover loading offline and
    the golden screenshots reproducible.
    """
    from PIL import Image, ImageDraw

    covers_dir = profile_root / PROFILE_DIR_NAME / "covers"
    covers_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(n):
        r = _rng(9000 + i)
        h1, h2 = r.randrange(360), r.randrange(360)
        img = Image.new("RGB", (size, size))
        d = ImageDraw.Draw(img)
        for y in range(size):                       # vertical gradient
            t = y / max(1, size - 1)
            d.line([(0, y), (size, y)],
                   fill=(int(h1 + (h2 - h1) * t) % 256,
                         (h1 * 2 + y // 3) % 256,
                         (h2 * 2 + y // 5) % 256))
        # a couple of deterministic blocks so covers are visually distinguishable
        for _ in range(3):
            x0, y0 = r.randrange(size - 40), r.randrange(size - 40)
            d.rectangle([x0, y0, x0 + r.randrange(20, 90), y0 + r.randrange(20, 90)],
                        outline=(255, 255, 255), width=2)
        d.text((10, 10), f"C{i}", fill=(255, 255, 255))
        p = covers_dir / f"fixture_cover_{i:02d}.png"
        img.save(p, "PNG", optimize=False, compress_level=1)
        paths.append(str(p))
    return paths


# --------------------------------------------------------------------------
# DB seeding
# --------------------------------------------------------------------------
_TRACK_COLUMNS = (
    "title", "artist", "album", "duration", "file_path", "source", "source_id",
    "source_url", "cover_path", "cover_url", "bitrate", "sample_rate", "format",
    "file_size", "genre", "year", "track_number", "play_count", "is_favorite",
    "is_downloaded",
)

# Settings written before launch so the window/theme are deterministic.
#
# BOOLEAN values must be the literal strings "true"/"false", NOT "1"/"0".
# SettingsManager only coerces 'true'/'false' (core/settings.py:361-362), so a
# row containing '1' comes back as int 1, and the onboarding wizard's guard
# `first_launch_done === true` (js/onboarding.js:30) is then FALSE - the wizard
# then renders full-screen over the whole app. That silently invalidated a full
# round of benchmarks (idle CPU, scroll FPS) until the live backdrop-filter
# audit exposed it.
DEFAULT_SETTINGS_ROWS = [
    ("general", "first_launch_done", "true", "general"),
    ("personalization", "onboarding_completed", "true", "general"),
    ("theme", "theme_mode", "dark", "theme"),
    ("theme", "theme", "dark", "theme"),
    ("theme", "name", "Dark", "theme"),
    ("theme", "transparency_enabled", "false", "theme"),
    ("theme", "glass_blur", "15", "theme"),
    ("theme", "accent_color", "#a855f7", "theme"),
    ("optimization", "performance_preset", "balanced", "theme"),
    ("optimization", "limit_state", "minimize", "theme"),
]


def seed_db(db_path: Path, tracks: list[dict], covers: list[str],
            history_per_track: int = 0,
            settings: dict | None = None,
            cookie_mode: str = "pinned") -> dict:
    """Create a fully-formed NeDotify DB and populate it.

    Uses the project's own ``DatabaseManager`` for schema creation (so the
    fixture can never drift from the real schema, including the idempotent
    ``ALTER TABLE`` additions and the FTS5 triggers), then bulk-inserts with
    ``executemany`` for speed.

    ``settings`` maps ``category -> {key: value}`` and is merged over
    ``DEFAULT_SETTINGS_ROWS``; used by the visual guard to pin a theme.
    """
    sys.path.insert(0, str(REPO_ROOT))
    from core.database import DatabaseManager

    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    for suffix in ("-wal", "-shm"):
        p = Path(str(db_path) + suffix)
        if p.exists():
            p.unlink()

    mgr = DatabaseManager(str(db_path))

    rows = []
    for t in tracks:
        cover = covers[t["index"] % len(covers)] if covers else None
        # file_path only for rows marked downloaded; add_track() treats a
        # non-null file_path as "already downloaded".
        fp = (f"C:/fixture/library/track_{t['index']:05d}.mp3"
              if t["is_downloaded"] else None)
        rows.append((
            t["title"], t["artist"], t["album"], t["duration"], fp, t["source"],
            t["source_id"], t["source_url"], cover, t["cover_url"], t["bitrate"],
            t["sample_rate"], t["format"], t["file_size"], t["genre"], t["year"],
            t["track_number"], t["play_count"], t["is_favorite"], t["is_downloaded"],
        ))

    conn = mgr.conn
    placeholders = ",".join("?" * len(_TRACK_COLUMNS))
    with mgr._write_lock:
        with conn:
            conn.executemany(
                f"INSERT OR IGNORE INTO tracks ({','.join(_TRACK_COLUMNS)}) "
                f"VALUES ({placeholders})", rows)
            n_tracks = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]

            n_history = 0
            if history_per_track:
                ids = [r[0] for r in conn.execute("SELECT id FROM tracks ORDER BY id")]
                r = _rng(4242)
                hist = []
                for tid in ids:
                    for _ in range(history_per_track):
                        hist.append((tid,
                                     round(t["duration"] * r.uniform(0.3, 1.0), 2),
                                     1 if r.random() < 0.7 else 0))
                conn.executemany(
                    "INSERT INTO history (track_id, duration_listened, completed) "
                    "VALUES (?, ?, ?)", hist)
                n_history = len(hist)
                conn.executemany(
                    "INSERT INTO listening_stats (duration_ms) VALUES (?)",
                    [(h[1] * 1000,) for h in hist])

            # a couple of playlists so the library sidebar is not empty
            conn.execute(
                "INSERT INTO playlists (name, description, is_smart) VALUES (?,?,0)",
                ("Fixture Favourites", "Seeded by tools/bench"))
            conn.execute(
                "INSERT INTO playlists (name, description, is_smart) VALUES (?,?,0)",
                ("Fixture Mix", "Seeded by tools/bench"))
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value, category) VALUES (?,?,?)",
                ("__seeded", "1", "general"))

    conn.executemany(
        "INSERT OR REPLACE INTO settings (key, value, category) VALUES (?,?,?)",
        [(f"{cat}.{k}", v, cat) for cat, k, v, _c in DEFAULT_SETTINGS_ROWS]
        + [(f"{cat}.{k}", str(v), cat)
           for cat, kv in (settings or {}).items() for k, v in kv.items()])

    # keep the WAL checkpointed so the app does not inherit a big WAL file
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()

    # --- cookie handling -------------------------------------------------
    # YouTubeService._detect_browser_cookies() scrapes the *real* installed
    # browsers when neither `cookiefile` nor `cookiesfrombrowser` is set
    # (services/youtube_service.py:271), which reads the user's actual browser
    # profile (measured: 636 Cookie objects, 120.66 ms - see
    # docs/perf/prof_python_startup.md).
    #
    # cookie_mode="pinned" (default): point auth.cookies_file_path at an empty
    # jar inside the scratch profile, so a bench run never touches the real
    # browser. cookie_mode="real": delete the override so auto-detection runs,
    # which reproduces what a user actually pays at startup - at the cost of
    # reading the real browser profile. Both are measurable; the baseline
    # records which was used.
    profile_root = db_path.parent.parent
    conn2 = sqlite3.connect(str(db_path))
    if cookie_mode == "real":
        conn2.execute("DELETE FROM settings WHERE key='auth.cookies_file_path'")
        conn2.execute("DELETE FROM settings WHERE key='auth.browser_cookies'")
        conn2.commit(); conn2.close()
        cookie_jar = None
    else:
        jar = profile_root / PROFILE_DIR_NAME / "bench_cookies.txt"
        jar.parent.mkdir(parents=True, exist_ok=True)
        if not jar.exists():
            jar.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
        conn2.execute(
            "INSERT OR REPLACE INTO settings (key, value, category) VALUES (?,?,?)",
            ("auth.cookies_file_path", str(jar), "auth"))
        conn2.execute(
            "INSERT OR REPLACE INTO settings (key, value, category) VALUES (?,?,?)",
            ("auth.browser_cookies", "none", "auth"))
        conn2.commit(); conn2.close()
        cookie_jar = str(jar)

    return {"db_path": str(db_path), "tracks": n_tracks, "history": n_history,
            "covers": len(covers), "cookie_mode": cookie_mode,
            "cookie_jar": cookie_jar}


# --------------------------------------------------------------------------
# profile lifecycle
# --------------------------------------------------------------------------
def make_scratch_profile(prefix: str = "nedotify-bench-") -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


def child_env(profile_root: Path, debug_port: int = 9222,
              extra: dict | None = None) -> dict:
    """Environment for the app child process: redirected ~ + CDP enabled."""
    env = dict(os.environ)
    env["USERPROFILE"] = str(profile_root)
    env["HOMEDRIVE"] = ""
    env["HOMEPATH"] = ""
    # main.py APPENDS to this, so the flag survives next to its own args.
    existing = env.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "")
    args = f"--remote-debugging-port={debug_port} --disable-background-timer-throttling"
    env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (existing + " " + args).strip()
    # no Last.fm key -> _api_request short-circuits and never touches the network
    env.pop("LASTFM_API_KEY", None)
    env.pop("LASTFM_USERNAME", None)
    env["PYTHONUNBUFFERED"] = "1"
    if extra:
        env.update(extra)
    return env


def fingerprint_tree(repo_root: Path = REPO_ROOT) -> dict:
    """SHA-256 (short) of every tracked source file, so a result set can be
    tied to the exact code that produced it even with a dirty worktree."""
    out = {}
    for sub in ("main.py", "core", "services", "ui/web_new_v2", "tools"):
        p = repo_root / sub
        files = [p] if p.is_file() else sorted(q for q in p.rglob("*") if q.is_file())
        for f in files:
            if f.suffix.lower() not in {".py", ".js", ".css", ".html"}:
                continue
            try:
                data = f.read_bytes()
            except OSError:
                continue
            rel = f.relative_to(repo_root).as_posix()
            out[rel] = hashlib.sha256(data).hexdigest()[:16]
    return out


def tree_fingerprint_short(fp: dict) -> str:
    h = hashlib.sha256()
    for k in sorted(fp):
        h.update(k.encode()); h.update(fp[k].encode())
    return h.hexdigest()[:16]
