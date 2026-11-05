from tests.jsdom import run_node, source


def test_artist_candidate_query_keeps_full_group_name():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
let requested;
const ctx = vm.createContext({
  document: {querySelectorAll:()=>[],getElementById:()=>({})},
  window: {showPage() {}}, closeModalFocusTrap() {},
  loadArtistProfile: name => requested = name,
});
vm.runInContext(SOURCE.slice(SOURCE.indexOf('const KNOWN_COLLAB_GROUPS'), SOURCE.indexOf('window.searchArtistProfile =')).replaceAll('export ', ''), ctx);
ctx.searchArtistProfile('New Band & Friends', null, {require_candidates:true});
assert.equal(requested, 'New Band & Friends');
ctx.searchArtistProfile('New Band feat. Guest');
assert.equal(requested, 'New Band');
""".replace('SOURCE', source('search.js')))

from types import SimpleNamespace
from services.lyrics_search import find_lyric_tracks, should_search_lyrics


def test_lyrics_fallback_budget_and_identity():
    requests, searches = [], []
    def fetch(url, deadline):
        requests.append(url)
        return {'response': {'sections': [{'hits': [
            {'result': {'title':'A Song','primary_artist':{'name':'Artist'}},
             'highlights':[{'property':'lyrics','value':'<em>we are walking through the night</em>'}]},
            {'result': {'title':'Unrelated','primary_artist':{'name':'Other'}},
             'highlights':[{'property':'lyrics','value':'something unrelated'}]},
        ]}]}}
    def search(query, **kwargs):
        searches.append(query)
        return [{'title':'A Song','artist':'Other','source_id':'wrong'},
                {'title':'Another Song','artist':'Artist','source_id':'wrong2'},
                {'title':'A Song','artist':'Artist','source':'youtube','source_id':'right'}]
    lyrics = SimpleNamespace(_lookup=SimpleNamespace(_json=fetch),settings=None)
    tracks = find_lyric_tracks('we are walking through the night', lyrics, SimpleNamespace(search_sync=search))
    assert [t['source_id'] for t in tracks] == ['right']
    assert tracks[0]['matched_by'] == 'lyrics'
    assert len(requests) == len(searches) == 1
    assert '/api/search/lyric?' in requests[0]


def test_regular_search_does_not_double_provider_work():
    assert not should_search_lyrics('Artist', [])
    assert not should_search_lyrics('My Song Title', [{'title':'My Song Title'}])
    assert not should_search_lyrics('My Song Title', [{'title':'My Song Title (Live)'}])
    assert should_search_lyrics('some lost song', [])
    assert should_search_lyrics('we are walking through the night', [{'title':'Other'}])


def test_cancelled_lyrics_search_never_calls_network():
    assert find_lyric_tracks('a lyric line', SimpleNamespace(), SimpleNamespace(), lambda: False) == []


def test_artist_track_only_provider_completes_without_track_results(api, emitted, monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError('track provider invoked for artists')
    monkeypatch.setattr(api._core, 'spotify', SimpleNamespace(search=unexpected), raising=False)
    api.search('Artist', source='spotify', result_type='artists', request_id='artists-only')
    assert [event for event, _ in emitted] == ['search_completed']
    assert emitted[0][1]['request_id'] == 'artists-only'


def test_general_search_lyrics_fallback_emits_before_completion(api, emitted, monkeypatch):
    from services import lyrics_search
    from tests.test_api_search import _wait_for
    normal_calls, lyric_calls = [], []
    def search(query, callback, **kwargs):
        normal_calls.append(query)
        callback([])
    for name in ('youtube', 'soundcloud', 'spotify', 'deezer', 'yandex'):
        monkeypatch.setattr(api._core, name, SimpleNamespace(search=search), raising=False)
    monkeypatch.setattr(api._core, 'lyrics', object(), raising=False)
    def lyric(query, *args):
        lyric_calls.append(query)
        return [{'title':'Verified Song','artist':'Artist','source':'youtube','source_id':'song'}]
    monkeypatch.setattr(lyrics_search, 'find_lyric_tracks', lyric)
    api.search('we are walking through the night', request_id='line-request')
    assert _wait_for(emitted, 'search_completed')
    assert lyric_calls == ['we are walking through the night']
    matches = [d for e,d in emitted if e == 'search_results' and d['tracks']]
    assert matches[0]['tracks'][0]['source_id'] == 'song'
    assert matches[0]['request_id'] == 'line-request'
    assert emitted[-1][0] == 'search_completed'
    assert 5 <= len(normal_calls) <= 10


def test_empty_cached_provider_layout_retry_is_reentrant(api, emitted, monkeypatch):
    from tests.test_api_search import _wait_for
    calls = []
    def cached_search(query, callback, **kwargs):
        calls.append(query)
        callback([])
    monkeypatch.setattr(api._core, 'spotify', SimpleNamespace(search=cached_search), raising=False)
    api.search('ghbdtn', source='spotify', request_id='empty-cache')
    assert _wait_for(emitted, 'search_completed', timeout=1)
    assert calls == ['ghbdtn', 'привет']
    assert sum(event == 'search_completed' for event, _ in emitted) == 1


def test_local_artist_search_returns_real_artist_entities(api, emitted, tmp_db):
    tmp_db.add_track(title='Song', artist='Unique Artist', source='local',source_id='local-artist')
    api.search('Unique Artist', source='local', result_type='artists')
    batches = [d for e,d in emitted if e == 'search_results']
    assert batches and batches[0]['tracks'][0]['type'] == 'artist'
    assert batches[0]['tracks'][0]['artist'] == 'Unique Artist'


def test_ordinary_track_search_never_calls_lyrics_provider(api, emitted, monkeypatch):
    from services import lyrics_search
    from tests.test_api_search import _wait_for
    def search(query, callback, **kwargs):
        callback([{'title':query,'artist':'Artist','source':'youtube','source_id':'song'}])
    for name in ('youtube', 'soundcloud', 'spotify', 'deezer', 'yandex'):
        monkeypatch.setattr(api._core, name, SimpleNamespace(search=search), raising=False)
    def unexpected(*args):
        raise AssertionError('ordinary title search doubled by lyric discovery')
    monkeypatch.setattr(lyrics_search, 'find_lyric_tracks', unexpected)
    api.search('A Very Long Real Song Title')
    assert _wait_for(emitted, 'search_completed', timeout=1)
    assert not any(t.get('matched_by') == 'lyrics' for e,d in emitted if e == 'search_results' for t in d['tracks'])


def test_lyrics_cancelled_after_fulltext_skips_catalogue():
    current = [True]
    def fetch(*args):
        current[0] = False
        return {'response':{'sections':[{'hits':[{'result':{'title':'Song','primary_artist':{'name':'Artist'}},'highlights':[{'property':'lyrics','value':'a lyric line'}]}]}]}}
    def unexpected(*args, **kwargs):
        raise AssertionError('stale request reached catalogue')
    lyrics = SimpleNamespace(_lookup=SimpleNamespace(_json=fetch))
    assert find_lyric_tracks('a lyric line', lyrics, SimpleNamespace(search_sync=unexpected), lambda: current[0]) == []


def test_russian_genius_credit_matches_existing_lyrics_identity():
    from services.lyrics_service import LyricsService
    lyrics = LyricsService()
    lyrics._lookup._json = lambda *args: {'response':{'sections':[{'hits':[{
        'result':{'title':'Группа крови (Blood Type)','primary_artist':{'name':'КИНО (KINO)'}},
        'highlights':[{'property':'lyrics','value':'пожелай мне удачи в бою'}],
    }]}]}}
    searches = []
    def search(query, **kwargs):
        searches.append(query)
        return [{'title':'Группа крови','artist':'KINO','source':'youtube','source_id':'original'}]
    hits = find_lyric_tracks('пожелай мне удачи в бою', lyrics, SimpleNamespace(search_sync=search))
    assert searches == ['КИНО - Группа крови']
    assert [track['source_id'] for track in hits] == ['original']


def test_missing_youtube_uses_verified_deezer_catalogue():
    from services.deezer_service import DeezerService
    requests = []
    def fetch(url, *args):
        requests.append(url)
        if 'genius.com' in url:
            return {'response':{'sections':[{'hits':[{
                'result':{'title':'A Song','primary_artist':{'name':'Artist'}},
                'highlights':[{'property':'lyrics','value':'some matching lyric line'}],
            }]}]}}
        return {'data':[
            {'id':1,'title':'A Song','artist':{'name':'Other'}},
            {'id':2,'title':'A Song','artist':{'name':'Artist'},'preview':'https://example.org/preview.mp3'},
        ]}
    lyrics = SimpleNamespace(_lookup=SimpleNamespace(_json=fetch),settings=None)
    hits = find_lyric_tracks('some matching lyric line',lyrics,SimpleNamespace(search_sync=lambda *a,**k: []),deezer=DeezerService())
    assert [(t['source'],t['source_id']) for t in hits] == [('deezer','2')]
    assert 'preview' not in hits[0] and 'stream_url' not in hits[0]
    assert len(requests) == 2


def test_fulltext_does_not_accept_title_only_highlight():
    def unexpected(*args, **kwargs):
        raise AssertionError('title highlight must not trigger catalogue search')
    payload = {'response':{'sections':[{'hits':[{
        'result':{'title':'Some Song Title','primary_artist':{'name':'Artist'}},
        'highlights':[{'property':'title','value':'some song title'}],
    }]}]}}
    lyrics = SimpleNamespace(_lookup=SimpleNamespace(_json=lambda *a:payload))
    assert find_lyric_tracks('some song title',lyrics,SimpleNamespace(search_sync=unexpected)) == []


def test_native_credit_cleanup_preserves_versions():
    from services.lyrics_search import _native_name
    assert _native_name('Группа крови (Blood Type)') == 'Группа крови'
    assert _native_name('Группа крови (Live)') == 'Группа крови (Live)'
    assert _native_name('Группа крови (Remix)') == 'Группа крови (Remix)'
    assert _native_name('Song (Live)') == 'Song (Live)'


def test_artist_discovery_reserves_deadline_for_itunes(monkeypatch):
    import time
    from services.catalog_service import CatalogService
    from services.itunes_gateway import ITunesGateway, CatalogueUnavailable
    service = CatalogService(SimpleNamespace(_ytmusic=SimpleNamespace(search=lambda *a,**k: [])))
    deadlines = []
    def unavailable(fn, deadline, is_current):
        deadlines.append(deadline)
        raise CatalogueUnavailable('provider timed out')
    monkeypatch.setattr(service, '_call', unavailable)
    monkeypatch.setattr(ITunesGateway, 'get', lambda *a,**k: {'results':[{'artistId':290699,'artistName':'Earth, Wind & Fire'}]})
    deadline = time.monotonic() + 8
    result = service.resolve_artist('Earth, Wind & Fire',{'require_candidates':True},_deadline=deadline)
    assert result['status'] == 'ambiguous'
    assert result['candidates'][0]['source'] == 'itunes'
    assert deadlines and deadlines[0] <= deadline - 4


def test_lyrics_timeout_still_completes_general_search(api, emitted, monkeypatch):
    from services import lyrics_search
    from tests.test_api_search import _wait_for
    def search(query, callback, **kwargs):
        callback([])
    for name in ('youtube', 'soundcloud', 'spotify', 'deezer', 'yandex'):
        monkeypatch.setattr(api._core,name,SimpleNamespace(search=search),raising=False)
    monkeypatch.setattr(api._core,'lyrics',object(),raising=False)
    def timeout(*args):
        raise TimeoutError('public source timeout')
    monkeypatch.setattr(lyrics_search,'find_lyric_tracks',timeout)
    api.search('a sufficiently long unknown lyric line',request_id='timed-out-lyric')
    assert _wait_for(emitted,'search_completed',timeout=1)
    assert sum(e == 'search_completed' for e,d in emitted) == 1
    assert emitted[-1][1]['request_id'] == 'timed-out-lyric'
