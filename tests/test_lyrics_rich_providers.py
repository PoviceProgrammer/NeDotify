from urllib.parse import parse_qs, urlparse

import pytest

from services import lyrics_providers as module
from services.lyrics_providers import RichLyricsProviders
from services.lyrics_service import LyricsService


pytestmark = pytest.mark.rich_lyrics


class FakeEngine:
    def __init__(self):
        self.requests = []
        self.accepted = []

    def _json(self, url, deadline):
        self.requests.append((url, deadline))
        return self.body

    def accept(self, form, title, artists, duration, synced, plain, source, instrumental=False):
        self.accepted.append((form, title, artists, duration, synced, plain, source))
        if self.reject:
            return None
        return {
            'status': 'found', 'syncedLyrics': synced, 'plainLyrics': plain,
            'instrumental': False, 'weight': 1, 'source': source,
            'match_type': 'exact', 'confidence': 1,
        }

    reject = False


def form(**overrides):
    value = {
        'metadata': {'title': 'Song', 'artists': ['Artist'], 'version': ''},
        'query_title': 'Song', 'query_artist': 'Artist', 'duration': 180,
        'album': 'Album', 'fallback': False,
    }
    value.update(overrides)
    return value


def parser_stubs(monkeypatch, *, sync_type='word'):
    model = {
        'syncType': sync_type,
        'lines': [{'startMs': 0, 'endMs': 1000,
                   'words': [{'text': 'Song', 'startMs': 0, 'endMs': 1000}]}],
    }
    monkeypatch.setattr(module, 'parse_lyrics', lambda text, fmt, duration_ms=0: dict(model))
    monkeypatch.setattr(module, 'validate_lyrics', lambda model, duration_ms=0: True)
    monkeypatch.setattr(module, 'plain_text', lambda model: 'Song')
    monkeypatch.setattr(module, 'to_lrc', lambda model: '[00:00.00]Song')


def test_unison_uses_only_confirmed_video_id_and_preserves_original(monkeypatch):
    parser_stubs(monkeypatch)
    engine = FakeEngine()
    engine.body = {'success': True, 'data': {
        'videoId': 'abcdefghijk', 'song': 'Song', 'artist': 'Artist',
        'duration': 180, 'confidence': 'high', 'format': 'ttml', 'syncType': 'richsync',
        'lyrics': '<tt>original</tt>',
    }}
    provider = RichLyricsProviders(engine)
    offers = []
    result = provider.unison(form(video_id='abcdefghijk'), 12.5, offers.append)

    parsed = urlparse(engine.requests[0][0])
    assert parsed.path == '/lyrics'
    assert parse_qs(parsed.query) == {'v': ['abcdefghijk']}
    assert engine.requests[0][1] == 12.5
    assert result['source'] == 'Unison'
    assert result['originalFormat'] == 'ttml'
    assert result['originalLyrics'] == '<tt>original</tt>'
    assert result['syncType'] == 'word'
    assert result['lines'][0]['words'][0]['text'] == 'Song'
    assert offers == [result]


def test_unison_rejects_mismatched_video_id(monkeypatch):
    parser_stubs(monkeypatch)
    engine = FakeEngine()
    engine.body = {'success': True, 'data': {
        'videoId': 'wrongwrong1', 'song': 'Song', 'artist': 'Artist',
        'duration': 180, 'confidence': 'high', 'format': 'lrc', 'lyrics': '[00:00.00]Song',
    }}
    assert RichLyricsProviders(engine).unison(form(video_id='abcdefghijk'), 5, lambda _: None) is None
    assert engine.accepted == []


def test_unison_title_lookup_requires_explicit_identity(monkeypatch):
    parser_stubs(monkeypatch)
    engine = FakeEngine()
    engine.body = {'success': True, 'data': {'confidence': 'high', 'format': 'plain', 'lyrics': 'Song'}}
    provider = RichLyricsProviders(engine)
    assert provider.unison(form(), 5, lambda _: None) is None
    assert parse_qs(urlparse(engine.requests[0][0]).query) == {
        'song': ['Song'], 'artist': ['Artist'], 'album': ['Album'], 'duration': ['180'],
    }
    assert engine.accepted == []


