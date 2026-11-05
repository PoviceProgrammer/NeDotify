from types import SimpleNamespace

import pytest

from services.yandex_service import YandexService


@pytest.mark.parametrize(("value", "expected"), [
    ("12345", "12345"),
    ("yandex:12345", "12345"),
    ("https://music.yandex.ru/album/7/track/12345", "12345"),
    ("https://music.yandex.com/track/12345", "12345"),
    ("https://music.yandex.ru.evil.test/track/12345", ""),
    ("https://example.test/track/12345", ""),
    ("https://music.yandex.ru/album/7", ""),
    ("not-an-id", ""),
])
def test_track_id_normalization(value, expected):
    assert YandexService._extract_track_id(value) == expected


def test_download_accepts_yandex_track_url_and_passes_numeric_id(tmp_path):
    seen = []

    class DownloadInfo:
        codec = "mp3"
        bitrate_in_kbps = 192

        def get_direct_link(self):
            return "https://music.yandex.ru/audio"

    track = SimpleNamespace(get_download_info=lambda: [DownloadInfo()])
    client = SimpleNamespace(tracks=lambda ids: seen.append(ids) or [track])
    service = YandexService.__new__(YandexService)
    service._get_client = lambda: client

    class Context:
        stem = "download_42"

        def checkpoint(self):
            pass

        def download_http(self, url, output_path):
            assert url == "https://music.yandex.ru/audio"
            return output_path

    result = service.download_audio_sync(
        "https://music.yandex.ru/album/7/track/12345", str(tmp_path), Context())

    assert seen == [["12345"]]
    assert result == str(tmp_path / "download_42.mp3")
