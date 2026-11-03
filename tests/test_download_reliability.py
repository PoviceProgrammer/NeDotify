"""Failures remain recoverable without publishing truncated audio."""
from types import SimpleNamespace

import pytest
import requests

from core.download_transfer import DownloadContext, IncompleteDownload, DownloadInterrupted
from core.downloader import _RetryLater
from tests.audio_helpers import wave_bytes
from tests.test_download_resume import FakeResponse


def test_truncated_transfer_preserves_partial_for_retry(tmp_path, monkeypatch, downloader):
    path = tmp_path / 'song.mp3'
    response = FakeResponse(200, {'Content-Length': '10', 'ETag': '"same"'}, [b'12345'])
    monkeypatch.setattr('core.download_transfer.guarded_requests_get', lambda *a, **k: response)
    monkeypatch.setattr('core.download_transfer.is_safe_media_url', lambda url: True)
    ctx = DownloadContext(1, 'yandex', 'id', lambda: None, lambda *a: None)
    with pytest.raises(IncompleteDownload) as error:
        ctx.download_http('https://example.com/song.mp3', str(path))
    assert downloader._is_retryable_error(error.value)
    assert not path.exists()
    assert (tmp_path / 'song.mp3.part').read_bytes() == b'12345'
    assert response.closed


def test_corrupt_audio_retries_then_commits_good_file(downloader, tmp_db, redirect_home, emitted, monkeypatch):
    track_id = tmp_db.add_track(title='Song', artist='Artist', source='youtube', source_id='vid')
    tmp_db.download_queue_add(track_id, 'youtube', 'vid')
    folder = redirect_home / '.nedotify' / 'downloads'
    folder.mkdir(parents=True, exist_ok=True)
    output = folder / 'download.wav'
    attempts = []
    def download(*args, **kwargs):
        attempts.append(True)
        output.write_bytes(b'bad' if len(attempts) == 1 else wave_bytes())
        return str(output)
    monkeypatch.setattr(downloader._core.youtube, 'download_audio_sync', download)
    item = {'track_id': track_id, 'source': 'youtube', 'source_id': 'vid'}
    downloader._download_worker(item)
    assert not tmp_db.get_track(track_id)['is_downloaded']
    assert tmp_db.download_queue_get_status(track_id) == 'pending'
    assert not output.exists()
    assert not any(event == 'download_complete' for event, _ in emitted)
    downloader._download_worker(item)
    assert tmp_db.get_track(track_id)['is_downloaded']
    assert sum(event == 'download_complete' for event, _ in emitted) == 1


def test_retry_after_releases_worker_and_honours_delay(downloader, monkeypatch):
    error = requests.HTTPError('HTTP 429 Too Many Requests')
    error.response = SimpleNamespace(headers={'Retry-After': '90'})
    monkeypatch.setattr(downloader, '_fetch_from_provider', lambda *a: (_ for _ in ()).throw(error))
    with pytest.raises(_RetryLater) as retry:
        downloader._fetch_with_retry('youtube', 'vid', 'unused', 1, 0)
    assert retry.value.delay == 90


def test_connection_body_failure_is_retryable(downloader):
    assert downloader._is_retryable_error(requests.exceptions.ChunkedEncodingError('incomplete body'))
    assert not downloader._is_retryable_error(DownloadInterrupted())


def test_missing_fragments_cannot_be_silently_skipped(tmp_path):
    options = DownloadContext(1, 'youtube', 'id', lambda: None, lambda *a: None).ydl_options(str(tmp_path))
    assert options['skip_unavailable_fragments'] is False
    assert options['continuedl'] is True


def test_deezer_download_queue_keeps_catalogue_identity(downloader, tmp_db, emitted, redirect_home):
    tid = tmp_db.add_track(title='Song', artist='Artist', source='deezer', source_id='123')
    tmp_db.download_queue_add(tid, 'deezer', '123')
    def download(sid, folder, download_context=None):
        from pathlib import Path
        assert sid == '123' and download_context is not None
        output = Path(folder) / 'deezer.wav'
        output.write_bytes(wave_bytes())
        return str(output)
    downloader._core.deezer = SimpleNamespace(download_audio_sync=download)
    downloader._download_worker({'track_id': tid, 'source': 'deezer', 'source_id': '123'})
    row = tmp_db.get_track(tid)
    assert row['is_downloaded'] and row['source'] == 'deezer' and row['source_id'] == '123'
    assert any(event == 'download_complete' for event, _ in emitted)
