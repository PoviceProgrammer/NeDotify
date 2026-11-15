"""Persistent queue controls and real partial-transfer resume without network I/O."""

import json
import os
import threading
import time

import pytest

from core.download_transfer import DownloadContext, DownloadInterrupted
from core.downloader import DownloadManager
from core.download_store import DownloadStore


def _wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError('Download state did not settle')


def _start_processor(manager):
    manager._processor_thread.join(timeout=2)
    assert not manager._processor_thread.is_alive()
    manager._running = True
    manager._processor_thread = threading.Thread(target=manager._process_queue, daemon=True)
    manager._processor_thread.start()


def test_download_store_rows_does_not_take_database_write_lock(tmp_db):
    track_id = tmp_db.add_track(title="Queue row", artist="Artist", source="youtube",
                                source_id="queue-row")
    tmp_db.download_queue_add(track_id, "youtube", "queue-row")
    store = DownloadStore(tmp_db)

    class ForbiddenWriteLock:
        def __enter__(self):
            raise AssertionError("read-only queue listing took the database write lock")

        def __exit__(self, *_args):
            return False

    tmp_db._write_lock = ForbiddenWriteLock()
    rows = store.rows()
    assert len(rows) == 1
    assert rows[0]["track_id"] == track_id


class PartialProvider:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.offsets = []
        self.paths = []

    def download_audio_sync(self, source_id, output_dir, download_context=None):
        path = os.path.join(output_dir, download_context.stem + '.mp3')
        partial = path + '.part'
        offset = os.path.getsize(partial) if os.path.isfile(partial) else 0
        self.offsets.append(offset)
        self.paths.append(path)
        if not offset:
            with open(partial, 'wb') as audio_file:
                from tests.audio_helpers import wave_bytes
                audio_file.write(wave_bytes()[:8192])
            download_context.progress(8192, 16384)
            self.started.set()
            assert self.release.wait(5)
            download_context.checkpoint()
        with open(partial, 'ab') as audio_file:
            from tests.audio_helpers import wave_bytes
            audio_file.write(wave_bytes()[8192:])
        download_context.progress(16384, 16384)
        download_context.checkpoint()
        os.replace(partial, path)
        return path


def test_inflight_pause_resume_waits_for_old_worker_and_reuses_partial(
        downloader, core_ns, tmp_db, emitted, redirect_home):
    provider = PartialProvider()
    core_ns.youtube = provider
    track_id = tmp_db.add_track(title='Resume', artist='Artist', source='youtube', source_id='resume')
    _start_processor(downloader)
    downloader.queue_download(track_id, 'youtube', 'resume')
    try:
        assert provider.started.wait(5)
        assert downloader.pause_download(track_id) == {'success': True, 'count': 1}
        state = downloader.get_downloads()[0]
        assert state['status'] == 'paused'
        assert state['downloaded_bytes'] == 8192
        assert state['percent'] == 50
        assert downloader.resume_download(track_id) == {'success': True, 'count': 1}
        time.sleep(0.1)
        assert provider.offsets == [0]
        provider.release.set()
        _wait_until(lambda: tmp_db.download_queue_get_status(track_id) == 'completed')
        assert provider.offsets == [0, 8192]
        assert provider.paths[0] == provider.paths[1]
        # The transfer is resumed at the same staging path, then tags are
        # embedded and the audio is atomically published under its final name.
        final_path = tmp_db.get_track(track_id)['file_path']
        assert os.path.getsize(final_path) >= 16384
        from utils.audio_validation import audio_duration
        assert audio_duration(final_path) > 0
        assert not [payload for name, payload in emitted if name == 'download_failed']
        state = downloader.get_downloads()[0]
        assert state['percent'] == 100
        assert state['downloaded_bytes'] == state['total_bytes'] == os.path.getsize(final_path)
        json.dumps(state)
    finally:
        provider.release.set()
        downloader.stop()


def test_paused_partial_survives_manager_restart(core_ns, tmp_db, redirect_home):
    provider = PartialProvider()
    core_ns.youtube = provider
    track_id = tmp_db.add_track(title='Persistent', artist='Artist', source='youtube', source_id='persistent')
    first = DownloadManager(core_ns)
    second = None
    try:
        first.queue_download(track_id, 'youtube', 'persistent')
        assert provider.started.wait(5)
        first.pause_download(track_id)
        provider.release.set()
        _wait_until(lambda: not first._running_futures())
        first.stop()
        second = DownloadManager(core_ns)
        assert tmp_db.download_queue_get_status(track_id) == 'paused'
        assert provider.offsets == [0]
        assert second.get_downloads()[0]['downloaded_bytes'] == 8192
        second.resume_download(track_id)
        _wait_until(lambda: tmp_db.download_queue_get_status(track_id) == 'completed')
        assert provider.offsets == [0, 8192]
    finally:
        provider.release.set()
        first.stop()
        if second:
            second.stop()


