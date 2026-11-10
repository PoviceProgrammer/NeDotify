"""Windows discovery and album regressions; all provider responses are fixtures."""
from types import SimpleNamespace
import importlib
import threading

import pytest

from services.catalog_service import CatalogService
from services.taste_profile import UserTasteProfile
from tests.helpers import fetch, recommendations, track
from tests.jsdom import run_node, source


@pytest.mark.parametrize('mode', ['balanced', 'discovery'])
def test_home_discovery_does_not_fill_with_playlist_or_history(recommendations, mode):
    recommendations.settings = SimpleNamespace(get=lambda category, key, default=None:
        mode if key == 'recommendation_mode' else default)
    profile = UserTasteProfile()
    profile.playlist_tracks = [track('saved', 'Saved', 'Favorite Artist')]
    profile.recent_history = [track('current', 'Current'), track('heard', 'Heard')]
    profile.favorite_tracks = [track('liked', 'Liked')]
    recommendations._collect_candidates = lambda *a, **kw: [
        track('reupload', 'Saved (Official Audio)', 'Favorite Artist'),
        track('other-provider', 'Heard', source='soundcloud'),
        track('new', 'Discovery', 'Favorite Artist')]
    result = recommendations._feed_tracks(profile, 20)
    assert [item['source_id'] for item in result] == ['new']


def test_home_discovery_does_not_hide_outage_with_saved_tracks(recommendations):
    profile = UserTasteProfile()
    profile.favorite_tracks = [track('saved', 'Saved')]
    def offline(*args, **kwargs):
        raise RuntimeError('Provider offline')
    recommendations._collect_candidates = offline
    with pytest.raises(RuntimeError, match='Provider offline'):
        recommendations._feed_tracks(profile, 20)


def test_home_familiar_mode_retains_explicit_library_fallback(recommendations):
    recommendations.settings = SimpleNamespace(get=lambda category, key, default=None:
        'familiar' if key == 'recommendation_mode' else default)
    profile = UserTasteProfile()
    profile.favorite_tracks = [track('saved', 'Saved')]
    recommendations._collect_candidates = lambda *a, **kw: []
    assert recommendations._feed_tracks(profile, 20)[0]['source_id'] == 'saved'


@pytest.mark.parametrize('with_discovery', [True, False])
def test_visible_for_you_mixes_do_not_copy_library(recommendations, with_discovery):
    profile = UserTasteProfile()
    known = [track('saved-a', 'Saved A', 'Artist A'), track('saved-b', 'Saved B', 'Artist B')]
    profile.top_tracks = profile.playlist_tracks = known
    profile.top_artists = [{'name': 'Artist A', 'play_count': 5}, {'name': 'Artist B', 'play_count': 4}]
    recommendations._profile = lambda history=None: profile
    recommendations._collect_candidates = lambda *a, **kw: known + ([
        track('new', 'Discovery', 'Artist A')] if with_discovery else [])
    mixes = fetch(recommendations.get_mixes)
    assert all(row['source_id'] == 'new' for mix in mixes for row in mix['tracks'])
    assert bool(mixes) is with_discovery


def test_youtube_album_verified_channel_accepts_changed_display_name():
    yt = SimpleNamespace(get_album=lambda sid: {'title': 'Release',
        'artists': [{'name': 'New Artist Name', 'id': 'UC-artist'}],
        'tracks': [{'videoId': 'song', 'title': 'Song', 'duration_seconds': 180}]})
    catalog = CatalogService(SimpleNamespace(_ytmusic=yt))
    result = catalog.album_details({'source': 'youtube', 'source_id': 'MPRE-release',
        'title': 'Release', 'artist': 'Old Artist Name', 'artist_channel_id': 'UC-artist'})
    assert result['status'] == 'found'
    assert result['album']['artist'] == 'New Artist Name'


def test_youtube_album_cache_does_not_bypass_requested_artist_identity():
    yt = SimpleNamespace(get_album=lambda sid: {'title': 'Release',
        'artists': [{'name': 'Same Name', 'id': 'UC-one'}], 'tracks': []})
    catalog = CatalogService(SimpleNamespace(_ytmusic=yt))
    reference = {'source': 'youtube', 'source_id': 'MPRE-release', 'title': 'Release',
        'artist': 'Same Name', 'artist_channel_id': 'UC-one'}
    assert catalog.album_details(reference)['status'] == 'found'
    assert catalog.album_details(dict(reference, artist_channel_id='UC-two'))['status'] == 'not_found'


def test_youtube_album_tracklist_deduplicates_recording_ids():
    song = {'videoId': 'song', 'title': 'Song', 'duration_seconds': 180}
    yt = SimpleNamespace(get_album=lambda sid: {'title': 'Release',
        'artists': [{'name': 'Artist'}], 'tracks': [song, dict(song),
            dict(song, videoId='unavailable', isAvailable=False)]})
    result = CatalogService(SimpleNamespace(_ytmusic=yt)).album_details({
        'source': 'youtube', 'source_id': 'MPRE-release', 'title': 'Release', 'artist': 'Artist'})
    assert [row['source_id'] for row in result['tracks']] == ['song']


