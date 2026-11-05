"""Artist identity and catalogue regressions replayed without network access."""

from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from services.artist_service import ArtistService
from services.catalog_service import CatalogService
from services.itunes_gateway import ITunesGateway
from tests.jsdom import run_node, source as js_source


def test_itunes_homonyms_resolve_by_unique_track_evidence(monkeypatch):
    """An exact name alone is ambiguous; a uniquely credited song resolves it."""
    candidates = [
        {'artistId': sid, 'artistName': 'PHARAOH', 'primaryGenreName': genre}
        for sid, genre in [(11, 'Metal'), (22, 'Hip-Hop/Rap'), (33, 'Chinese Hip-Hop')]
    ]

    def get(url, **kwargs):
        query = parse_qs(urlparse(url).query)
        if query.get('entity') == ['musicArtist']:
            return {'results': candidates}
        ids = [int(sid) for sid in query['id'][0].split(',')]
        if query.get('entity') == ['song']:
            return {'results': [dict(wrapperType='track', kind='song', trackId=100 + sid,
                                     artistId=sid, artistName='PHARAOH',
                                     trackName='ДИКО, НАПРИМЕР' if sid == 22 else 'Other Song') for sid in ids]}
        return {'results': [dict(item, wrapperType='artist') for item in candidates if item['artistId'] in ids]}

    monkeypatch.setattr(ITunesGateway, 'get', staticmethod(get))
    service = CatalogService()
    monkeypatch.setattr(service, '_deezer_get', lambda *args, **kwargs: {'data':[]})
    ref = {'context': {'title': 'ДИКО, НАПРИМЕР', 'source': 'local', 'source_id': 'local-1'}}
    result = service.resolve_artist('PHARAOH', ref)
    assert result['status'] == 'found', 'unique credited track evidence must resolve catalogue homonyms'
    assert (result['source'], result['source_id']) == ('itunes', '22')


def test_shared_song_title_does_not_arbitrarily_choose_first_homonym():
    class YT:
        def search(self, *args, **kwargs):
            return [{'artist': 'Same Name', 'browseId': sid} for sid in ('UC-one', 'UC-two')]

        def get_artist(self, sid):
            return {'name': 'Same Name', 'songs': {'results': [
                {'title': 'Intro', 'artists': [{'name': 'Same Name', 'id': sid}]}]}}

    service = CatalogService(SimpleNamespace(_ytmusic=YT()))
    result = service.resolve_artist('Same Name', {'hint_track': 'Intro'})
    assert result['status'] == 'ambiguous', 'two equally supported catalogue IDs must remain a choice'
    assert {candidate['source_id'] for candidate in result['candidates']} == {'UC-one', 'UC-two'}


@pytest.mark.parametrize('source', ['youtube', 'itunes'])
def test_artist_catalog_page_keeps_id_verified_remixes(monkeypatch, source):
    sid = 'UC-artist' if source == 'youtube' else '77'
    if source == 'youtube':
        items = [
            {'videoId': 'own-remix', 'title': 'Track (Official Remix)',
             'artists': [{'name': 'PHARAOH', 'id': sid}]},
            {'videoId': 'other-remix', 'title': 'Other Remix',
             'artists': [{'name': 'PHARAOH', 'id': 'UC-other'}]},
        ]
        yt = SimpleNamespace(get_album=lambda album_id: {'tracks': items})
        service = ArtistService(SimpleNamespace(_ytmusic=yt))
    else:
        items = [
            {'wrapperType': 'track', 'kind': 'song', 'trackId': 1, 'artistId': 77,
             'artistName': 'PHARAOH', 'trackName': 'Track (Official Remix)'},
            {'wrapperType': 'track', 'kind': 'song', 'trackId': 2, 'artistId': 88,
             'artistName': 'PHARAOH', 'trackName': 'Other Remix'},
        ]
        monkeypatch.setattr(ITunesGateway, 'get', staticmethod(lambda *args, **kwargs: {'results': items}))
        service = ArtistService()
    service._cache_put(source + ':' + sid, {
        'name': 'PHARAOH', 'albums': [{'source_id': '123', 'title': 'Release'}]})
    page = service.get_tracks_page({'source': source, 'source_id': sid})
    assert [track['title'] for track in page['tracks']] == ['Track (Official Remix)']
    assert page['has_more'] is False and page['next_offset'] == 1


def test_artist_singles_continuation_is_not_skipped_after_large_album_shelf():
    def album(index):
        return {'browseId': 'MPRE-' + str(index), 'title': 'Release ' + str(index),
                'artists': [{'name': 'PHARAOH', 'id': 'UC-artist'}]}

    yt = SimpleNamespace(
        get_artist_albums=lambda *args, **kwargs: [album(1001), album(1002)],
        search=lambda *args, **kwargs: [],
    )
    service = ArtistService(SimpleNamespace(_ytmusic=yt))
    raw = {'albums': {'results': [album(index) for index in range(121)]},
           'singles': {'results': [album(1000)], 'params': 'singles-continuation'}}
    albums = service._collect_albums(yt, 'UC-artist', raw, 'PHARAOH')
    assert {item['source_id'] for item in albums} == {
        'MPRE-' + str(index) for index in [*range(121), 1000, 1001, 1002]}


