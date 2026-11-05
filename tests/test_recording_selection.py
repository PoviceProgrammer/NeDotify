"""services/recording_selection.py — the single verified-choice gate.

Spec scenarios from the audio-zone fix plan: original vs remix, live vs
studio, equal titles by different artists, unavailable first hit, and the
re-resolve-must-return-the-same-recording requirement (persisted video id).
No real network: providers are synchronous stubs.
"""

import pytest

from services.recording_selection import (
    remember_video_id,
    remembered_video_id,
    search_verified,
    select_recording,
    stream_matches,
)

ORIGINAL = {"title": "Выхода нет", "artist": "Сплин", "duration": 240.0}


class _Settings:
    def __init__(self):
        self.data = {}

    def get(self, category, key, default=None):
        return self.data.get((category, key), default)

    def set(self, category, key, value):
        self.data[(category, key)] = value


class _Provider:
    """Synchronous search stub returning canned result batches."""

    def __init__(self, results=None, error=None):
        self.results = results or []
        self.error = error
        self.calls = []

    def search(self, query, max_results=20, callback=None, error_callback=None):
        self.calls.append((query, max_results))
        if self.error is not None:
            error_callback(self.error)
            return None
        callback(self.results[:max_results] if max_results < len(self.results) else self.results)
        return None


def _yt(video_id, title, artist, duration, result_type="song"):
    return {"source": "youtube", "source_id": video_id, "title": title,
            "artist": artist, "duration": duration, "resultType": result_type}


# --------------------------------------------------------------------------- #
# select_recording
# --------------------------------------------------------------------------- #

def test_selects_the_exact_recording():
    candidates = [_yt("aaa11111111", "Выхода нет", "Сплин", 240)]
    assert select_recording(ORIGINAL, candidates) is candidates[0]


def test_remix_is_rejected_when_the_original_was_requested():
    candidates = [_yt("aaa11111111", "Выхода нет (Remix)", "Сплин", 240)]
    assert select_recording(ORIGINAL, candidates) is None


def test_live_version_is_rejected_for_the_studio_recording():
    candidates = [_yt("aaa11111111", "Выхода нет (Live)", "Сплин", 260)]
    assert select_recording(ORIGINAL, candidates) is None


def test_same_title_by_another_artist_is_rejected():
    candidates = [_yt("aaa11111111", "Выхода нет", "Кино", 240)]
    assert select_recording(ORIGINAL, candidates) is None


def test_duration_outside_tolerance_is_rejected():
    long_version = _yt("aaa11111111", "Выхода нет", "Сплин", 320)
    assert select_recording(ORIGINAL, [long_version]) is None


def test_closest_duration_wins_among_verified_candidates():
    near = _yt("aaa11111111", "Выхода нет", "Сплин", 241)
    far = _yt("bbb22222222", "Выхода нет", "Сплин", 250)
    assert select_recording(ORIGINAL, [far, near]) is near


def test_provider_song_result_is_preferred_over_a_video_result():
    song = _yt("aaa11111111", "Выхода нет", "Сплин", 240, result_type="song")
    video = _yt("bbb22222222", "Выхода нет", "Сплин", 240, result_type="video")
    assert select_recording(ORIGINAL, [video, song]) is song


def test_no_convincing_match_returns_none():
    assert select_recording(ORIGINAL, []) is None
    assert select_recording(ORIGINAL, [{"title": "Совсем другое"}]) is None
    assert select_recording(ORIGINAL, [None, 42]) is None


def test_track_without_title_selects_nothing():
    assert select_recording({"title": ""}, [_yt("a", "x", "y", 1)]) is None


# --------------------------------------------------------------------------- #
# search_verified
# --------------------------------------------------------------------------- #

def test_first_hit_unavailable_but_second_verifies():
    """The right recording often sits below a remix: the search must keep
    looking instead of trusting the provider's ranking."""
    provider = _Provider(results=[
        _yt("aaa11111111", "Выхода нет (Nightcore)", "Сплин", 180),
        _yt("bbb22222222", "Выхода нет", "Сплин", 240),
    ])
    found = search_verified(provider, ORIGINAL, limit=5)
    assert found is not None and found["source_id"] == "bbb22222222"
    assert provider.calls[0][1] == 5, "fallback searches must look past the top hit"


def test_search_with_no_verified_candidate_returns_none():
    provider = _Provider(results=[_yt("aaa11111111", "Выхода нет (Live)", "Сплин", 255)])
    assert search_verified(provider, ORIGINAL) is None


def test_search_without_a_provider_or_title_is_a_no_op():
    assert search_verified(None, ORIGINAL) is None
    provider = _Provider(results=[_yt("a", "b", "c", 1)])
    assert search_verified(provider, {"title": " "}) is None
    assert provider.calls == []


# --------------------------------------------------------------------------- #
# stream_matches
# --------------------------------------------------------------------------- #

def test_direct_id_short_circuits_metadata_comparison():
    """The provider resolved exactly the id we addressed: same recording by
    construction, even if the title spelling differs from the catalogue."""
    metadata = {"title": "Some Raw Video Title", "artist": "Whatever - Topic",
                "duration": 999, "source_id": "abc12345678"}
    assert stream_matches(ORIGINAL, metadata, requested_id="abc12345678")


def test_metadata_mismatch_rejects_a_search_derived_stream():
    metadata = {"title": "Выхода нет (Extended Mix)", "artist": "Сплин",
                "duration": 300, "source_id": "zzz99999999"}
    assert not stream_matches(ORIGINAL, metadata, requested_id=None)


def test_matching_metadata_is_accepted():
    metadata = {"title": "Выхода нет", "artist": "Сплин",
                "duration": 241, "source_id": "zzz99999999"}
    assert stream_matches(ORIGINAL, metadata)


def test_metadata_without_a_title_is_not_rejected():
    assert stream_matches(ORIGINAL, None)
    assert stream_matches(ORIGINAL, {"duration": 1})


# --------------------------------------------------------------------------- #
# persisted recording identity (BUG-A1-002)
# --------------------------------------------------------------------------- #

def test_remembered_video_id_roundtrip():
    settings = _Settings()
    assert remembered_video_id(settings, "spotify", "ytsearch1: A - B") == ""
    remember_video_id(settings, "spotify", "ytsearch1: A - B", "dQw4w9WgXcQ")
    assert remembered_video_id(settings, "spotify", "ytsearch1: A - B") == "dQw4w9WgXcQ"


def test_remember_rejects_non_video_ids():
    settings = _Settings()
    remember_video_id(settings, "spotify", "k", "not-a-video-id")
    remember_video_id(settings, "spotify", "k", "")
    assert remembered_video_id(settings, "spotify", "k") == ""


def test_remember_ignores_non_spotify_sources():
    settings = _Settings()
    remember_video_id(settings, "youtube", "k", "dQw4w9WgXcQ")
    assert remembered_video_id(settings, "youtube", "k") == ""


def test_remember_survives_a_fresh_settings_instance(tmp_path):
    """The value goes through the settings store, so it is durable."""
    from core.settings import SettingsManager
    from core.database import DatabaseManager
    db = DatabaseManager(str(tmp_path / "s.db"))
    try:
        store = SettingsManager(db)
        remember_video_id(store, "spotify", "ytsearch1: Сплин - Выхода нет", "dQw4w9WgXcQ")
        store.flush()
        reopened = SettingsManager(DatabaseManager(str(tmp_path / "s.db")))
        assert remembered_video_id(reopened, "spotify",
                                   "ytsearch1: Сплин - Выхода нет") == "dQw4w9WgXcQ"
    finally:
        db.close()