def test_youtube_filtered_search_keeps_sdk_album_shelf(monkeypatch):
    """Replay the SDK language-sensitive shelf filter without live requests."""
    from services.youtube_service import YouTubeService
    sdk_search = importlib.import_module('ytmusicapi.mixins.search')
    service = YouTubeService()
    client = service._ytmusic
    parsed_album = {'browseId': 'MPRE-release', 'title': 'Release', 'resultType': 'album',
                    'artists': [{'name': 'Artist', 'id': 'UC-artist'}]}
    monkeypatch.setattr(sdk_search, 'parse_search_results', lambda *a: [parsed_album])
    monkeypatch.setattr(service, '_prepare_search_headers', lambda: None)
    def response(*args, **kwargs):
        label = 'Альбомы' if client.context['context']['client']['hl'] == 'ru' else 'Albums'
        return {'contents': {'sectionListRenderer': {'contents': [{'musicShelfRenderer': {
            'title': {'runs': [{'text': label}]},
            'contents': [{'musicResponsiveListItemRenderer': {}}]}}]}}}
    monkeypatch.setattr(client, '_send_request', response)
    done, box = threading.Event(), {}
    try:
        service.search('Artist Release', result_type='albums',
            callback=lambda rows: (box.update(rows=rows), done.set()),
            error_callback=lambda error: (box.update(error=error), done.set()))
        assert done.wait(2)
        assert 'error' not in box
        assert [row['source_id'] for row in box['rows']] == ['MPRE-release']
    finally:
        service._executor.shutdown(wait=True, cancel_futures=True)
        service._playback_executor.shutdown(wait=True, cancel_futures=True)


def test_deezer_album_retains_authoritative_release_metadata(monkeypatch):
    from services.deezer_service import DeezerService
    metadata = {'id': 7, 'title': 'Release', 'artist': {'name': 'Artist'},
        'release_date': '2026-05-10', 'record_type': 'ep', 'nb_tracks': 1,
        'cover_xl': 'https://example.com/high-res.jpg'}
    monkeypatch.setattr(DeezerService, '_get', lambda self, path, **kw: metadata if path == 'album/7'
        else {'data': [{'id': 8, 'title': 'Song', 'artist': {'name': 'Artist'}, 'duration': 180}]})
    result = CatalogService().album_details({'source': 'deezer', 'source_id': '7', 'title': 'Release'})
    assert result['status'] == 'found'
    assert result['album']['artist'] == 'Artist'
    assert result['album']['release_date'] == '2026-05-10'
    assert result['album']['year'] == '2026'
    assert result['album']['album_type'] == 'ep'
    assert result['album']['cover_url'] == metadata['cover_xl']


def test_open_album_modal_updates_summary_from_verified_details():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const summary = new Map(['title','artist','info','kind','cover'].map(key =>
    [key, {textContent:'Old',style:{},src:''}]));
const modal = {style:{}, querySelector(selector) {
    return summary.get(selector.replace('[data-album-detail-','').replace(']',''));
}};
const tracks = {appendChild() {}};
const play = {disabled:true,addEventListener() {}};
const elements = new Map([['album-detail-modal',modal], ['album-modal-tracks',tracks],
    ['btn-play-full-album',play]]);
const context = vm.createContext({console,
    albumModalGeneration:0, window:{},
    document:{getElementById:id=>elements.get(id)},
    escapeHtml:text=>String(text),renderIcons() {},openModalFocusTrap() {},
    createTrackElement() {return {}},getCurrentTrack() {return null},
    fetchAlbumDetails:async()=>({status:'found',verified:true,
        album:{title:'Verified Title',artist:'Verified Artist',year:'2026',album_type:'ep',
            cover_url:'https://example.com/verified.jpg',track_count:1},tracks:[{title:'Song'}]}),
});
const code = SOURCE;
const begin=code.indexOf('export async function openAlbumModal(');
const end=code.indexOf('\nwindow.openAlbumModal',begin);
vm.runInContext(code.slice(begin,end).replace('export ',''),context);
await context.openAlbumModal({title:'Old',artist:'Old'});
assert.equal(summary.get('title').textContent,'Verified Title');
assert.equal(summary.get('artist').textContent,'Verified Artist');
assert.match(summary.get('info').textContent,/2026/);
assert.equal(summary.get('kind').textContent,'EP');
assert.equal(summary.get('cover').src,'https://example.com/verified.jpg');
assert.equal(play.disabled,false);
""".replace('SOURCE', source('search.js')))
