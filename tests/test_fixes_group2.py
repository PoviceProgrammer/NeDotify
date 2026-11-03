"""Tests for Group #2 bug fixes (Music search and track matching).

Covers:
- BUG-WIN-003: 3+ artist collaborations and feats matching in music_matching and lyrics_lookup.
- BUG-WIN-006: No disappearing or duplicated search results in search.js streaming search.
- BUG-WIN-010: Conjunction delimiters 'and' and 'и' in credits().
- BUG-WIN-011: TrackResolver._is_plausible_match video title artist extraction and score threshold.
- BUG-WIN-012: Title_metadata unbracketed/unhyphenated version detection ("Title Remix").
- BUG-WIN-034: Yandex Music unblocked in UI search.
- BUG-WIN-037: Keyboard layout conversion `convert_layout` and fallback search.
"""

import time
import pytest
from unittest.mock import Mock
from types import SimpleNamespace

from services.music_matching import (
    credits,
    artist_matches,
    title_metadata,
    similarity,
)
from services.track_resolver import TrackResolver, TRACK_MATCH_MIN_SCORE
from services.lyrics_lookup import LyricsLookup
from utils.search_query import convert_layout, suggest_search_queries


# ==============================================================================
# BUG-WIN-010: "and" and "и" delimiters in credits()
# ==============================================================================

def test_credits_splits_and_conjunction():
    assert credits("Drake and 21 Savage") == ["Drake", "21 Savage"]
    assert credits("Artist A and Artist B and Artist C") == ["Artist A", "Artist B", "Artist C"]


def test_credits_splits_russian_i_conjunction():
    assert credits("Баста и Гуф") == ["Баста", "Гуф"]
    assert credits("Miyagi и Andy Panda") == ["Miyagi", "Andy Panda"]


def test_credits_handles_list_with_composite_strings():
    assert credits(["Drake and 21 Savage", "Travis Scott"]) == ["Drake", "21 Savage", "Travis Scott"]
    assert credits(["Би-2 и Чиж & Co"]) == ["Би-2", "Чиж", "Co"]


# ==============================================================================
# BUG-WIN-003: 3+ artists collaborations & feats
# ==============================================================================

def test_three_plus_artist_collaboration_matches_symmetrically():
    # 3+ artists joined with comma and ampersand
    assert artist_matches("Eminem, Dr. Dre & 50 Cent", "50 Cent, Dr. Dre & Eminem")
    assert artist_matches("Artist A, Artist B & Artist C", ["Artist A", "Artist B", "Artist C"])
    assert artist_matches("A, B, C", "C, B & A")
    assert artist_matches("A, B and C", "A, B & C")


def test_three_plus_artist_does_not_match_under_credited_recordings():
    # Symmetric multi-credit rule: a recording credited to 3 artists must not match 1 or 2
    assert not artist_matches("A, B & C", "A")
    assert not artist_matches("A, B & C", "A & B")
    assert not artist_matches("A", "A, B & C")


def test_lyrics_lookup_artists_agree_handles_featured_artists():
    lookup = LyricsLookup(service=SimpleNamespace(settings=None))

    # Expected has featured artist, offered only has lead artist
    assert lookup._artists_agree(["Drake", "21 Savage"], ["Drake"])
    assert lookup._artists_agree(["Meek Mill", "Drake"], ["Meek Mill"])

    # Expected has lead artist, offered has featured artist
    assert lookup._artists_agree(["Drake"], ["Drake", "21 Savage"])

    # Expected has 3 artists, offered has lead
    assert lookup._artists_agree(["Artist A", "Artist B", "Artist C"], ["Artist A"])

    # Different primary artists sharing a guest must NOT agree
    assert not lookup._artists_agree(["Drake", "Future"], ["21 Savage", "Future"])

    # Completely different artists
    assert not lookup._artists_agree(["Adele"], ["Lionel Richie"])


# ==============================================================================
# BUG-WIN-012: Remix / versions without brackets or hyphens
# ==============================================================================

