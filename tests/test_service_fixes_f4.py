"""F4 regression tests: embedded lyrics (H4) and sqlite3.Row profile fields (M23)."""

import sqlite3

import pytest

from services.taste_profile import UserTasteProfile
from utils import tag_parser


def test_extract_embedded_lyrics_missing_file_returns_empty(tmp_path):
    assert tag_parser.extract_embedded_lyrics(str(tmp_path / "nope.mp3")) == ""


def test_extract_embedded_lyrics_non_audio_returns_empty(tmp_path):
    bogus = tmp_path / "bogus.flac"
    bogus.write_bytes(b"not really audio")
    assert tag_parser.extract_embedded_lyrics(str(bogus)) == ""


def test_field_reads_sqlite_row_by_name():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT 'Queen' AS artist, 1 AS completed").fetchone()
    assert UserTasteProfile._field(row, "artist") == "Queen"
    assert UserTasteProfile._field(row, "completed", 0) == 1
    assert UserTasteProfile._field(row, "missing", "d") == "d"


def test_get_artist_works_on_sqlite_row():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT ' Queen ' AS artist").fetchone()
    assert UserTasteProfile._get_artist(row) == "Queen"


def test_get_artist_skips_unknown_on_sqlite_row():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT 'Unknown Artist' AS artist").fetchone()
    assert UserTasteProfile._get_artist(row) is None