def test_better_lyrics_requires_embedded_ttml_identity(monkeypatch):
    parser_stubs(monkeypatch)
    engine = FakeEngine()
    engine.body = {'ttml': '<tt><body>unverified</body></tt>'}
    provider = RichLyricsProviders(engine)
    assert provider.betterlyrics(form(), 4, lambda _: None) is None
    assert engine.accepted == []
    assert parse_qs(urlparse(engine.requests[0][0]).query) == {
        's': ['Song'], 'a': ['Artist'], 'al': ['Album'], 'd': ['180'],
    }


def test_better_lyrics_checks_embedded_identity_before_offer(monkeypatch):
    parser_stubs(monkeypatch)
    engine = FakeEngine()
    engine.body = {'ttml': (
        '<tt xmlns="http://www.w3.org/ns/ttml"><head><metadata>'
        '<title>Song</title><artist>Artist</artist><album>Album</album>'
        '<duration>180</duration></metadata></head><body>lyric</body></tt>'
    )}
    result = RichLyricsProviders(engine).betterlyrics(form(), 4, lambda _: None)
    assert result['source'] == 'Better Lyrics'
    assert engine.accepted[0][1:4] == ('Song', 'Artist', 180)


def test_better_lyrics_reads_pinned_amll_key_value_metadata():
    engine = FakeEngine()
    engine.body = {'ttml': (
        '<tt xmlns="http://www.w3.org/ns/ttml" xmlns:amll="https://github.com/amll-dev">'
        '<head><metadata><amll:meta key="musicName" value="Song"/>'
        '<amll:meta key="artists" value="Artist"/><amll:meta key="album" value="Album"/>'
        '</metadata></head><body><div><p begin="0s" end="1s">'
        '<span begin="0s" end="1s">Song</span></p></div></body></tt>'
    )}
    result = RichLyricsProviders(engine).betterlyrics(form(), 4, lambda _: None)
    assert result['source'] == 'Better Lyrics'
    assert engine.accepted[0][1:4] == ('Song', 'Artist', 180)
    assert result['originalFormat'] == 'ttml'


def test_simpmusic_is_id_bound_and_never_searches_without_id(monkeypatch):
    parser_stubs(monkeypatch)
    engine = FakeEngine()
    provider = RichLyricsProviders(engine)
    assert provider.simpmusic(form(), 3, lambda _: None) is None
    assert engine.requests == []
    engine.body = {'success': True, 'data': [{
        'videoId': 'abcdefghijk', 'syncedLyrics': '[00:00.00]Song', 'duration': 180,
    }]}
    result = provider.simpmusic(form(video_id='abcdefghijk'), 3, lambda _: None)
    assert urlparse(engine.requests[0][0]).path == '/v1/abcdefghijk'
    assert result['source'] == 'SimpMusic'
    assert result['originalLyrics'] == '[00:00.00]Song'


def test_simpmusic_rejects_response_for_another_video(monkeypatch):
    parser_stubs(monkeypatch)
    engine = FakeEngine()
    engine.body = {'success': True, 'data': [{'videoId': 'wrongwrong1', 'syncedLyrics': '[00:00.00]Song'}]}
    assert RichLyricsProviders(engine).simpmusic(form(video_id='abcdefghijk'), 3, lambda _: None) is None
    assert engine.accepted == []


def test_simpmusic_word_markers_parse_without_changing_the_source_text():
    engine = FakeEngine()
    original = '<00:00.00>Song <00:00.50>again'
    engine.body = {'success': True, 'data': [{
        'videoId': 'abcdefghijk', 'syncedLyrics': original, 'duration': 180,
    }]}
    result = RichLyricsProviders(engine).simpmusic(form(video_id='abcdefghijk'), 3, lambda _: None)
    assert result['originalLyrics'] == original
    assert result['syncType'] == 'word'
    assert [word['text'].strip() for word in result['lines'][0]['words']] == ['Song', 'again']


def test_identity_acceptance_can_reject_a_rich_provider_result(monkeypatch):
    parser_stubs(monkeypatch)
    engine = FakeEngine()
    engine.reject = True
    engine.body = {'success': True, 'data': {
        'videoId': 'abcdefghijk', 'song': 'Song', 'artist': 'Artist',
        'duration': 180, 'confidence': 'high', 'format': 'lrc', 'lyrics': '[00:00.00]Song',
    }}
    assert RichLyricsProviders(engine).unison(form(video_id='abcdefghijk'), 2, lambda _: None) is None


