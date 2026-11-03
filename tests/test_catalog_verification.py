"""Catalogue identities must never be inferred from a random fuzzy hit."""
from types import SimpleNamespace
import threading

import pytest

from services.catalog_service import CatalogService, credited_to
from services.artist_identity import artist_aliases, artist_binding, canonical_artist
from services.itunes_gateway import ITunesGateway, CatalogueUnavailable
from services.music_matching import similarity, title_metadata


class FakeYT:
    def __init__(self, hits=None):
        self.hits = hits or []
        self.calls = 0
        self.profiles = {}
        self.albums = {}

    def search(self, *args, **kwargs):
        self.calls += 1
        return self.hits

    def get_artist(self, sid):
        return self.profiles.get(sid, {})

    def get_album(self, sid):
        return self.albums.get(sid, {})


@pytest.fixture
def catalog(monkeypatch):
    monkeypatch.setattr(ITunesGateway, 'get', lambda *a, **k: {'results': []})
    yt = FakeYT()
    return CatalogService(SimpleNamespace(_ytmusic=yt)), yt


def test_fuzzy_artist_requires_choice_and_same_id_is_deduplicated(catalog):
    service, yt = catalog
    yt.hits = [{'artist': 'PHARAOH', 'browseId': 'UC-one'}] * 2
    result = service.resolve_artist('PHARAO')
    assert result['status'] == 'ambiguous'
    assert [c['source_id'] for c in result['candidates']] == ['UC-one']


def test_homonyms_are_not_automatically_selected(catalog):
    service, yt = catalog
    yt.hits = [{'artist': 'Same', 'browseId': 'UC-one'}, {'artist': 'Same', 'browseId': 'UC-two'}]
    assert service.resolve_artist('Same')['status'] == 'ambiguous'


def test_exact_alias_resolves_identity_not_first_hit(catalog):
    service, yt = catalog
    yt.hits = [{'artist': 'Someone Else', 'browseId': 'UC-wrong'}, {'artist': 'PHARAOH', 'browseId': 'UC-real'}]
    yt.profiles['UC-real'] = {'name': 'PHARAOH', 'songs': {}}
    result = service.resolve_artist('Фараон')
    assert result['status'] == 'found'
    assert result['source_id'] == 'UC-real'


def test_no_match_is_cached_but_network_failure_is_not(catalog, monkeypatch):
    service, yt = catalog
    assert service.resolve_artist('Nonexistent')['status'] == 'not_found'
    assert service.resolve_artist('Nonexistent')['status'] == 'not_found'
    assert yt.calls == 1
    service._results.clear()
    monkeypatch.setattr(yt, 'search', lambda *a, **k: (_ for _ in ()).throw(ConnectionError('offline')))
    assert service.resolve_artist('Name')['status'] == 'unavailable'
    assert not service._results
    monkeypatch.setattr(yt, 'search', lambda *a, **k: [{'artist': 'Name', 'browseId': 'UC-real'}])
    yt.profiles['UC-real'] = {'name': 'Name'}
    assert service.resolve_artist('Name')['status'] == 'found'


def test_credit_requires_matching_id_or_exact_alias():
    assert not credited_to({'artists': [{'name': 'Artist Extra', 'id': 'wrong'}]}, 'Artist', 'real')
    assert not credited_to({'artists': [{'name': 'Artist Extra'}]}, 'Artist')
    assert credited_to({'artists': [{'name': 'Фараон'}]}, 'PHARAOH')


def test_album_checks_catalogue_identity_and_real_tracklist(catalog):
    service, yt = catalog
    yt.albums['MPRE-real'] = {'title': 'Release', 'artists': [{'name': 'Artist'}], 'tracks': [
        {'videoId': 'video', 'title': 'First', 'duration_seconds': 180}, {'title': 'Unavailable'}]}
    album = {'source': 'youtube', 'source_id': 'MPRE-real', 'title': 'Release', 'artist': 'Artist'}
    result = service.album_details(album)
    assert result['status'] == 'found' and result['verified']
    assert [t['source_id'] for t in result['tracks']] == ['video']
    assert service.album_details(dict(album, artist='Someone Else'))['status'] == 'not_found'
    assert service.album_details(dict(album, source_id='ordinary-video'))['status'] == 'not_found'


