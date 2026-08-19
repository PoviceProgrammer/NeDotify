"""
P3 Acceptance Criteria Tests — Personalization: Profile from all local signals.

Tests:
1. test_profile_uses_favorites_downloads_playlists — mock DB with favorites/downloads/playlists
   → profile contains those artists, NO default fallback artists in output.
2. test_deduplication_within_and_across_sections — same track never appears twice in mixes or across sections.
3. test_local_likes_and_downloads_mix — "Из лайков и загрузок" mix present and contains only local tracks.
4. test_fallback_only_when_profile_empty — with empty DB, DEFAULT_FALLBACK_ARTISTS used (FALLBACK log), not with real data.
5. test_profile_logging_profile_tag — [PROFILE] log emitted during build_from_db with correct artist names.
"""

import sqlite3
import threading
import logging
import pytest
from unittest.mock import MagicMock, patch
from services.taste_profile import UserTasteProfile
from services.recommendation_service import RecommendationService

# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

FAKE_ARTISTS = ["Radiohead", "Portishead", "Massive Attack", "Björk", "Aphex Twin"]
DEFAULT_ARTISTS = UserTasteProfile.DEFAULT_SEED_ARTISTS


def _make_db_with_signals():
    """Create in-memory DB with favorites, downloads, playlist tracks, and history."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            artist TEXT DEFAULT 'Unknown Artist',
            album TEXT DEFAULT '',
            duration REAL DEFAULT 0,
            file_path TEXT,
            source TEXT DEFAULT 'local',
            source_id TEXT,
            source_url TEXT,
            cover_path TEXT,
            cover_url TEXT,
            genre TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_played TIMESTAMP,
            play_count INTEGER DEFAULT 0,
            is_favorite INTEGER DEFAULT 0,
            is_downloaded INTEGER DEFAULT 0,
            metadata_json TEXT
        );

        CREATE TABLE history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_id INTEGER NOT NULL,
            played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            duration_listened REAL DEFAULT 0,
            completed INTEGER DEFAULT 0
        );

        CREATE TABLE playlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            cover_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_smart INTEGER DEFAULT 0,
            smart_rules_json TEXT
        );

        CREATE TABLE playlist_tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            playlist_id INTEGER NOT NULL,
            track_id INTEGER NOT NULL,
            position INTEGER DEFAULT 0,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # Insert tracks: 2 favorites, 2 downloads, 1 playlist-only
    cur.execute("INSERT INTO tracks (title, artist, genre, is_favorite, is_downloaded, source, source_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("Creep", "Radiohead", "Alternative", 1, 0, "local", "r1"))
    cur.execute("INSERT INTO tracks (title, artist, genre, is_favorite, is_downloaded, source, source_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("Exit Music", "Radiohead", "Alternative", 1, 0, "local", "r2"))
    cur.execute("INSERT INTO tracks (title, artist, genre, is_favorite, is_downloaded, source, source_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("Glory Box", "Portishead", "Trip-Hop", 0, 1, "local", "p1"))
    cur.execute("INSERT INTO tracks (title, artist, genre, is_favorite, is_downloaded, source, source_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("Sour Times", "Portishead", "Trip-Hop", 0, 1, "local", "p2"))
    cur.execute("INSERT INTO tracks (title, artist, genre, is_favorite, is_downloaded, source, source_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("Teardrop", "Massive Attack", "Trip-Hop", 0, 0, "local", "m1"))

    # Insert playlist
    cur.execute("INSERT INTO playlists (name) VALUES ('My Playlist')")
    playlist_id = cur.lastrowid

    # Track IDs: Radiohead=1,2; Portishead=3,4; MassiveAttack=5
    cur.execute("INSERT INTO playlist_tracks (playlist_id, track_id, position) VALUES (?, ?, ?)", (playlist_id, 5, 1))

    # History: Radiohead played 3 times (2 completed), Portishead 1 time
    cur.execute("INSERT INTO history (track_id, played_at, completed) VALUES (1, '2026-08-01 10:00:00', 1)")
    cur.execute("INSERT INTO history (track_id, played_at, completed) VALUES (1, '2026-08-02 11:00:00', 1)")
    cur.execute("INSERT INTO history (track_id, played_at, completed) VALUES (3, '2026-08-03 15:00:00', 0)")
    conn.commit()
    return conn


def _make_empty_db():
    """Create in-memory DB with no signals."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE tracks (
            id INTEGER PRIMARY KEY, title TEXT, artist TEXT, album TEXT,
            duration REAL DEFAULT 0, file_path TEXT, source TEXT, source_id TEXT,
            source_url TEXT, cover_path TEXT, cover_url TEXT, genre TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, last_played TIMESTAMP,
            play_count INTEGER DEFAULT 0, is_favorite INTEGER DEFAULT 0,
            is_downloaded INTEGER DEFAULT 0, metadata_json TEXT
        );
        CREATE TABLE history (
            id INTEGER PRIMARY KEY, track_id INTEGER, played_at TIMESTAMP,
            duration_listened REAL DEFAULT 0, completed INTEGER DEFAULT 0
        );
        CREATE TABLE playlists (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE playlist_tracks (id INTEGER PRIMARY KEY, playlist_id INTEGER, track_id INTEGER, position INTEGER DEFAULT 0);
    """)
    conn.commit()
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# P3.1 — Profile uses favorites, downloads, playlists (no default fallback artists)
# ─────────────────────────────────────────────────────────────────────────────

def test_profile_uses_favorites_downloads_playlists():
    conn = _make_db_with_signals()
    profile = UserTasteProfile().build_from_db(conn)

    # Profile must have artists from DB, NOT default fallback artists
    artist_names = [a['name'] for a in profile.top_artists]
    assert len(artist_names) > 0, "Profile must have artists"
    assert "Radiohead" in artist_names, "Radiohead (favorited + history) must appear"
    assert "Portishead" in artist_names, "Portishead (downloaded + history) must appear"
    assert "Massive Attack" in artist_names, "Massive Attack (playlist) must appear"

    for default_artist in DEFAULT_ARTISTS:
        assert default_artist not in artist_names, (
            f"DEFAULT artist '{default_artist}' must NOT appear in a non-empty profile. "
            f"Got artists: {artist_names}"
        )


def test_profile_seed_artists_no_default_when_nonempty():
    conn = _make_db_with_signals()
    profile = UserTasteProfile().build_from_db(conn)
    seeds = profile.get_seed_artists(limit=10)

    assert len(seeds) > 0
    for default_artist in DEFAULT_ARTISTS:
        assert default_artist not in seeds, (
            f"get_seed_artists() must not return DEFAULT artist '{default_artist}' when profile is non-empty. "
            f"Got: {seeds}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# P3.2 — Deduplication within and across sections
# ─────────────────────────────────────────────────────────────────────────────

def test_deduplication_within_mixes():
    """Each mix must contain no duplicate tracks (by artist:title key)."""
    conn = _make_db_with_signals()
    service = RecommendationService(db=conn)

    # Mock Last.fm and resolver
    service.lastfm.artist.getTopTracks = MagicMock(return_value=[
        {'name': 'Creep', 'artist': 'Radiohead'},
        {'name': 'Creep', 'artist': 'Radiohead'},  # intentional duplicate
        {'name': 'Exit Music', 'artist': 'Radiohead'},
    ])
    service.lastfm.chart.getTopTracks = MagicMock(return_value=[])
    service.resolver.resolve_track = MagicMock(side_effect=lambda title, artist="": {
        'title': title, 'artist': artist,
        'cover_url': '', 'source': 'local', 'source_id': f'{artist}_{title}',
        'source_url': '', 'duration': 180.0
    })

    done = threading.Event()
    result_mixes = []

    def cb(mixes):
        result_mixes.extend(mixes)
        done.set()

    service.get_mixes(callback=cb)
    done.wait(timeout=5.0)

    # Check within-mix dedup
    for mix in result_mixes:
        if mix.get('type') == 'custom_playlist' and mix.get('tracks'):
            seen = set()
            for trk in mix['tracks']:
                key = f"{trk.get('artist', '').lower()}:{trk.get('title', '').lower()}"
                assert key not in seen, f"Duplicate track in mix '{mix['title']}': {key}"
                seen.add(key)


def test_deduplication_across_mixes():
    """Same track must NOT appear in two different mixes."""
    conn = _make_db_with_signals()
    service = RecommendationService(db=conn)

    shared_track = {'name': 'Shared Song', 'artist': 'Radiohead'}
    service.lastfm.artist.getTopTracks = MagicMock(return_value=[shared_track, shared_track])
    service.lastfm.chart.getTopTracks = MagicMock(return_value=[shared_track])
    service.resolver.resolve_track = MagicMock(side_effect=lambda title, artist="": {
        'title': title, 'artist': artist,
        'cover_url': '', 'source': 'local',
        'source_id': f'{artist}_{title}', 'source_url': '', 'duration': 180.0
    })

    done = threading.Event()
    result_mixes = []

    def cb(mixes):
        result_mixes.extend(mixes)
        done.set()

    service.get_mixes(callback=cb)
    done.wait(timeout=5.0)

    global_seen = set()
    for mix in result_mixes:
        for trk in mix.get('tracks', []):
            key = f"{trk.get('artist', '').lower()}:{trk.get('title', '').lower()}"
            assert key not in global_seen, f"Track '{key}' duplicated across mixes"
            global_seen.add(key)


# ─────────────────────────────────────────────────────────────────────────────
# P3.3 — "Из лайков и загрузок" mix is present and uses local tracks
# ─────────────────────────────────────────────────────────────────────────────

def test_local_likes_and_downloads_mix_present():
    conn = _make_db_with_signals()
    service = RecommendationService(db=conn)

    service.lastfm.artist.getTopTracks = MagicMock(return_value=[])
    service.lastfm.chart.getTopTracks = MagicMock(return_value=[])
    service.resolver.resolve_track = MagicMock(return_value=None)

    done = threading.Event()
    result_mixes = []

    def cb(mixes):
        result_mixes.extend(mixes)
        done.set()

    service.get_mixes(callback=cb)
    done.wait(timeout=5.0)

    # Find the local mix
    local_mix = next(
        (m for m in result_mixes if m.get('title') == 'Из лайков и загрузок'),
        None
    )
    assert local_mix is not None, "'Из лайков и загрузок' mix must be present when user has favorites/downloads"
    assert len(local_mix.get('tracks', [])) > 0, "Local mix must have tracks"

    # All tracks must be from DB (is_favorite or is_downloaded or playlist)
    user_artists = {'Radiohead', 'Portishead', 'Massive Attack'}
    for trk in local_mix['tracks']:
        assert trk.get('artist') in user_artists, (
            f"Local mix track must be from user's local data, got artist: {trk.get('artist')}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# P3.4 — Fallback ONLY when profile is genuinely empty
# ─────────────────────────────────────────────────────────────────────────────

def test_fallback_only_when_profile_empty():
    """With real DB data, DEFAULT_FALLBACK_ARTISTS must NOT appear in seeds."""
    real_conn = _make_db_with_signals()
    profile_real = UserTasteProfile().build_from_db(real_conn)
    assert not profile_real.is_empty(), "Real DB profile must not be empty"
    seeds_real = profile_real.get_seed_artists(limit=10)
    for d in DEFAULT_ARTISTS:
        assert d not in seeds_real, f"Seed '{d}' is a default artist but profile has real data"

    # Empty DB → must use defaults
    empty_conn = _make_empty_db()
    profile_empty = UserTasteProfile().build_from_db(empty_conn)
    assert profile_empty.is_empty(), "Empty DB profile must report is_empty()==True"
    seeds_empty = profile_empty.get_seed_artists(limit=5)
    # Seeds should come from DEFAULT_SEED_ARTISTS
    for s in seeds_empty:
        assert s in DEFAULT_ARTISTS, f"Empty profile seed '{s}' not in DEFAULT_SEED_ARTISTS"


# ─────────────────────────────────────────────────────────────────────────────
# P3.5 — [PROFILE] log emitted with correct artist names
# ─────────────────────────────────────────────────────────────────────────────

def test_profile_logging_profile_tag():
    """[PROFILE] log must be emitted with correct artist names during build_from_db."""
    import logging
    conn = _make_db_with_signals()

    # Capture log records via a list handler
    log_records = []

    class ListHandler(logging.Handler):
        def emit(self, record):
            log_records.append(self.format(record))

    handler = ListHandler()
    handler.setLevel(logging.DEBUG)
    target_logger = logging.getLogger('services.taste_profile')
    target_logger.addHandler(handler)
    old_level = target_logger.level
    target_logger.setLevel(logging.DEBUG)

    try:
        UserTasteProfile().build_from_db(conn)
    finally:
        target_logger.removeHandler(handler)
        target_logger.setLevel(old_level)

    profile_logs = [r for r in log_records if '[PROFILE]' in r]
    assert len(profile_logs) > 0, f"At least one [PROFILE] log must be emitted. Got: {log_records}"

    # One of the logs must mention Radiohead (top weighted artist)
    artist_log = next((l for l in profile_logs if 'Radiohead' in l), None)
    assert artist_log is not None, (
        f"[PROFILE] log must mention 'Radiohead'. Got logs: {profile_logs}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# P3.6 — Weighted scores: favorites and downloads score higher than plain plays
# ─────────────────────────────────────────────────────────────────────────────

def test_weighted_scores_favorites_over_plays():
    """Radiohead (2 favorites) should score higher than an artist with only 1 plain play."""
    conn = _make_db_with_signals()
    profile = UserTasteProfile().build_from_db(conn)

    artist_map = {a['name']: a['play_count'] for a in profile.top_artists}

    # Radiohead: 2 favorites (×3) + 2 completed plays (×2) → very high score
    # Massive Attack: 1 playlist (×1) only → lower score
    assert 'Radiohead' in artist_map
    assert 'Massive Attack' in artist_map
    assert artist_map['Radiohead'] > artist_map.get('Massive Attack', 0), (
        "Radiohead (favorites + completed plays) must score higher than Massive Attack (playlist only)"
    )
