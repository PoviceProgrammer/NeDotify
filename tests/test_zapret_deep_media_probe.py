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
    directories = []

    def run(args, checkpoint, timeout, on_line):
        assert args[args.index('--proxy') + 1] == ''
        assert args[args.index('--retries') + 1] == '0'
        assert args[args.index('--socket-timeout') + 1] == '4'
        assert '--no-cache-dir' in args
        assert '--cookies' not in args and '--cookies-from-browser' not in args
        checkpoint()
        template = args[args.index('-o') + 1]
        output = Path(template.replace('%(id)s', 'dQw4w9WgXcQ').replace('%(ext)s', 'm4a'))
        directories.append(output.parent)
        output.write_bytes(b'audio' * 1024)
        on_line('nd-file:' + str(output))

    monkeypatch.setattr('core.download_processing.run_tool', run)
    assert probe.probe_youtube_audio(lambda: False)
    assert directories and not directories[0].exists()


def test_cancelled_media_probe_cannot_start_a_download(monkeypatch):
    import services.youtube_service as youtube
    monkeypatch.setattr(youtube, 'YouTubeService', lambda **kwargs: pytest.fail('cancelled probe constructed provider'))
    assert not probe.probe_youtube_audio(lambda: True)