@pytest.mark.parametrize('confidence', [None, 'low', 'medium', .79, float('nan'), 1.01, -0.1])
def test_unison_title_lookup_requires_sufficient_valid_confidence(monkeypatch, confidence):
    parser_stubs(monkeypatch)
    engine = FakeEngine()
    engine.body = {'success': True, 'data': {
        'song': 'Song', 'artist': 'Artist', 'album': 'Album', 'duration': 180,
        'confidence': confidence, 'format': 'lrc', 'lyrics': '[00:00.00]Song',
    }}
    assert RichLyricsProviders(engine).unison(form(), 2, lambda _: None) is None
    assert engine.accepted == []


def test_unison_checks_album_and_requires_echoed_video_id(monkeypatch):
    parser_stubs(monkeypatch)
    engine = FakeEngine()
    provider = RichLyricsProviders(engine)
    engine.body = {'success': True, 'data': {
        'song': 'Song', 'artist': 'Artist', 'album': 'Different Album', 'duration': 180,
        'confidence': 'high', 'format': 'lrc', 'lyrics': '[00:00.00]Song',
    }}
    assert provider.unison(form(), 2, lambda _: None) is None
    engine.body = {'success': True, 'data': {
        'song': 'Song', 'artist': 'Artist', 'duration': 180,
        'format': 'lrc', 'lyrics': '[00:00.00]Song',
    }}
    assert provider.unison(form(video_id='abcdefghijk'), 2, lambda _: None) is None


def test_unison_uses_form_duration_when_echoed_video_has_no_duration(monkeypatch):
    parser_stubs(monkeypatch)
    engine = FakeEngine()
    engine.body = {'success': True, 'data': {
        'videoId': 'abcdefghijk', 'song': 'Song', 'artist': 'Artist',
        'confidence': 'high', 'format': 'lrc', 'lyrics': '[00:00.00]Song',
    }}
    result = RichLyricsProviders(engine).unison(form(video_id='abcdefghijk'), 2, lambda _: None)
    assert result['syncedLyrics'] == '[00:00.00]Song'
    assert engine.accepted[0][3] == 180


def test_lookup_real_acceptor_with_mocked_rich_transport(monkeypatch):
    service = LyricsService()
    lookup = service._lookup
    for name in ('betterlyrics', 'simpmusic'):
        monkeypatch.setattr(lookup.rich, name, lambda *args: None)
    for name in ('lrclib', 'netease', 'genius', 'qqmusic', 'megalobiz'):
        monkeypatch.setattr(lookup, name, lambda *args: None)
    calls = []

    def mocked_json(url, deadline, headers=None):
        calls.append((url, deadline))
        return {'success': True, 'data': {
            'videoId': 'abcdefghijk', 'song': 'Song', 'artist': 'Artist',
            'duration': 180, 'confidence': 'high', 'format': 'lrc',
            'lyrics': '[00:00.00]Song',
        }}

    monkeypatch.setattr(lookup, '_json', mocked_json)
    result = lookup.get('Song', 'Artist', 180000, album='Album', video_id='abcdefghijk')
    assert len(calls) == 1
    assert result['status'] == 'found'
    assert result['syncType'] == 'line'
    assert result['lines'][0]['words'][0]['text'] == 'Song'
    assert result['trackIdentity']['videoId'] == 'abcdefghijk'


def test_unison_id_miss_retries_verified_metadata(monkeypatch):
    from services.lyrics_providers import RichLyricsProviders
    from services.lyrics_service import LyricsService
    service = LyricsService()
    calls = []
    def request(url, *args):
        calls.append(url)
        if '?v=' in url:
            return {'success':False,'code':'NOT_FOUND'}
        return {'success':True,'data':{'song':'Song','artist':'Artist','duration':120,'confidence':'high',
                                     'format':'lrc','lyrics':'[00:01] Hello'}}
    monkeypatch.setattr(service._lookup, '_json', request)
    form = {'metadata':{'title':'Song','base_title':'Song','artists':['Artist'],'version':''},
            'query_title':'Song','query_artist':'Artist','duration':120,'album':'','fallback':False,'video_id':'abcdefghijk'}
    result = RichLyricsProviders(service._lookup).unison(form, 1, lambda p: None)
    assert result['plainLyrics'] == 'Hello'
    assert len(calls) == 2 and 'song=Song' in calls[1]