@pytest.mark.parametrize("title, expected_ver, expected_base", [
    ("In The End Remix", "remix", "In The End"),
    ("Numb Club Mix", "remix", "Numb"),
    ("Song Radio Edit", "remix", "Song"),
    ("Title Extended Mix", "remix", "Title"),
    ("Song Rework", "remix", "Song"),
    ("Bad Guy Sped Up", "sped", "Bad Guy"),
    ("Song Speed Up", "sped", "Song"),
    ("Day 'N' Nite Slowed", "slowed", "Day 'N' Nite"),
    ("Track Slowed + Reverb", "slowed", "Track"),
    ("Believer Instrumental", "instrumental", "Believer"),
    ("Shape of You Cover", "cover", "Shape of You"),
    ("Hotel California Live", "live", "Hotel California"),
    ("Song Acoustic", "acoustic", "Song"),
])
def test_title_metadata_unbracketed_versions(title, expected_ver, expected_base):
    meta = title_metadata(title)
    assert meta["version"] == expected_ver
    assert meta["base_title"] == expected_base


def test_title_metadata_plain_titles_not_falsely_stripped():
    meta = title_metadata("Stay Alive")
    assert meta["version"] == ""
    assert meta["base_title"] == "Stay Alive"

    meta2 = title_metadata("Remix")
    assert meta2["version"] == ""
    assert meta2["base_title"] == "Remix"


# ==============================================================================
# BUG-WIN-011: TrackResolver._is_plausible_match
# ==============================================================================

def test_track_resolver_min_score_raised():
    assert TRACK_MATCH_MIN_SCORE >= 0.8


def test_track_resolver_plausible_match_extracts_artist_from_video_title():
    # YouTube result where artist field is channel name, but video title contains artist
    top = {
        "title": "Queen - Bohemian Rhapsody (Official Video)",
        "artist": "HollywoodRecordsVEVO",
        "duration": 355.0,
    }
    assert TrackResolver._is_plausible_match("Bohemian Rhapsody", "Queen", top, expected_duration=355.0)


def test_track_resolver_plausible_match_rejects_low_similarity():
    top = {
        "title": "Everyday",
        "artist": "Adele",
        "duration": 200.0,
    }
    # "Yesterday" vs "Everyday" has similarity ~0.62, which was admitted by 0.6 but rejected by 0.8+
    assert not TrackResolver._is_plausible_match("Yesterday", "Adele", top, expected_duration=200.0)


# ==============================================================================
# BUG-WIN-034: Yandex Music in UI search
# ==============================================================================

def test_yandex_is_not_in_disabled_providers(api):
    # api.search with yandex source is dispatched and emits search_completed
    emitted = []
    api._emit = lambda event, data: emitted.append((event, data))
    api.search("hello", source="yandex")
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if any(e == "search_completed" and d.get("source") == "yandex" for e, d in emitted):
            break
        time.sleep(0.05)
    assert any(e == "search_completed" and d.get("source") == "yandex" for e, d in emitted)


# ==============================================================================
# BUG-WIN-037: convert_layout and fallback search
# ==============================================================================

def test_convert_layout_latin_to_cyrillic():
    assert convert_layout("vjkxfn") == "молчат"
    assert convert_layout("ghbdtn") == "привет"
    assert convert_layout("hello") == "руддщ"


def test_convert_layout_cyrillic_to_latin():
    assert convert_layout("молчат") == "vjkxfn"
    assert convert_layout("привет") == "ghbdtn"


def test_convert_layout_mixed_or_invalid():
    assert convert_layout("hello мир") == ""
    assert convert_layout("12345") == ""
    assert convert_layout("") == ""
    assert convert_layout(None) == ""


def test_local_search_fallback_with_convert_layout(api, tmp_db):
    tmp_db.add_track(title="Судно", artist="Молчат Дома", source="local", source_id="loc_molchat")
    emitted = []
    api._emit = lambda event, data: emitted.append((event, data))

    # Query typed in English layout "vjkxfn" for "молчат"
    api.search("vjkxfn", source="local")

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if any(e == "search_completed" for e, _ in emitted):
            break
        time.sleep(0.05)

    results = [d for e, d in emitted if e == "search_results"]
    assert any(r["source"] == "local" and any(t["artist"] == "Молчат Дома" for t in r.get("tracks", [])) for r in results)


# ==============================================================================
# BUG-WIN-006: Streaming search dedup and order stability
# ==============================================================================

def test_search_js_streaming_handles_reordered_results():
    from tests.jsdom import run_node, source
    import json

    raw = json.loads(source("search.js"))
    # Verify that the fix for BUG-WIN-006 is present:
    # 1. Checks prefix equality before appendOnly
    assert "trackDedupKey(childTrack) !== trackDedupKey(tracks[j])" in raw
    # 2. Replaces track list when order changes
    assert "renderSearchResultsBatch(container, tracks, true)" in raw
