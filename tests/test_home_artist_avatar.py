import json
from types import SimpleNamespace
from tests.jsdom import run_node, source


def test_photo_overlays_letter_until_loaded_then_replaces_it():
    home = json.loads(source('home.js'))
    start = home.index('function applyArtistAvatar(')
    end = home.index('\nfunction requestArtistAvatars', start)
    run_node("import assert from 'node:assert/strict';\n" + r"""
let fallbackRemoved=false;
const fallback={remove(){fallbackRemoved=true;}};
let photo;
const cover={querySelector(s){return s==='img'?null:s==='.artist-avatar-fallback'?fallback:null;},appendChild(img){photo=img;}};
const card={querySelector(s){return s==='.feed-card-title'?{textContent:'HOME'}:cover;}};
const document={querySelectorAll(){return [card];},createElement(){return {style:{},listeners:{},addEventListener(n,fn){this.listeners[n]=fn;}};}};
const getCoverUrl=()=>'/cover/photo';
const loadAvatarStore=()=>({});const saveAvatarStore=()=>{};
""" + home[start:end] + r"""
applyArtistAvatar('HOME','https://example.org/photo.jpg');
assert.match(photo.style.cssText,/position:absolute/,'photo must occupy the same rectangle as the fallback');
assert.equal(fallbackRemoved,false,'keep the letter while the image loads');
photo.listeners.load();
assert.equal(fallbackRemoved,true,'loaded photo replaces letter');
""")


def test_confirmed_deezer_artist_photo_is_used_without_another_lookup():
    from services.artist_service import ArtistService
    service = ArtistService.__new__(ArtistService)
    service.catalog = SimpleNamespace(resolve_artist=lambda *args, **kwargs: {
        'status': 'found', 'name': 'HOME',
        'profile_data': {'picture_xl': 'https://example.org/home.jpg'},
    })
    service.submit = lambda task: (task(), True)[1]
    service._resolve_metadata_fallback = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError('confirmed photo must not trigger a redundant network lookup'))
    results = []
    service.get_avatars(['HOME'], callback=results.append)
    assert results == [{'HOME': 'https://example.org/home.jpg'}]


def test_failed_artist_does_not_prevent_later_photos():
    from services.artist_service import ArtistService
    service = ArtistService.__new__(ArtistService)
    def resolve(name, **kwargs):
        if name == 'Unavailable':
            raise TimeoutError()
        return {'status': 'found', 'profile_data': {'picture_xl': 'https://example.org/photo.jpg'}}
    service.catalog = SimpleNamespace(resolve_artist=resolve)
    service.submit = lambda task: (task(), True)[1]
    results = []
    service.get_avatars(['Unavailable', 'HOME', 'Gorillaz'], callback=results.append)
    assert results == [{'HOME': 'https://example.org/photo.jpg'},
                       {'Gorillaz': 'https://example.org/photo.jpg'}]


def test_avatar_search_rejects_unrelated_first_result():
    from services.deezer_service import DeezerService
    service = DeezerService()
    service._get = lambda *args, **kwargs: {'data': [
        {'id': 1, 'name': 'Big Kuza', 'picture_xl': 'https://example.org/wrong.jpg'},
        {'id': 2, 'name': 'BG Muz', 'picture_xl': 'https://example.org/right.jpg'},
    ]}
    assert service.get_artist('BG Muz')['avatar_url'] == 'https://example.org/right.jpg'
    service._get = lambda *args, **kwargs: {'data': [
        {'id': 1, 'name': 'Big Kuza', 'picture_xl': 'https://example.org/wrong.jpg'}]}
    assert service.get_artist('BG Muz') == {}


def test_photo_lookup_passes_recording_hint_and_resolves_collaboration():
    from services.artist_service import ArtistService
    service = ArtistService.__new__(ArtistService)
    calls = []
    def resolve(name, **kwargs):
        calls.append((name, kwargs.get('artist_ref')))
        if name == 'VØJ, Narvent':
            return {'status': 'not_found'}
        return {'status': 'found', 'profile_data': {'picture_xl': 'https://example.org/voj.jpg'}}
    service.catalog = SimpleNamespace(resolve_artist=resolve)
    service.submit = lambda task: (task(), True)[1]
    results = []
    service.get_avatars(['VØJ, Narvent'], callback=results.append,
                        hints={'VØJ, Narvent': 'Memory Reboot'})
    assert calls == [('VØJ, Narvent', {'hint_track': 'Memory Reboot'}),
                     ('VØJ', {'hint_track': 'Memory Reboot'})]
    assert results == [{'VØJ, Narvent': 'https://example.org/voj.jpg'}]


def test_source_photo_requires_matching_recording_and_uploader():
    from services.artist_service import ArtistService
    service = ArtistService.__new__(ArtistService)
    service.settings = None
    service.catalog = SimpleNamespace(resolve_artist=lambda *args, **kwargs: {'status': 'not_found'})
    service.submit = lambda task: (task(), True)[1]
    for actual_artist, actual_title, expected in [
        ('Cube Rubik', 'Song', True), ('Other', 'Song', False), ('Cube Rubik', 'Other', False),
    ]:
        results = []
        service.get_avatars(['Cube Rubik'], callback=results.append,
            source_tracks={'Cube Rubik': [{'source_id': '1', 'title': 'Song'}]},
            metadata_loader=lambda track: {'artist': actual_artist, 'title': actual_title,
                                          'artist_avatar_url': 'https://example.org/profile.jpg'})
        assert bool(results) is expected


def test_youtube_channel_photo_uses_foreground_not_banner():
    from services.youtube_service import YouTubeService
    service = YouTubeService.__new__(YouTubeService)
    service._ytmusic = SimpleNamespace(
        get_song=lambda video: {'videoDetails': {'channelId': 'UCchannel', 'author': 'BG Muz', 'title': 'Song'}},
        _send_request=lambda *args: {'header': {'musicVisualHeaderRenderer': {
            'thumbnail': {'musicThumbnailRenderer': {'thumbnail': {'thumbnails': [{'url': 'banner'}]}}},
            'foregroundThumbnail': {'musicThumbnailRenderer': {'thumbnail': {'thumbnails': [
                {'url': 'photo', 'width': 544, 'height': 544}]}}},
        }}},
    )
    assert service.get_artist_avatar_metadata('MsH08whXHls') == {
        'artist': 'BG Muz', 'title': 'Song', 'artist_avatar_url': 'photo'}