def test_artist_profile_initial_tracks_do_not_display_duplicate_catalog_ids():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const rendered = [];
const track = {id:'spotify_1', source:'spotify', title:'Song', artist:'PHARAOH'};
const context = vm.createContext({
    bridgeProfile: {tracks: [track, {...track}], tracks_has_more:false},
    tracksList: {set innerHTML(value) {rendered.length=0}, appendChild(track) {rendered.push(track)}},
    btnTracksToggle: {classList:{toggle() {}}},
    window: {}, renderIcons() {}, getCurrentTrack() {return null},
    createTrackElement(track) {return track},
    currentArtistTracks: [], artistTracksExpanded:false,
});
const text = SOURCE;
const begin = text.indexOf('// Popular tracks (Top 5 default');
const end = text.indexOf('// Play All and Shuffle actions', begin);
assert.ok(begin >= 0 && end > begin, 'exercise the shipped artist catalogue rendering');
vm.runInContext(text.slice(begin,end), context);
assert.equal(rendered.length,1,'the same catalogue recording must appear only once before pagination');
""".replace('SOURCE', js_source('artist_profile.js')))


def test_youtube_discography_resumes_failed_continuation_without_skipping_albums():
    calls = []

    def page(album_id, continuation=None):
        renderer = {'items': [{'musicTwoRowItemRenderer': {
            'title': {'runs': [{'text': album_id, 'navigationEndpoint': {'browseEndpoint': {'browseId': album_id}}}]},
            'subtitle': {'runs': [{'text':'Album'},{'text':' · '},{'text':'2026'}]}}}]}
        if continuation:
            renderer['continuations'] = [{'nextContinuationData': {'continuation': continuation}}]
        return {'continuationContents': {'gridContinuation': renderer}}

    def send(endpoint, body, continuation):
        calls.append(continuation)
        if len(calls) == 1:
            return page('MPRE-first', 'next-page')
        if len(calls) == 2:
            raise ConnectionError('temporary failure')
        assert 'next-page' in continuation
        return page('MPRE-second')

    yt = SimpleNamespace(_send_request=send, search=lambda *a, **k: [],
                         get_album=lambda sid: {'tracks': [{'videoId':sid, 'title':'Same title',
                             'artists':[{'name':'Artist','id':'UC-artist'}]}]})
    service = ArtistService(SimpleNamespace(_ytmusic=yt))
    service._cache_put('youtube:UC-artist', {'name':'Artist', 'albums':[],
        'catalog_state':{'initialized':True, 'pending':[{'params':'albums', 'continuation':None, 'visited':[]}]}})
    ref = {'source':'youtube','source_id':'UC-artist'}
    first = service.get_tracks_page(ref, 0)
    assert first['retryable'] and first['catalog_partial'] and first['has_more']
    assert first['next_offset'] == 1
    second = service.get_tracks_page(ref, first['next_offset'])
    assert not second['has_more'] and not second['catalog_partial']
    assert [t['source_id'] for t in first['tracks'] + second['tracks']] == ['MPRE-first','MPRE-second']
    assert [a['source_id'] for a in second['albums']] == ['MPRE-first','MPRE-second']


def test_deezer_album_and_track_cursors_resume_without_losing_versions(monkeypatch):
    service = ArtistService()
    calls = []
    failed = False

    def get(path, **params):
        nonlocal failed
        index = params.get('index', 0)
        calls.append((path, index))
        if path == 'artist/77/albums':
            return {'data':[{'id':10+index, 'title':'Release'}], 'next':'next' if index == 0 else None}
        if path == 'album/10/tracks' and index == 1 and not failed:
            failed = True
            raise ConnectionError('temporary failure')
        return {'data':[{'id':100+index if path == 'album/10/tracks' else 200,
                         'title':'Same title', 'artist':{'id':77, 'name':'Artist'}}],
                'next':'next' if path == 'album/10/tracks' and index == 0 else None}

    monkeypatch.setattr(service.catalog, '_deezer_get', get)
    service._cache_put('deezer:77', {'name':'Artist','albums':[],
        'catalog_state':{'next_index':0, 'track_offsets':{}}})
    ref = {'source':'deezer', 'source_id':'77'}
    first = service.get_tracks_page(ref,0)
    assert first['retryable'] and first['next_offset'] == 0
    second = service.get_tracks_page(ref,0)
    assert second['next_offset'] == 1 and second['has_more']
    third = service.get_tracks_page(ref,1)
    assert third['next_offset'] == 2 and not third['has_more']
    assert [t['source_id'] for p in (first,second,third) for t in p['tracks']] == ['100','101','200']
    assert calls.count(('album/10/tracks',0)) == 1, 'completed track pages must not be fetched again'