def test_local_album_remains_available_without_claiming_verification(catalog):
    service, _ = catalog
    result = service.album_details({'source': 'local', 'title': 'My Album', 'artist': 'Me'}, lambda *a: [{'id': 1}])
    assert result['status'] == 'found' and result['verified'] is False
    assert result['tracks'] == [{'id': 1}]


def test_itunes_album_ignores_tracks_from_other_collections(catalog, monkeypatch):
    service, _ = catalog
    monkeypatch.setattr(ITunesGateway, 'get', lambda *a, **k: {'results': [
        {'wrapperType': 'collection', 'collectionType': 'Album', 'collectionId': 4, 'collectionName': 'Album', 'artistName': 'Me'},
        {'kind': 'song', 'trackId': 1, 'collectionId': 4, 'trackName': 'Right'},
        {'kind': 'song', 'trackId': 2, 'collectionId': 5, 'trackName': 'Wrong'}]})
    result = service.album_details({'source': 'spotify', 'source_id': '4', 'title': 'Album', 'artist': 'Me'})
    assert [t['title'] for t in result['tracks']] == ['Right']


def test_binding_survives_catalogue_failure_and_scoped_choice_does_not_merge_names(api, core_ns, settings_stub, catalog):
    service, yt = catalog
    api._store_artist_binding('Фараон', {'name': 'PHARAOH', 'source': 'youtube', 'source_id': 'UC-real'})
    aliases = artist_aliases(settings_stub)
    assert canonical_artist('PHARAOH', aliases) == canonical_artist('Фараон', aliases)
    api._store_artist_binding('Other', {'name': 'Same', 'source': 'youtube', 'source_id': 'UC-scoped'}, {'source': 'local', 'source_id': '3'})
    assert artist_binding(settings_stub, 'Other') is None
    assert artist_binding(settings_stub, 'Other', {'source': 'local', 'source_id': '3'})['catalog_ids']['youtube'] == 'UC-scoped'
    service.settings = settings_stub
    monkey = yt.get_artist
    yt.get_artist = lambda sid: (_ for _ in ()).throw(ConnectionError('offline'))
    assert service.resolve_artist('Фараон')['status'] == 'unavailable'
    assert artist_binding(settings_stub, 'Фараон')['catalog_ids']['youtube'] == 'UC-real'
    yt.get_artist = monkey


def test_bridge_preserves_event_names_and_structured_request_id(api, core_ns, emitted):
    core_ns.artists = SimpleNamespace(get_profile=lambda name, callback, **kwargs: callback({'status': 'ambiguous', 'candidates': [], 'artist': name}))
    result = api.get_artist_profile('Name', request_id='request')
    assert result['request_id'] == 'request'
    assert emitted[-1][0] == 'artist_profile_ready'
    assert emitted[-1][1]['request_id'] == 'request'
    assert emitted[-1][1]['status'] == 'ambiguous'
    core_ns.artists = SimpleNamespace(get_profile=lambda name, error_callback, **kwargs: error_callback({'status': 'not_found'}))
    api.get_artist_profile('Name', request_id='next')
    assert emitted[-1] == ('artist_profile_error', {'status': 'not_found', 'artist': 'Name', 'request_id': 'next'})


def test_short_names_and_meaningful_parentheses_are_preserved():
    assert similarity('Life', 'Live') == 0
    assert similarity('PHАRAOH', 'PHARAOH') != 1  # Cyrillic A is not transliterated
    assert title_metadata('Song (I Love You) [Official Audio]', 'Artist')['base_title'] == 'Song (I Love You)'
    assert title_metadata('Song (feat. Guest)', 'Artist')['artists'] == ['Artist', 'Guest']