def test_shutdown_interruption_resumes_automatically(core_ns, tmp_db, redirect_home):
    provider = PartialProvider()
    core_ns.youtube = provider
    track_id = tmp_db.add_track(title='Shutdown', artist='Artist', source='youtube', source_id='shutdown')
    first = DownloadManager(core_ns)
    second = None
    try:
        first.queue_download(track_id, 'youtube', 'shutdown')
        assert provider.started.wait(5)
        stopper = threading.Thread(target=first.stop)
        stopper.start()
        _wait_until(lambda: not first._running)
        provider.release.set()
        stopper.join(5)
        assert not stopper.is_alive()
        assert tmp_db.get_track(track_id)['is_downloaded'] == 0
        second = DownloadManager(core_ns)
        _wait_until(lambda: tmp_db.download_queue_get_status(track_id) == 'completed')
        assert provider.offsets == [0, 8192]
    finally:
        provider.release.set()
        first.stop()
        if second:
            second.stop()


def test_retry_failed_keeps_completed_and_paused_untouched(downloader, tmp_db, redirect_home):
    states = ['completed', 'failed', 'paused', 'cancelled']
    identifiers = []
    for status in states:
        track_id = tmp_db.add_track(title=status, artist='Artist', source='youtube', source_id=status)
        tmp_db.download_queue_add(track_id, 'youtube', status)
        tmp_db.download_queue_set_status(track_id, status)
        identifiers.append(track_id)
    result = downloader.retry_failed_downloads()
    assert result == {'success': True, 'count': 1}
    assert [item['track_id'] for item in downloader._queue] == [identifiers[1]]
    assert [tmp_db.download_queue_get_status(track_id) for track_id in identifiers] == [
        'completed', 'pending', 'paused', 'cancelled']


def test_progress_is_throttled_without_losing_latest_partial(downloader, tmp_db, emitted):
    tmp_db.conn.execute("INSERT INTO tracks(id,title) VALUES(101,'Progress')")
    tmp_db.conn.commit()
    tmp_db.download_queue_add(101, 'youtube', 'progress')
    for downloaded in range(1000):
        downloader._record_progress(101, downloaded, 2000)
    events = [payload for name, payload in emitted if name == 'download_progress']
    assert len(events) == 1
    downloader._record_progress(101, 999, 2000, force=True)
    assert downloader.get_downloads()[0]['downloaded_bytes'] == 999


@pytest.mark.parametrize('raw,code,action', [
    ('No space left on device', 'disk_full', 'storage'),
    ('Connection timed out', 'network', 'retry'),
    ('файл не найден', 'file_missing', 'library'),
    ('Provider refused the transfer', 'unexpected', 'retry'),
])
def test_download_error_keeps_raw_detail_and_adds_serializable_action(
        downloader, emitted, raw, code, action):
    original = {'track_id': 27, 'error': raw}
    downloader._emit('download_failed', original)
    payload = next(payload for name, payload in emitted if name == 'download_failed')
    assert payload['track_id'] == 27
    assert payload['error'] == payload['message']
    assert raw not in payload['error']
    assert payload['method'] == 'download_track'
    assert payload['code'] == code
    assert payload['action'] == action
    assert payload['title']
    assert payload['message']
    assert original == {'track_id': 27, 'error': raw}
    json.dumps(payload, ensure_ascii=False)


class FakeResponse:
    def __init__(self, status, headers, chunks):
        self.status_code = status
        self.headers = headers
        self.chunks = chunks
        self.closed = False

    def iter_content(self, chunk_size):
        yield from self.chunks

    def raise_for_status(self):
        if self.status_code >= 400:
            raise IOError(str(self.status_code))

    def close(self):
        self.closed = True


def test_http_resume_sends_validated_range_and_appends(tmp_path, monkeypatch):
    output = str(tmp_path / 'audio.mp3')
    with open(output + '.part', 'wb') as audio_file:
        audio_file.write(b'a' * 8192)
    with open(output + '.part.json', 'w') as metadata_file:
        json.dump({'etag': '"same-recording"'}, metadata_file)
    response = FakeResponse(206, {'Content-Range': 'bytes 8192-16383/16384', 'ETag': '"same-recording"'}, [b'b' * 8192])
    calls = []

    def request(url, **options):
        calls.append(options)
        return response

    monkeypatch.setattr('core.download_transfer.guarded_requests_get', request)
    monkeypatch.setattr('core.download_transfer.is_safe_media_url', lambda url: True)
    context = DownloadContext(1, 'yandex', 'id', lambda: None, lambda downloaded, total: None)
    assert context.download_http('https://media.example/audio', output) == output
    assert calls[0]['headers']['Range'] == 'bytes=8192-'
    assert calls[0]['headers']['If-Range'] == '"same-recording"'
    assert os.path.getsize(output) == 16384
    assert response.closed
    with open(output, 'rb') as audio_file:
        assert audio_file.read() == b'a' * 8192 + b'b' * 8192


