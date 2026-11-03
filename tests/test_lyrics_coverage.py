"""Actual provider transport seams for reuploads and extra public lyric sources."""
import json
import base64
import time
import threading
import urllib.parse
import urllib.error
from io import BytesIO

import pytest

from services.lyrics_service import LyricsService
from services.lyrics_metadata import lyrics_metadata


pytestmark = pytest.mark.lyrics_coverage


def quiet_original_sources(service, monkeypatch):
    for name in ('lrclib', 'netease', 'qqmusic', 'genius', 'megalobiz'):
        monkeypatch.setattr(service._lookup, name, lambda *args: None)
    for name in ('unison', 'betterlyrics', 'simpmusic'):
        monkeypatch.setattr(service._lookup.rich, name, lambda *args: None)


@pytest.mark.parametrize('collision', [False, True])
def test_reupload_requires_unique_independent_catalogue_evidence(monkeypatch, collision):
    service = LyricsService()
    quiet_original_sources(service, monkeypatch)
    requests = []

    def request(req, **kwargs):
        parsed = urllib.parse.urlsplit(req.full_url)
        requests.append(parsed.hostname + parsed.path)
        if parsed.hostname == 'api.deezer.com':
            rows = [{'id': 100, 'title': 'Сукины дети', 'duration': 220,
                     'artist': {'id': 7, 'name': '1.Kla$'}},
                    {'id': 101, 'title': 'Сукины дети', 'duration': 166,
                     'artist': {'id': 8, 'name': 'Another artist'}}]
            if collision:
                rows.append({'id': 102, 'title': 'Сукины дети', 'duration': 220,
                             'artist': {'id': 8, 'name': 'Another artist'}})
            data = {'data': rows}
        elif parsed.path == '/api/cloudsearch/pc':
            songs = [{'id': 200, 'name': 'Сукины дети', 'dt': 220517,
                      'ar': [{'id': 9, 'name': '1.Kla$'}]}]
            if collision:
                songs.append({'id': 201, 'name': 'Сукины дети', 'dt': 220000,
                              'ar': [{'id': 10, 'name': 'Another artist'}]})
            data = {'code': 200, 'result': {'songs': songs}}
        elif parsed.path == '/api/song/lyric':
            data = {'lrc': {'lyric': '[00:01] Independent lyric fixture'}}
        else:
            raise ConnectionError('Other providers unavailable in fixture')
        return BytesIO(json.dumps(data).encode())

    monkeypatch.setattr(service, '_open_url', request)
    result = service.get_lyrics('Сукины дети', 'Danzal_Parkour', 219000,
                                source='soundcloud', source_id='123456')
    if collision:
        assert result['status'] != 'found'
        assert 'music.163.com/api/song/lyric' not in requests
    else:
        assert result['status'] == 'found', result
        assert result['matched_artist'] == '1.Kla$'
        assert result['plainLyrics'] == 'Independent lyric fixture'
        assert result['syncedLyrics'] is None
        assert result['identity_recovered'] is True
        assert {x['source'] for x in result['identity_evidence']} == {'Deezer', 'Netease'}


def test_genius_bilingual_title_matches_original_without_accepting_translation():
    service = LyricsService()
    form = {'metadata': lyrics_metadata('Сукины дети', '1.Kla$'), 'duration': 219}
    assert service._lookup.accept(form, 'Сукины дети (Sons of Bitches)', '1.Kla$', 0,
                                  None, 'Fixture', 'Genius') is not None
    assert service._lookup.accept(form, 'Сукины дети (English Translation)',
                                  'Genius English Translations', 0, None, 'Wrong', 'Genius') is None


def provider_form(title='A Song', artist='Artist', duration=120):
    return {'metadata': lyrics_metadata(title, artist), 'duration': duration, 'album': '',
            'fallback': False, 'query_artist': artist, 'query_title': title}


@pytest.mark.parametrize('original', [False, True])
def test_ovh_plain_and_remix_fallback_use_url_encoded_identity(monkeypatch, original):
    service = LyricsService()
    queries = []
    def request(req, **kwargs):
        queries.append(req.full_url)
        return BytesIO(json.dumps({'lyrics': 'Fixture words'}).encode())
    monkeypatch.setattr(service, '_open_url', request)
    form = provider_form('A Song (Remix)' if original else 'A Song', 'Artist / Other')
    if original:
        form.update(query_title='A Song', fallback=True)
    result = service._lookup.public.ovh(form, time.monotonic() + 1, lambda r: None)
    assert result['plainLyrics'] == 'Fixture words' and result['syncedLyrics'] is None
    assert '%2F' in queries[0] and result['match_type'] == ('base' if original else 'exact')


@pytest.mark.parametrize('metadata,expected', [('[ti:A Song][ar:Artist]', True),
                                              ('[ti:Another][ar:Artist]', False), ('', False)])
def test_better_qq_requires_embedded_identity_and_never_invents_duration(monkeypatch, metadata, expected):
    engine = LyricsService()._lookup
    raw = '<?xml version="1.0"?><QrcInfos><LyricInfo><Lyric_1 LyricContent="' + metadata + '&#10;[1000,2000]Fixture(1000,2000)"/></LyricInfo></QrcInfos>'
    monkeypatch.setattr(engine, '_json', lambda *args: {'provider': 'qq', 'lyrics': raw})
    result = engine.public.better_qq(provider_form(), time.monotonic() + 1, lambda r: None)
    assert bool(result) is expected
    if expected:
        assert result['plainLyrics'] == 'Fixture'
        assert result['syncedLyrics'] is None


