import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.api import AppApi
from core.database import DatabaseManager
from services.playlist_import_service import (
    PlaylistImportError,
    PlaylistImportService,
    UnsupportedPlaylistService,
)


class FakeYdl:
    def __init__(self, options, result):
        self.options = options
        self.result = result

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def extract_info(self, url, download=False):
        return self.result


def make_api(temp_dir, resolver):
    db = DatabaseManager(str(Path(temp_dir) / "playlist-import.db"))
    core = SimpleNamespace(
        db=db,
        playlist_importer=resolver,
        engine=None,
    )
    return AppApi(core), db


def test_resolver_normalizes_supported_playlist_without_network():
    result = {
        "title": "Road Trip",
        "entries": [
            {
                "id": "abc123",
                "title": "First Song",
                "uploader": "First Artist",
                "duration": 125,
                "thumbnail": "https://img.example/first.jpg",
            },
            {
                "id": "def456",
                "title": "Second Song",
                "artist": "Second Artist",
                "duration": "210",
                "webpage_url": "https://www.youtube.com/watch?v=def456",
            },
        ],
    }
    factory = lambda options: FakeYdl(options, result)
    resolved = PlaylistImportService(ydl_factory=factory).resolve(
        "https://www.youtube.com/playlist?list=test"
    )

    assert resolved["name"] == "Road Trip"
    assert len(resolved["tracks"]) == 2
    assert resolved["tracks"][0] == {
        "title": "First Song",
        "artist": "First Artist",
        "album": "Unknown Album",
        "duration": 125.0,
        "source": "youtube",
        "source_id": "abc123",
        "source_url": "https://www.youtube.com/watch?v=abc123",
        "cover_url": "https://img.example/first.jpg",
    }


def test_resolver_rejects_services_without_playlist_resolver():
    service = PlaylistImportService(ydl_factory=MagicMock())

    for url in (
        "https://open.spotify.com/playlist/example",
        "https://vk.com/music/playlist/example",
    ):
        try:
            service.resolve(url)
        except UnsupportedPlaylistService as exc:
            assert "YouTube" in str(exc)
        else:
            raise AssertionError(f"Unsupported playlist resolver accepted: {url}")


def test_api_imports_resolved_tracks_into_created_playlist():
    resolver = MagicMock()
    resolver.resolve.return_value = {
        "name": "Resolved Playlist",
        "source": "youtube",
        "tracks": [
            {
                "title": "Imported Song",
                "artist": "Imported Artist",
                "album": "Imported Album",
                "duration": 181,
                "source": "youtube",
                "source_id": "video-1",
                "source_url": "https://www.youtube.com/watch?v=video-1",
                "cover_url": "https://img.example/cover.jpg",
            }
        ],
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        api, db = make_api(temp_dir, resolver)

        result = api.import_external_playlist(
            "https://www.youtube.com/playlist?list=test", ""
        )

        assert result["success"] is True
        assert result["imported_count"] == 1
        playlists = db.get_playlists()
        assert playlists[0]["name"] == "Resolved Playlist"
        assert playlists[0]["track_count"] == 1
        playlist_id = result["playlist_id"]
        assert isinstance(playlist_id, int)
        tracks = db.get_playlist_tracks(playlist_id)
        assert tracks[0]["source_id"] == "video-1"
        assert tracks[0]["source_url"].endswith("video-1")
        assert tracks[0]["cover_url"].endswith("cover.jpg")
        db.close()


def test_api_does_not_create_playlist_for_empty_result():
    resolver = MagicMock()
    resolver.resolve.return_value = {"name": "Empty", "tracks": []}
    with tempfile.TemporaryDirectory() as temp_dir:
        api, db = make_api(temp_dir, resolver)

        result = api.import_external_playlist(
            "https://www.youtube.com/playlist?list=empty"
        )

        assert result["success"] is False
        error = result["error"]
        assert isinstance(error, str)
        assert "не найдено" in error
        assert db.get_playlists() == []
        db.close()


def test_api_removes_playlist_when_database_add_fails():
    resolver = MagicMock()
    resolver.resolve.return_value = {
        "name": "Broken Import",
        "tracks": [{
            "title": "Track",
            "artist": "Artist",
            "source": "youtube",
            "source_id": "track-id",
        }],
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        api, db = make_api(temp_dir, resolver)
        db.add_to_playlist = MagicMock(return_value=False)

        result = api.import_external_playlist(
            "https://www.youtube.com/playlist?list=broken"
        )

        assert result["success"] is False
        assert db.get_playlists() == []
        db.close()


def test_api_does_not_create_playlist_for_failed_resolution():
    resolver = MagicMock()
    resolver.resolve.side_effect = PlaylistImportError("В плейлисте нет треков")
    with tempfile.TemporaryDirectory() as temp_dir:
        api, db = make_api(temp_dir, resolver)

        result = api.import_external_playlist(
            "https://music.yandex.ru/users/test/playlists/1"
        )

        assert result == {"success": False, "error": "В плейлисте нет треков"}
        assert db.get_playlists() == []
        db.close()
