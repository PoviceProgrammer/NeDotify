"""Album tracklist availability checks mirror the playlist semantics."""
import threading
from types import SimpleNamespace

from core.album_availability import AlbumAvailability


def make_core(tmp_db, resolve, resolver=None, settings=None):
    return SimpleNamespace(db=tmp_db, engine=SimpleNamespace(resolve_stream_url=resolve),
                           resolver=resolver, settings=settings)


def test_album_check_statuses_mirror_playlist_semantics(tmp_db, tmp_path, settings_stub):
    audio = tmp_path / 'song.mp3'
    audio.write_bytes(b'x' * 10)
    tracks = [
        dict(title='Local', source='local', source_id='', file_path=str(audio)),
        dict(title='Gone', source='local', source_id='', file_path=str(tmp_path / 'gone.mp3')),
        dict(title='Stream', source='youtube', source_id='video'),
        dict(title='Blocked', source='soundcloud', source_id='audio'),
        dict(title='Mystery', source='lmusic', source_id='46'),
    ]

    learned = set()

    def resolve(track, cancel_token):
        if track['source'] == 'youtube':
            return 'https://media.example/song.mp3'
        if track['source'] == 'lmusic':
            raise TimeoutError
        learned.add(track['source_id'])  # the engine records the negative result
        return None

    core = make_core(tmp_db, resolve, resolver=SimpleNamespace(
        is_unavailable=lambda source, sid: sid in learned,
        get_cached_url=lambda source, sid: None), settings=settings_stub)
    done = threading.Event()
    events = []

    def emit(name, data):
        events.append((name, data))
        if name == 'album_availability_updated' and data.get('stage') == 'done':
            done.set()

    checker = AlbumAvailability(core, emit)
    try:
        checker.start(tracks, request_id='rid')
        assert [t['availability'] for t in tracks[:2]] == ['available', 'unavailable']
        assert done.wait(3)
        assert [t['availability'] for t in tracks] == [
            'available', 'unavailable', 'available', 'unavailable', 'unknown']
        final = events[-1][1]
        assert final['request_id'] == 'rid' and final['stage'] == 'done'
        assert (final['total'], final['checked'], final['available'],
                final['unavailable'], final['unknown']) == (3, 3, 1, 1, 1)
        assert [t['availability'] for t in final['tracks']] == [
            'available', 'unavailable', 'available', 'unavailable', 'unknown']
    finally:
        checker.close()


def test_album_check_skips_probes_for_disabled_service_known_bad_and_cached(tmp_db, settings_stub):
    settings_stub.set('services', 'lmusic_enabled', False)
    tracks = [
        dict(title='Off', source='lmusic', source_id='46'),
        dict(title='Bad', source='youtube', source_id='v'),
        dict(title='Cached', source='youtube', source_id='c'),
    ]

    def resolve(track, cancel_token):
        raise AssertionError('no probe should be scheduled for a known status')

    core = make_core(tmp_db, resolve, resolver=SimpleNamespace(
        is_unavailable=lambda source, sid: sid == 'v',
        get_cached_url=lambda source, sid: 'https://media.example/c.mp3' if sid == 'c' else None),
        settings=settings_stub)
    checker = AlbumAvailability(core, lambda *args: None)
    try:
        checker.start(tracks)
        assert [t['availability'] for t in tracks] == ['unknown', 'unavailable', 'available']
    finally:
        checker.close()


def test_album_details_starts_availability_only_for_found_albums(api, core_ns, emitted, monkeypatch):
    started = []

    class StubAvailability:
        def start(self, tracks, request_id=None):
            started.append((tracks, request_id))

        def close(self):
            pass

    monkeypatch.setattr(api, '_album_availability', StubAvailability())
    catalogue = SimpleNamespace(album_details=lambda *a, **k: {
        'status': 'found', 'verified': True,
        'tracks': [{'title': 'Song', 'source': 'youtube', 'source_id': 'v'}]})
    monkeypatch.setattr(api, '_catalog_service', lambda: catalogue)
    pending = []
    monkeypatch.setattr(api, '_search_executor', SimpleNamespace(submit=pending.append))

    api.get_album_details({'source': 'youtube'}, 'rid')
    for run in pending:
        run()
    assert len(started) == 1 and started[0][1] == 'rid'
    assert emitted[-1][0] == 'album_details_ready' and emitted[-1][1]['request_id'] == 'rid'

    catalogue.album_details = lambda *a, **k: {'status': 'not_found', 'tracks': []}
    api.get_album_details({'source': 'youtube'}, 'rid2')
    for run in pending:
        run()
    assert len(started) == 1
    assert emitted[-1][1]['status'] == 'not_found'
