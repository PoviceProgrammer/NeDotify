"""Provider downloads use the shared CLI and retain recording identity."""
from types import SimpleNamespace

import pytest

from core.download_processing import ToolExecutionError
from core.download_transfer import DownloadContext


@pytest.mark.parametrize('cached_id', ['dQw4w9WgXcQ', '', 'https://invalid.example'])
def test_catalogue_download_reuses_only_valid_resolved_video_id(monkeypatch, tmp_path, cached_id):
    from services.youtube_service import YouTubeService

    service = YouTubeService.__new__(YouTubeService)
    service.settings = None
    service.get_from_cache = lambda key: {'source_id': cached_id}
    targets = []
    output = tmp_path / 'audio.webm'
    output.write_bytes(b'audio' * 1024)

    def transfer(self, target, directory):
        targets.append(target)
        assert directory == str(tmp_path)
        return str(output)

    monkeypatch.setattr(DownloadContext, 'download_executable', transfer)
    query = 'ytsearch1: Artist - Song'
    assert service.download_audio_sync(query, str(tmp_path)) == str(output)
    expected = f'https://www.youtube.com/watch?v={cached_id}' if cached_id == 'dQw4w9WgXcQ' else query
    assert targets == [expected]


def test_soundcloud_download_uses_one_process_and_excludes_previews(monkeypatch, tmp_path):
    import sys
    from services.soundcloud_service import SoundCloudService

    service = SoundCloudService.__new__(SoundCloudService)
    service.settings = SimpleNamespace(get=lambda section, key, default='':
                                      'http://127.0.0.1:8080' if key == 'proxy_url' else default)
    calls, progress = [], []
    context = DownloadContext(1, 'soundcloud', '123', lambda: None,
                              lambda done, total: progress.append((done, total)), service.settings)
    output = tmp_path / (context.stem + '_123.mp3')

    def run(args, checkpoint, timeout, on_line):
        calls.append(args)
        assert args[:3] == [sys.executable, '-m', 'yt_dlp']
        assert args[-2:] == ['--', 'https://api-v2.soundcloud.com/tracks/123']
        assert args[args.index('-f') + 1] == 'bestaudio[format_id!*=preview]'
        assert args[args.index('--proxy') + 1] == 'http://127.0.0.1:8080'
        assert '--continue' in args and '--no-overwrites' in args
        output.write_bytes(b'audio' * 1024)
        on_line('nd-progress:5:5')
        on_line('nd-file:' + str(output))

    monkeypatch.setattr('core.download_processing.run_tool', run)
    assert service.download_audio_sync('123', str(tmp_path), context) == str(output)
    assert len(calls) == 1
    assert progress == [(5, 5)]


def test_soundcloud_transfer_timeout_reaches_queue_retry_policy(monkeypatch, tmp_path):
    from services.soundcloud_service import SoundCloudService

    service = SoundCloudService.__new__(SoundCloudService)
    service.settings = None

    def transfer(*args, **kwargs):
        raise TimeoutError('connection timed out')

    monkeypatch.setattr(DownloadContext, 'download_executable', transfer)
    with pytest.raises(TimeoutError):
        service.download_audio_sync('123', str(tmp_path))


@pytest.mark.parametrize('youtube_enabled', [True, False])
def test_soundcloud_preview_fallback_verifies_recording(monkeypatch, tmp_path, youtube_enabled):
    from services.soundcloud_service import SoundCloudService

    service = SoundCloudService.__new__(SoundCloudService)
    service.settings = SimpleNamespace(get=lambda section, key, default=True: youtube_enabled)
    service.get_from_cache = lambda key: {'title': 'Song', 'artist': 'Artist', 'duration': 180}
    calls = []
    provider = SimpleNamespace(
        search_sync=lambda *args, **kw: [
            {'source_id': 'wrong', 'title': 'Song (Live)', 'artist': 'Artist', 'duration': 180},
            {'source_id': 'right', 'title': 'Song', 'artist': 'Artist', 'duration': 180}],
        download_audio_sync=lambda sid, *args, **kw: (calls.append(sid), 'audio.mp3')[1])
    service._get_youtube_fallback = lambda: provider

    def transfer(*args, **kwargs):
        raise ToolExecutionError(1, 'Requested format is not available')

    monkeypatch.setattr(DownloadContext, 'download_executable', transfer)
    if youtube_enabled:
        assert service.download_audio_sync('123', str(tmp_path)) == 'audio.mp3'
        assert calls == ['right']
    else:
        with pytest.raises(ToolExecutionError):
            service.download_audio_sync('123', str(tmp_path))
        assert calls == []