def test_http_range_ignored_restarts_without_appending(tmp_path, monkeypatch):
    output = str(tmp_path / 'audio.mp3')
    with open(output + '.part', 'wb') as audio_file:
        audio_file.write(b'old')
    with open(output + '.part.json', 'w') as metadata_file:
        json.dump({'etag': '"old"'}, metadata_file)
    response = FakeResponse(200, {'Content-Length': '8192', 'ETag': '"new"'}, [b'n' * 8192])
    monkeypatch.setattr('core.download_transfer.guarded_requests_get', lambda *args, **kwargs: response)
    monkeypatch.setattr('core.download_transfer.is_safe_media_url', lambda url: True)
    context = DownloadContext(1, 'yandex', 'id', lambda: None, lambda downloaded, total: None)
    context.download_http('https://media.example/audio', output)
    assert os.path.getsize(output) == 8192
    with open(output, 'rb') as audio_file:
        assert audio_file.read() == b'n' * 8192


def test_http_invalid_range_cannot_corrupt_partial(tmp_path, monkeypatch):
    output = str(tmp_path / 'audio.mp3')
    with open(output + '.part', 'wb') as audio_file:
        audio_file.write(b'a' * 8192)
    with open(output + '.part.json', 'w') as metadata_file:
        json.dump({'etag': '"same"'}, metadata_file)
    response = FakeResponse(206, {'Content-Range': 'bytes 0-8191/16384', 'ETag': '"same"'}, [b'b' * 8192])
    monkeypatch.setattr('core.download_transfer.guarded_requests_get', lambda *args, **kwargs: response)
    monkeypatch.setattr('core.download_transfer.is_safe_media_url', lambda url: True)
    context = DownloadContext(1, 'yandex', 'id', lambda: None, lambda downloaded, total: None)
    with pytest.raises(ValueError, match='диапазон'):
        context.download_http('https://media.example/audio', output)
    assert os.path.getsize(output + '.part') == 8192
    assert response.closed


def test_http_redirect_cannot_bypass_media_url_guard(tmp_path, monkeypatch):
    response = FakeResponse(302, {'Location': 'http://127.0.0.1/private'}, [])
    calls = []

    def request(url, **kwargs):
        calls.append(url)
        return response

    monkeypatch.setattr('core.download_transfer.guarded_requests_get', request)
    monkeypatch.setattr('core.download_transfer.is_safe_media_url', lambda url: not url.startswith('http://127.'))
    context = DownloadContext(1, 'yandex', 'id', lambda: None, lambda downloaded, total: None)
    with pytest.raises(ValueError, match='Unsafe'):
        context.download_http('https://media.example/audio', str(tmp_path / 'audio.mp3'))
    assert calls == ['https://media.example/audio']
    assert response.closed


def test_http_pause_closes_response_and_preserves_partial(tmp_path, monkeypatch):
    output = str(tmp_path / 'audio.mp3')
    checks = []

    def checkpoint():
        checks.append(True)
        if len(checks) >= 4:
            raise DownloadInterrupted()

    response = FakeResponse(200, {'Content-Length': '16384', 'ETag': '"same"'}, [b'a' * 8192, b'b' * 8192])
    monkeypatch.setattr('core.download_transfer.guarded_requests_get', lambda *args, **kwargs: response)
    monkeypatch.setattr('core.download_transfer.is_safe_media_url', lambda url: True)
    context = DownloadContext(1, 'yandex', 'id', checkpoint, lambda downloaded, total: None)
    with pytest.raises(DownloadInterrupted):
        context.download_http('https://media.example/audio', output)
    assert os.path.getsize(output + '.part') == 8192
    assert not os.path.exists(output)
    assert response.closed


def test_youtube_cli_keeps_its_partial_across_pause_and_resume(tmp_path, monkeypatch):
    from services.youtube_service import YouTubeService

    target = 'jNQXAC9IVRw'
    service = YouTubeService.__new__(YouTubeService)
    service.settings = None
    templates, progress = [], []
    paused = False

    def checkpoint():
        if paused:
            raise DownloadInterrupted()

    def run(args, checkpoint, timeout, on_line):
        nonlocal paused
        checkpoint()
        assert '--continue' in args and '--no-overwrites' in args
        assert '--abort-on-unavailable-fragments' in args
        template = args[args.index('-o') + 1]
        templates.append(template)
        path = template.replace('%(id)s', target).replace('%(ext)s', 'm4a')
        partial = path + '.part'
        if not os.path.isfile(partial):
            with open(partial, 'wb') as audio:
                audio.write(b'a' * 8192)
            on_line('nd-progress:8192:16384')
            paused = True
            on_line('nd-progress:8192:16384')
            pytest.fail('paused progress was accepted')
        assert os.path.getsize(partial) == 8192
        with open(partial, 'ab') as audio:
            audio.write(b'b' * 8192)
        os.replace(partial, path)
        on_line('nd-progress:16384:16384')
        on_line('nd-file:' + path)

    monkeypatch.setattr('core.download_processing.run_tool', run)
    first = DownloadContext(1, 'youtube', target, checkpoint, lambda *values: progress.append(values))
    with pytest.raises(DownloadInterrupted):
        service.download_audio_sync(target, str(tmp_path), download_context=first)
    paused = False
    second = DownloadContext(1, 'youtube', target, checkpoint, lambda *values: progress.append(values))
    path = service.download_audio_sync(target, str(tmp_path), download_context=second)
    assert os.path.getsize(path) == 16384
    assert templates[0] == templates[1]
    assert progress == [(8192, 16384), (16384, 16384)]