def test_saved_scoped_ids_keep_homonyms_separate_and_refresh_taste(api, tmp_db, settings_stub):
    from services.taste_profile import UserTasteProfile
    one = tmp_db.add_track(title='One', artist='Same', source='youtube', source_id='one')
    two = tmp_db.add_track(title='Two', artist='Same', source='youtube', source_id='two')
    tmp_db.toggle_favorite(one); tmp_db.toggle_favorite(two)
    assert len(UserTasteProfile(settings_stub).build_from_db(tmp_db).top_artists) == 1
    api._store_artist_binding('Same', {'name': 'Same', 'source': 'youtube', 'source_id': 'UC-one'}, {'source': 'youtube', 'source_id': 'one'})
    api._store_artist_binding('Same', {'name': 'Same', 'source': 'youtube', 'source_id': 'UC-two'}, {'source': 'youtube', 'source_id': 'two'})
    profile = UserTasteProfile(settings_stub).build_from_db(tmp_db)
    assert len(profile.top_artists) == 2
    assert len({a['identity_key'] for a in profile.top_artists}) == 2


def test_album_bridge_drops_superseded_work_and_preserves_legacy_list(api, emitted, monkeypatch):
    pending = []
    monkeypatch.setattr(api, '_search_executor', SimpleNamespace(submit=pending.append))
    catalogue = SimpleNamespace(album_details=lambda *a, **k: {'status': 'found', 'tracks': [{'title': 'Real'}], 'verified': True})
    monkeypatch.setattr(api, '_catalog_service', lambda: catalogue)
    api.get_album_details({'source': 'youtube'}, 'old')
    api.get_album_details({'source': 'youtube'}, 'new')
    for run in pending:
        run()
    assert len(emitted) == 1 and emitted[0][0] == 'album_details_ready'
    assert emitted[0][1]['request_id'] == 'new'
    assert api.get_album_tracks({'source': 'youtube'}) == [{'title': 'Real'}]


# --- S4-001: a free-text query must not auto-open a single name match ---------

def test_require_candidates_never_autopicks_a_single_exact_hit(catalog):
    """The artists tab passes require_candidates: the user confirms the entity.

    Pre-fix a single name match was resolved into a full profile, so any
    query string equal to some channel's name opened that (possibly wrong)
    artist page.
    """
    service, yt = catalog
    yt.hits = [{'artist': 'Exact Name', 'browseId': 'UC-one'}]
    yt.profiles['UC-one'] = {'name': 'Exact Name', 'songs': {}}
    unmarked = service.resolve_artist('Exact Name')
    assert unmarked['status'] == 'found'  # entity-confirmed callers keep the shortcut

    service._results.clear()
    marked = service.resolve_artist('Exact Name', {'require_candidates': True})
    assert marked['status'] == 'ambiguous'
    assert [c['source_id'] for c in marked['candidates']] == ['UC-one']


def test_require_candidates_survives_multi_hits_and_not_found(catalog):
    service, yt = catalog
    yt.hits = [{'artist': 'Same Name', 'browseId': 'UC-1'}, {'artist': 'Same Name', 'browseId': 'UC-2'}]
    result = service.resolve_artist('Same Name', {'require_candidates': True})
    assert result['status'] == 'ambiguous' and len(result['candidates']) == 2

    service._results.clear()
    yt.hits = []
    assert service.resolve_artist('Nobody', {'require_candidates': True})['status'] == 'not_found'


def test_saved_binding_still_wins_over_require_candidates(catalog):
    """A previously confirmed choice (artist binding) keeps resolving directly."""
    service, yt = catalog

    class BindingSettings:
        def __init__(self, bindings):
            self._b = bindings
        def get(self, category, key, default=None):
            return self._b if key == 'artist_bindings' else default

    service.settings = BindingSettings({'exact name': {'catalog_ids': {'youtube': 'UC-bound'}, 'canonical_name': 'Exact Name'}})
    yt.profiles['UC-bound'] = {'name': 'Exact Name', 'songs': {}}
    result = service.resolve_artist('Exact Name', {'require_candidates': True})
    assert result['status'] == 'found' and result['source_id'] == 'UC-bound'