@pytest.mark.parametrize('singer,content,expected', [
    ('Artist', base64.b64encode(b'[00:01] Fixture').decode(), True),
    ('Other', base64.b64encode(b'[00:01] Wrong').decode(), False),
    ('Artist', 'not base64!!', False)])
def test_kugou_verifies_candidates_and_decodes_bounded_real_lrc(monkeypatch, singer, content, expected):
    engine = LyricsService()._lookup
    requests = []
    def request(url, *args):
        requests.append(url)
        if '/search?' in url:
            return {'candidates': [{'id': '123', 'accesskey': 'fixture', 'song': 'A Song',
                                    'singer': singer, 'duration': 120000}]}
        return {'content': content}
    monkeypatch.setattr(engine, '_json', request)
    result = engine.public.kugou(provider_form(), time.monotonic() + 1, lambda r: None)
    assert bool(result) is expected
    assert len(requests) == (1 if singer == 'Other' else 2)
    if expected:
        assert result['syncedLyrics'] == '[00:01.000] Fixture'


def test_upload_recovery_does_not_relax_ordinary_artist_or_missing_duration(monkeypatch):
    engine = LyricsService()._lookup
    monkeypatch.setattr(engine, '_json', lambda *a: pytest.fail('Must not query a catalogue'))
    assert engine.public.recover_upload(provider_form(), time.monotonic() + 1, lambda r: None) is None
    form = dict(provider_form(duration=0), upload_source='soundcloud')
    assert engine.public.recover_upload(form, time.monotonic() + 1, lambda r: None) is None


def test_real_qq_xml_attribute_line_breaks_do_not_hide_all_lines(monkeypatch):
    engine = LyricsService()._lookup
    raw = '<QrcInfos><LyricInfo><Lyric_1 LyricContent="[ti:A Song]\n[ar:Artist]\n[1000,1000]First(1000,1000)\n[3000,1000]Second(3000,1000)"/></LyricInfo></QrcInfos>'
    monkeypatch.setattr(engine, '_json', lambda *a: {'provider': 'qq', 'lyrics': raw})
    result = engine.public.better_qq(provider_form(), time.monotonic() + 1, lambda r: None)
    assert result and result['plainLyrics'] == 'First\nSecond'
    assert result['syncedLyrics'] is None


@pytest.mark.parametrize('proxy', ['', 'http://127.0.0.1:1080'])
def test_lyric_transport_reuses_public_tls_but_preserves_explicit_proxy(monkeypatch, proxy):
    from services.base_service import BaseMusicService
    from utils import url_safety
    class Settings:
        def get(self, *args):
            return proxy
    service = LyricsService(Settings())
    calls = []
    monkeypatch.setattr(url_safety, 'guarded_open_url', lambda *args, **kw: calls.append('public') or 'reply')
    monkeypatch.setattr(BaseMusicService, 'open_url', lambda *args, **kw: calls.append('explicit') or 'reply')
    assert service._open_url('https://lrclib.net/api/search?q=fixture') == 'reply'
    assert calls == ['explicit' if proxy else 'public']


def test_completed_lookup_stops_running_source_before_another_request(monkeypatch):
    service = LyricsService()
    engine = service._lookup
    real_netease = engine.netease
    quiet_original_sources(service, monkeypatch)
    for name in ('ovh', 'better_qq', 'kugou', 'recover_upload'):
        monkeypatch.setattr(engine.public, name, lambda *a: None)
    started, release, completed, second = (threading.Event() for _ in range(4))
    class SearchReply(BytesIO):
        def read(self, *args):
            started.set()
            assert release.wait(2)
            return super().read(*args)
    def request(req, **kwargs):
        if 'cloudsearch' in req.full_url:
            row = {'id': 1, 'name': 'A Song', 'dt': 120000, 'ar': [{'name': 'Artist'}]}
            return SearchReply(json.dumps({'result': {'songs': [row]}}).encode())
        second.set()
        return BytesIO(b'{}')
    def delayed(*args):
        try:
            return real_netease(*args)
        finally:
            completed.set()
    def first(form, *args):
        assert started.wait(1)
        result = engine.accept(form, 'A Song', 'Artist', 120, '[00:01] Fixture', 'Fixture', 'Test')
        result.update(syncType='word', lines=[{'startMs': 1000, 'endMs': 2000,
                      'words': [{'text': 'Fixture', 'startMs': 1000, 'endMs': 2000}]}])
        return result
    monkeypatch.setattr(service, '_open_url', request)
    monkeypatch.setattr(engine, 'netease', delayed)
    monkeypatch.setattr(engine, 'lrclib', first)
    try:
        result = service.get_lyrics('A Song', 'Artist', 120000)
        assert result['syncType'] == 'word'
    finally:
        release.set()
    assert completed.wait(1)
    assert not second.is_set(), 'A completed lookup must not continue fetching fallback pages'


@pytest.mark.parametrize('provider', ['ovh', 'better_qq'])
@pytest.mark.parametrize('code', [404, 429])
def test_public_lyric_miss_is_not_a_source_outage(monkeypatch, provider, code):
    engine = LyricsService()._lookup
    def error(url, *args):
        raise urllib.error.HTTPError(url, code, 'Fixture', {}, None)
    monkeypatch.setattr(engine, '_json', error)
    if code == 404:
        assert getattr(engine.public, provider)(provider_form(), time.monotonic() + 1, lambda r: None) is None
    else:
        with pytest.raises(urllib.error.HTTPError):
            getattr(engine.public, provider)(provider_form(), time.monotonic() + 1, lambda r: None)
