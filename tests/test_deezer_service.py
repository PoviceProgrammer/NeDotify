"""Deezer catalogue, complete imports, and verified full-audio routing."""
from types import SimpleNamespace

import pytest

from services.deezer_service import DeezerService, DeezerError
from services.playlist_import_service import PlaylistImportService


def raw_track(sid=1):
    return {'id': sid, 'title': 'Song', 'artist': {'name': 'Artist'}, 'duration': 180,
            'album': {'title': 'Album', 'cover_big': 'https://cdn.example/cover.jpg'},
            'preview': 'https://cdn.example/preview.mp3'}


@pytest.fixture
def deezer(monkeypatch):
    svc = DeezerService()
    svc._search_cache.clear()
    monkeypatch.setattr(svc, '_get', lambda *a, **k: pytest.fail('Unexpected network request'))
    monkeypatch.setattr(svc, 'submit', lambda fn: (fn(), object())[1])
    return svc


@pytest.mark.parametrize('kind', ['tracks', 'albums', 'playlists'])
def test_search_shapes_and_cache(deezer, monkeypatch, kind):
    calls, replies = [], []
    def get(path, **params):
        calls.append(path)
        return {'data': [raw_track()]}
    monkeypatch.setattr(deezer, '_get', get)
    deezer.search('Artist Song', result_type=kind, callback=replies.append)
    deezer.search('Artist Song', result_type=kind, callback=replies.append)
    assert len(calls) == 1
    assert len(replies) == 2
    assert replies[0][0]['source'] == 'deezer'
    assert replies[0][0]['source_id'] == '1'
    assert 'stream_url' not in replies[0][0]
    assert 'preview' not in replies[0][0]
    if kind != 'tracks':
        assert replies[0][0]['type'] == kind[:-1]


def test_import_paginates_and_deduplicates_without_following_next_url(deezer, monkeypatch):
    calls = []
    def get(path, **params):
        calls.append((path, params))
        if path == 'playlist/42':
            return {'title': 'Mix', 'nb_tracks': 3}
        if params['index'] == 0:
            return {'data': [raw_track(1), raw_track(2)], 'next': 'http://127.0.0.1/private'}
        return {'data': [raw_track(2)]}
    monkeypatch.setattr(deezer, '_get', get)
    result = deezer.collection('playlist', 42, require_complete=True)
    assert [t['source_id'] for t in result['tracks']] == ['1', '2']
    assert result['name'] == 'Mix'
    assert calls[-1] == ('playlist/42/tracks', {'index': 2, 'limit': 100})


@pytest.mark.parametrize('bad_page', [{'error': {}}, {'data': []}, {'data': [raw_track()]}])
def test_partial_import_is_not_reported_as_complete(deezer, monkeypatch, bad_page):
    monkeypatch.setattr(deezer, '_get', lambda path, **kw:
                        {'title': 'Mix', 'nb_tracks': 3} if path == 'playlist/42' else bad_page)
    with pytest.raises(DeezerError):
        deezer.collection('playlist', '42', require_complete=True)


def test_import_rejects_oversized_playlist_before_reading_tracks(deezer, monkeypatch):
    monkeypatch.setattr(deezer, '_get', lambda *a, **k: {'nb_tracks': 2001})
    with pytest.raises(DeezerError, match='2000'):
        deezer.collection('playlist', 42, require_complete=True)


def candidate(source='youtube', **changes):
    return dict({'source': source, 'source_id': 'video123456', 'artist': 'Artist',
                 'title': 'Song', 'duration': 180}, **changes)


def test_download_skips_wrong_versions_and_passes_resume_context(deezer, tmp_path):
    deezer._track(raw_track())
    downloads = []
    def download(sid, directory, download_context=None):
        downloads.append((sid, directory, download_context))
        return 'saved.mp3'
    youtube = SimpleNamespace(search=lambda query, callback, **kw: callback([
        candidate(title='Song (Live)'), candidate(duration=30), candidate()]), download_audio_sync=download)
    deezer._providers = lambda source: youtube
    checks = []
    context = SimpleNamespace(checkpoint=lambda: checks.append(True))
    assert deezer.download_audio_sync('1', str(tmp_path), context) == 'saved.mp3'
    assert downloads == [('video123456', str(tmp_path), context)]
    assert checks


def test_wrong_recording_is_never_downloaded(deezer, tmp_path):
    deezer._track(raw_track())
    deezer._providers = lambda source: SimpleNamespace(
        search=lambda query, callback, **kw: callback([candidate(source, artist='Someone else')]),
        download_audio_sync=lambda *a, **k: pytest.fail('Unverified recording downloaded'))
    with pytest.raises(DeezerError, match='не найдена'):
        deezer.download_audio_sync('1', str(tmp_path))


