"""Download startup avoids duplicate provider work; no live network required."""
import logging
import threading
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('cached_id', ['dQw4w9WgXcQ', '', 'https://invalid.example'])
def test_catalogue_download_reuses_only_valid_resolved_video_id(monkeypatch, tmp_path, cached_id):
    import services.youtube_service as module
    service = module.YouTubeService.__new__(module.YouTubeService)
    service.settings = None
    service.logger = logging.getLogger(__name__)
    service._ydl_lock = threading.Lock()
    service._get_ydl_opts = lambda *a, **k: {}
    service.get_from_cache = lambda key: {'source_id': cached_id}
    targets = []
    output = tmp_path / 'audio.webm'

    class Ydl:
        def __init__(self, opts):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, target, download):
            targets.append(target)
            assert download
            output.write_bytes(b'audio' * 1024)
            return {'ext': 'webm', 'acodec': 'opus'}
        def prepare_filename(self, info):
            return str(output)

    monkeypatch.setattr(module, 'HAS_YTDLP', True)
    monkeypatch.setattr(module.yt_dlp, 'YoutubeDL', Ydl)
    query = 'ytsearch1: Artist - Song'
    assert service.download_audio_sync(query, str(tmp_path)) == str(output)
    expected = f'https://www.youtube.com/watch?v={cached_id}' if cached_id == 'dQw4w9WgXcQ' else query
    assert targets == [expected]


def test_soundcloud_download_extracts_once_and_keeps_resume_hooks(monkeypatch, tmp_path):
    import services.soundcloud_service as module
    from core.download_transfer import DownloadContext
    service = module.SoundCloudService.__new__(module.SoundCloudService)
    service.logger = logging.getLogger(__name__)
    service.settings = SimpleNamespace(get=lambda section, key, default='':
                                      'http://127.0.0.1:8080' if key == 'proxy_url' else default)
    calls, options, progress = [], [], []
    info = {'id': '123', 'title': 'Song', 'ext': 'mp3', 'url': 'https://cdn.sndcdn.com/full.mp3'}
    output = tmp_path / 'audio.mp3'
    context = DownloadContext(1, 'soundcloud', '123', lambda: None,
                              lambda done, total: progress.append((done, total)))

    class Ydl:
        def __init__(self, opts):
            self.opts = opts
            options.append(opts)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, target, download):
            calls.append(target)
            assert not download, 'duplicate extraction during transfer'
            return info
        def process_ie_result(self, payload, download):
            assert payload is info and download
            assert self.opts['continuedl'] and not self.opts['overwrites']
            output.write_bytes(b'audio' * 1024)
            for hook in self.opts['progress_hooks']:
                hook({'downloaded_bytes': 5, 'total_bytes': 5})
            return payload
        def prepare_filename(self, payload):
            return str(output)

    monkeypatch.setattr(module, 'HAS_YTDLP', True)
    monkeypatch.setattr(module.yt_dlp, 'YoutubeDL', Ydl)
    assert service.download_audio_sync('123', str(tmp_path), context) == str(output)
    assert calls == ['https://api-v2.soundcloud.com/tracks/123']
    assert all(opts['proxy'] == 'http://127.0.0.1:8080' for opts in options)
    assert progress == [(5, 5)]


def test_soundcloud_probe_timeout_reaches_queue_retry_policy(monkeypatch, tmp_path):
    import services.soundcloud_service as module
    service = module.SoundCloudService.__new__(module.SoundCloudService)
    service.settings = None
    service.logger = logging.getLogger(__name__)
    class Ydl:
        def __init__(self, options):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, *args, **kwargs):
            raise TimeoutError('connection timed out')
    monkeypatch.setattr(module.yt_dlp, 'YoutubeDL', Ydl)
    with pytest.raises(TimeoutError):
        service.download_audio_sync('123', str(tmp_path))


def test_soundcloud_preview_fallback_verifies_recording(monkeypatch, tmp_path):
    import services.soundcloud_service as module
    import services.youtube_service as yt_module
    service = module.SoundCloudService.__new__(module.SoundCloudService)
    service.settings = None
    service.logger = logging.getLogger(__name__)
    class Ydl:
        def __init__(self, options):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, *args, **kwargs):
            return {'title': 'Song', 'uploader': 'Artist', 'duration': 180,
                    'url': 'https://cdn.sndcdn.com/preview/song.mp3'}
    calls = []
    provider = SimpleNamespace(
        search_sync=lambda *args, **kw: [
            {'source_id': 'wrong', 'title': 'Song (Live)', 'artist': 'Artist', 'duration': 180},
            {'source_id': 'right', 'title': 'Song', 'artist': 'Artist', 'duration': 180}],
        download_audio_sync=lambda sid, *args, **kw: (calls.append(sid), 'audio.mp3')[1])
    monkeypatch.setattr(module.yt_dlp, 'YoutubeDL', Ydl)
    monkeypatch.setattr(yt_module, 'YouTubeService', lambda settings: provider)
    assert service.download_audio_sync('123', str(tmp_path)) == 'audio.mp3'
    assert calls == ['right']
