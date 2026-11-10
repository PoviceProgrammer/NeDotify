"""A healthy YouTube homepage alone must not pass calibration."""
from types import SimpleNamespace

import pytest
import requests

from services.zapret_service import ZapretService
import services.zapret_probe as probe


@pytest.mark.parametrize('media_reachable', [False, True])
def test_calibration_also_requires_a_real_audio_transfer(monkeypatch, media_reachable):
    service = ZapretService()
    class Session:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, *args, **kwargs): return self
        status_code = 200
    monkeypatch.setattr(requests, 'Session', Session)
    media_calls = []
    monkeypatch.setattr(probe, 'probe_youtube_audio',
                        lambda cancelled: media_calls.append(True) or media_reachable)
    assert service._probe_selection_youtube() is media_reachable
    assert media_calls == [True]


def test_probe_uses_no_user_credentials_and_cleans_its_download(monkeypatch):
    from pathlib import Path
    import services.youtube_service as youtube
    directories = []
    class Provider:
        def __init__(self, settings):
            assert settings is None
        def download_audio_sync(self, source_id, directory, download_context):
            directories.append(Path(directory))
            options = download_context.ydl_options(directory)
            assert options['proxy'] == ''
            assert options['retries'] == 0
            assert options['socket_timeout'] == 4
            assert 'cookiefile' not in options
            download_context.checkpoint()
            (Path(directory) / 'validated-audio.webm').write_bytes(b'provider-validated')
    monkeypatch.setattr(youtube, 'YouTubeService', Provider)
    assert probe.probe_youtube_audio(lambda: False)
    assert directories and not directories[0].exists()


def test_cancelled_media_probe_cannot_start_a_download(monkeypatch):
    import services.youtube_service as youtube
    monkeypatch.setattr(youtube, 'YouTubeService', lambda **kwargs: pytest.fail('cancelled probe constructed provider'))
    assert not probe.probe_youtube_audio(lambda: True)