def test_download_cancel_never_falls_back(deezer, tmp_path):
    from core.download_transfer import DownloadInterrupted
    deezer._track(raw_track())
    calls = []
    def provider(source):
        calls.append(source)
        return SimpleNamespace(search=lambda query, callback, **kw: callback([candidate(source)]),
                               download_audio_sync=lambda *a, **k: (_ for _ in ()).throw(DownloadInterrupted()))
    deezer._providers = provider
    with pytest.raises(DownloadInterrupted):
        deezer.download_audio_sync('1', str(tmp_path))
    assert calls == ['youtube']


def test_download_falls_back_to_verified_soundcloud(deezer, tmp_path):
    deezer._track(raw_track())
    calls = []
    def provider(source):
        def download(*args, **kwargs):
            calls.append(source)
            if source == 'youtube':
                raise RuntimeError('Video unavailable')
            return 'soundcloud.mp3'
        return SimpleNamespace(search=lambda query, callback, **kw: callback([candidate(source)]),
                               download_audio_sync=download)
    deezer._providers = provider
    assert deezer.download_audio_sync(1, str(tmp_path)) == 'soundcloud.mp3'
    assert calls == ['youtube', 'soundcloud']


def test_stream_reports_actual_audio_source(deezer):
    deezer._track(raw_track())
    deezer._providers = lambda source: SimpleNamespace(
        search=lambda query, callback, **kw: callback([candidate()]),
        get_stream_url=lambda sid, callback, **kw: callback('https://audio.example/full', {'title': 'Song'}))
    replies = []
    deezer.get_stream_url(1, callback=lambda *args: replies.append(args))
    assert replies[0][0] == 'https://audio.example/full'
    assert replies[0][1]['resolved_source'] == 'youtube'


def test_import_deezer_url_and_database_identity(api, tmp_db, monkeypatch):
    monkeypatch.setattr('core.api._is_ssrf_safe_url', lambda url: True)
    monkeypatch.setattr('utils.url_safety.safe_public_url', lambda url: True)
    def get(self, path, **params):
        if path == 'playlist/42':
            return {'title': 'Mix', 'nb_tracks': 1}
        return {'data': [raw_track()]}
    monkeypatch.setattr(DeezerService, '_get', get)
    api._core.playlist_importer = PlaylistImportService()
    first = api.import_external_playlist('https://www.deezer.com/ru/playlist/42')
    second = api.import_external_playlist('https://www.deezer.com/ru/playlist/42')
    assert first['success'] and first['imported_count'] == 1
    assert second['success'] and second['imported_count'] == 0
    track = tmp_db.get_playlist_tracks(first['playlist_id'])[0]
    assert track['source'] == 'deezer' and track['source_id'] == '1'
    assert track['duration'] == 180


def test_failed_import_writes_nothing(api, tmp_db, monkeypatch):
    monkeypatch.setattr('core.api._is_ssrf_safe_url', lambda url: True)
    monkeypatch.setattr('utils.url_safety.safe_public_url', lambda url: True)
    monkeypatch.setattr(DeezerService, '_get', lambda self, path, **params:
                        {'title': 'Incomplete', 'nb_tracks': 200} if path == 'playlist/42'
                        else {'data': [raw_track()]})
    api._core.playlist_importer = PlaylistImportService()
    result = api.import_external_playlist('https://deezer.com/playlist/42')
    assert not result['success']
    assert tmp_db.get_playlists() == []
    assert tmp_db.get_track_by_source_id('deezer', '1') is None
    assert 'неполный плейлист' in result['error']


def test_deezer_search_crosses_bridge(api, emitted):
    api._core.deezer = SimpleNamespace(search=lambda query, callback, **kw: callback([candidate('deezer')]))
    api.search('Song', source='deezer', request_id='dz')
    from tests.test_api_search import _wait_for
    assert _wait_for(emitted, 'search_completed')
    result = next(data for event, data in emitted if event == 'search_results')
    assert result['source'] == 'deezer' and result['request_id'] == 'dz'
    assert result['tracks'][0]['title'] == 'Song'


def test_deezer_engine_route():
    from audio.engine import AudioEngine
    engine = AudioEngine.__new__(AudioEngine)
    engine.app_core = SimpleNamespace(deezer=SimpleNamespace(
        get_stream_url=lambda sid, callback, **kw: callback('https://audio.example/full')))
    assert engine._resolve_via_network({'source': 'deezer', 'source_id': '1'}) == 'https://audio.example/full'


@pytest.mark.network
def test_live_deezer_catalogue_and_public_playlist():
    svc = DeezerService()
    search = svc._get('search/track', q='Daft Punk Get Lucky', limit=1)
    assert svc._track(search['data'][0])['source'] == 'deezer'
    playlists = svc._get('search/playlist', q='Daft Punk', limit=1)
    result = svc.collection('playlist', playlists['data'][0]['id'], require_complete=True)
    assert result['tracks']
    assert all(t['source'] == 'deezer' and t['title'] and t['artist'] for t in result['tracks'])
