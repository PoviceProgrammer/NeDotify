import io
import threading
from email.message import Message
from types import SimpleNamespace

from core.playlist_availability import PlaylistAvailability
from services.playlist_import_service import PlaylistImportService
from services.spotify_service import SpotifyService
from services.web_music_service import WebMusicService


def test_lmusic_search_and_audio_probe_use_public_track_identity(monkeypatch):
    seen = []
    markup = b'<div class="c-card-mp3" data-mp3_id="46" data-url="/mp3/artist-song/46" data-song_name="Song" data-artist_name="Artist"></div>'

    def fetch(request, timeout):
        seen.append(request)
        response = io.BytesIO(markup if isinstance(request, str) else b'ID3' + bytes(512))
        response.headers = Message()
        response.headers['Content-Type'] = 'audio/mpeg'
        return response

    monkeypatch.setattr('services.web_music_service.guarded_open_url', fetch)
    service = WebMusicService('lmusic')
    results = []
    service.search('Artist Song', results.extend, lambda exc: None)
    assert [(item['title'], item['artist'], item['source_id']) for item in results] == [('Song', 'Artist', '46')]
    assert service.resolve_audio('46') == 'https://lmusic.kz/api/stream/46'
    assert seen[1].get_header('Range') == 'bytes=0-4095'
    assert service.resolve_audio('../other') is None


def test_import_reports_rows_as_the_parser_extracts_them(tmp_path):
    playlist = tmp_path / 'test.m3u'
    playlist.write_text('#EXTM3U\nhttps://rus.hitmos.fm/song/12682699\nhttps://lmusic.kz/mp3/artist-song/46\n',
                        encoding='utf-8')
    progress = []
    tracks = PlaylistImportService().resolve(str(playlist), on_progress=progress.append)['tracks']
    assert progress == [1, 2]
    assert [(track['source'], track['source_id']) for track in tracks] == [('hitmos', '12682699'), ('lmusic', '46')]


def test_hitmos_search_reads_track_metadata_without_inventing_an_audio_url(monkeypatch):
    page = b"""<div class="track-item">
        <img src="https://static-c1.hitmos.fm/cover.webp">
        <a class="track-item__title" href="/song/51">Song</a>
        <span class="track-item__artist">Artist &amp; Band</span>
        <span class="track-item__duration">03:41</span></div>"""
    monkeypatch.setattr('services.web_music_service.guarded_open_url', lambda *a, **k: io.BytesIO(page))
    results = []
    service = WebMusicService('hitmos')
    service.search('Artist Band Song', results.extend, lambda exc: None)
    assert results == [dict(source='hitmos', source_id='51', source_url='https://rus.hitmos.fm/song/51',
                            title='Song', artist='Artist & Band', duration=221,
                            cover_url='https://static-c1.hitmos.fm/cover.webp')]
    assert service.resolve_audio('51') is None


def test_spotify_token_search_uses_spotify_catalogue(monkeypatch):
    done = threading.Event()
    found, calls = [], []

    def request(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'tracks': {'items': [{
            'id': 'official-track', 'name': 'Song', 'artists': [{'name': 'Artist'}], 'duration_ms': 221000,
        }]}})

    def callback(tracks):
        found.extend(tracks)
        done.set()

    settings = SimpleNamespace(get=lambda section, key, default: 'fixture' if key == 'spotify_token' else default)
    service = SpotifyService(settings)
    monkeypatch.setattr(service, '_get_session', lambda: SimpleNamespace(get=request))
    try:
        service.search('Song', callback, lambda exc: done.set())
        assert done.wait(3)
        assert found[0]['catalog_source'] == 'spotify'
        assert found[0]['source_id'] == 'spotify_official-track'
        assert calls[0][0] == 'https://api.spotify.com/v1/search'
        assert calls[0][1]['headers']['Authorization'] == 'Bearer fixture'
    finally:
        service._executor.shutdown(wait=True)


def test_playlist_check_keeps_distinct_versions_and_persists_results(tmp_db):
    tracks = [dict(title='Song', artist='Artist', source=source, source_id=sid)
              for source, sid in [('youtube', 'video'), ('soundcloud', 'audio'), ('lmusic', '46')]]
    playlist_id, count = tmp_db.import_playlist_atomic('Versions', '', tracks, verify=True)
    saved = tmp_db.get_playlist_tracks(playlist_id)
    assert count == 3 and [row['availability'] for row in saved] == ['pending'] * 3

    def resolve(track, cancel_token):
        if track['source'] == 'youtube':
            return 'https://media.example/song.mp3'
        if track['source'] == 'lmusic':
            raise TimeoutError
        return None

    done = threading.Event()
    events = []

    def emit(name, data):
        events.append((name, data))
        if name == 'playlist_availability_updated':
            done.set()

    core = SimpleNamespace(db=tmp_db, engine=SimpleNamespace(resolve_stream_url=resolve),
                           resolver=SimpleNamespace(is_unavailable=lambda source, sid: source == 'soundcloud'))
    checker = PlaylistAvailability(core, emit)
    try:
        checker.start(playlist_id, saved, 'job')
        assert done.wait(3)
        assert [row['availability'] for row in tmp_db.get_playlist_tracks(playlist_id)] == [
            'available', 'unavailable', 'unknown',
        ]
        assert ('playlist_import_progress', dict(job_id='job', playlist_id=playlist_id, stage='done', total=3,
                                                checked=3, available=1, unavailable=1, unknown=1)) in events
    finally:
        checker.close()
