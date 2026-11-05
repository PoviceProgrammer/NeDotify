"""YouTube Music radio supplies related metadata without opening media streams."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from services.youtube_service import YouTubeService


SEED = "dQw4w9WgXcQ"
FIRST = "HJIGwE11_qw"
SECOND = "9mWr4c_ig54"
THIRD = "E0S4W34zFMA"


def track(video_id=FIRST, **fields):
    return {
        "videoId": video_id,
        "title": "Related song",
        "length": "3:07",
        "artists": [{"name": "Artist"}],
        "thumbnail": [{"url": "https://images.example/cover.jpg"}],
        **fields,
    }


@pytest.mark.parametrize('metric', ['Отметок "Нравится": 831 тыс.', '16K likes', '1.2M views'])
def test_radio_engagement_labels_are_not_artist_credits(youtube, metric):
    youtube._ytmusic.get_watch_playlist.return_value = {'tracks': [track(
        artists=[{'name': 'Bones', 'id': 'UC-real-channel'}, {'name': metric, 'id': None}]) ]}
    result = youtube.get_related_tracks_sync(SEED)
    assert result[0]['artist'] == 'Bones'


@pytest.fixture
def youtube(monkeypatch):
    # Avoid service construction: no sessions, executors, cookies or profile I/O.
    svc = YouTubeService.__new__(YouTubeService)
    svc._ytmusic = SimpleNamespace(get_watch_playlist=Mock(return_value={"tracks": [track()]}))
    monkeypatch.setattr(YouTubeService, "_search_cache", {})
    svc.get_stream_url = Mock(side_effect=AssertionError("Related tracks must not resolve audio"))
    svc._extract_info_safe = Mock(side_effect=AssertionError("Related tracks must not run yt-dlp"))
    return svc


def test_radio_metadata_has_playable_app_shape_and_preserves_fields(youtube):
    youtube._ytmusic.get_watch_playlist.return_value = {"tracks": [track(
        artists=[{"name": " First "}, {"name": "Second"}],
        length="1:02:03", album={"name": "Album"},
        thumbnail=[{"url": "https://images.example/small.jpg"},
                   {"url": "https://images.example/large.jpg"}],
    )]}

    assert youtube.get_related_tracks_sync(SEED, limit=3) == [{
        "source": "youtube", "source_id": FIRST, "title": "Related song",
        "artist": "First, Second", "duration": 3723,
        "cover_url": "https://images.example/large.jpg", "album": "Album",
    }]
    youtube._ytmusic.get_watch_playlist.assert_called_once_with(
        videoId=SEED, limit=4, radio=True,
    )
    youtube.get_stream_url.assert_not_called()
    youtube._extract_info_safe.assert_not_called()


def test_seed_unavailable_invalid_and_duplicate_entries_do_not_use_limit(youtube):
    youtube._ytmusic.get_watch_playlist.return_value = {"tracks": [
        track(SEED), track(FIRST, isAvailable=False), track(FIRST, isPlayable=False),
        track(FIRST, unplayableText="blocked"), track("bad"), None,
        track(FIRST, title="  "), track(FIRST), track(FIRST), track(SECOND), track(THIRD),
    ]}

    assert [t["source_id"] for t in youtube.get_related_tracks_sync(SEED, 2)] == [FIRST, SECOND]


@pytest.mark.parametrize("seed", [None, "", "ytsearch1:artist", "https://youtu.be/dQw4w9WgXcQ", "bad"])
def test_invalid_seed_never_requests_provider(youtube, seed):
    assert youtube.get_related_tracks_sync(seed) == []
    youtube._ytmusic.get_watch_playlist.assert_not_called()


@pytest.mark.parametrize("limit", [0, -1, None, "bad", float("inf")])
def test_invalid_limit_never_requests_provider(youtube, limit):
    assert youtube.get_related_tracks_sync(SEED, limit) == []
    youtube._ytmusic.get_watch_playlist.assert_not_called()


def test_limit_is_bounded_and_provider_may_return_more_than_requested(youtube):
    youtube._ytmusic.get_watch_playlist.return_value = {"tracks": [track(), track(SECOND)]}
    assert len(youtube.get_related_tracks_sync(SEED, 1)) == 1
    assert len(youtube.get_related_tracks_sync(SEED, 9999)) == 2
    assert youtube._ytmusic.get_watch_playlist.call_args.kwargs["limit"] == 51


@pytest.mark.parametrize("value,expected", [
    (123, 123), (123.9, 123), ("03:07", 187), ("1:02:03", 3723), ("120", 120),
    (-2, 0), (float("inf"), 0), (float("nan"), 0), ("3:99", 0), ("live", 0),
    ("-4", 0), (None, 0), (True, 0),
])
def test_duration_parsing_is_safe(youtube, value, expected):
    youtube._ytmusic.get_watch_playlist.return_value = {"tracks": [track(length=value)]}
    assert youtube.get_related_tracks_sync(SEED)[0]["duration"] == expected


def test_numeric_duration_and_alternate_thumbnails_are_supported(youtube):
    youtube._ytmusic.get_watch_playlist.return_value = {"tracks": [track(
        duration_seconds=225, length="bad", artists=[None, {"name": None}],
        thumbnail=None, thumbnails=[None, {"url": "https://images.example/cover.jpg"}],
        album=None,
    )]}
    result = youtube.get_related_tracks_sync(SEED)[0]
    assert result["duration"] == 225
    assert result["artist"] == "Unknown Artist"
    assert result["cover_url"] == "https://images.example/cover.jpg"
    assert result["album"] == ""


def test_cache_separates_seed_and_limit_and_callers_cannot_mutate_it(youtube):
    result = youtube.get_related_tracks_sync(SEED, 2)
    result[0]["title"] = "Changed by caller"
    result.clear()
    assert youtube.get_related_tracks_sync(SEED, 2)[0]["title"] == "Related song"
    assert youtube._ytmusic.get_watch_playlist.call_count == 1
    youtube.get_related_tracks_sync(SEED, 3)
    youtube.get_related_tracks_sync(SECOND, 2)
    assert youtube._ytmusic.get_watch_playlist.call_count == 3


def test_related_cache_expires_without_extending_ttl_on_read(youtube, monkeypatch):
    import services.base_service as base_module
    now = [100.0]
    monkeypatch.setattr(base_module, "time", SimpleNamespace(time=lambda: now[0]))
    youtube.get_related_tracks_sync(SEED)
    now[0] += YouTubeService._SEARCH_CACHE_TTL - 1
    youtube.get_related_tracks_sync(SEED)
    assert youtube._ytmusic.get_watch_playlist.call_count == 1
    now[0] += 2
    youtube.get_related_tracks_sync(SEED)
    assert youtube._ytmusic.get_watch_playlist.call_count == 2


def test_related_results_use_existing_size_bounded_lru_cache(youtube, monkeypatch):
    monkeypatch.setattr(YouTubeService, "_SEARCH_CACHE_MAX_SIZE", 2)
    youtube.get_related_tracks_sync(SEED)
    youtube.get_related_tracks_sync(SECOND)
    youtube.get_related_tracks_sync(SEED)  # Keep the first seed recent.
    youtube.get_related_tracks_sync(THIRD)
    youtube.get_related_tracks_sync(SEED)
    assert youtube._ytmusic.get_watch_playlist.call_count == 3
    youtube.get_related_tracks_sync(SECOND)
    assert youtube._ytmusic.get_watch_playlist.call_count == 4


def test_provider_error_does_not_poison_cache_and_later_request_can_recover(youtube):
    youtube._ytmusic.get_watch_playlist.side_effect = [RuntimeError("unavailable"), {"tracks": [track()]}]
    assert youtube.get_related_tracks_sync(SEED) == []
    assert youtube.get_related_tracks_sync(SEED)[0]["source_id"] == FIRST
    assert youtube._ytmusic.get_watch_playlist.call_count == 2


@pytest.mark.parametrize("response", [None, [], {"tracks": None}, {"tracks": "invalid"}])
def test_missing_provider_content_returns_empty_list(youtube, response):
    youtube._ytmusic.get_watch_playlist.return_value = response
    assert youtube.get_related_tracks_sync(SEED) == []


def test_missing_ytmusic_is_safe(youtube):
    youtube._ytmusic = None
    assert youtube.get_related_tracks_sync(SEED) == []
