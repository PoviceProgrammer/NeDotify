"""End-to-end bridge contracts for editable, non-destructive collections."""
from core.bridge import BridgeApi
import pytest


def test_playlist_rename_and_remove_preserve_tracks_and_other_collections(api, tmp_db):
    track = tmp_db.add_track(title='Keep me', artist='Artist', source='local')
    first = tmp_db.create_playlist('First')
    second = tmp_db.create_playlist('Second')
    tmp_db.add_to_playlist(first, track)
    tmp_db.add_to_playlist(second, track)
    bridge = BridgeApi(api)
    assert bridge.rename_playlist(first, ' Renamed ')['success']
    assert next(p for p in bridge.get_playlists() if p['id'] == first)['name'] == 'Renamed'
    assert bridge.remove_from_playlist(first, track)['success']
    assert bridge.get_playlist_tracks(first)['tracks'] == []
    assert [t['id'] for t in bridge.get_playlist_tracks(second)['tracks']] == [track]
    assert tmp_db.get_track(track)['title'] == 'Keep me'


def test_system_playlist_cannot_be_renamed_or_edited(api, tmp_db):
    system = tmp_db.create_playlist('Скачанное', is_system=True)
    assert not api.rename_playlist(system, 'Oops')['success']
    assert not api.remove_from_playlist(system, 1)['success']


def test_disabled_music_source_completes_search_without_provider_call(api, core_ns, emitted):
    core_ns.settings.set('services', 'youtube_enabled', False)
    core_ns.youtube.search = lambda *a, **k: (_ for _ in ()).throw(AssertionError('disabled source used'))
    assert api.search('a song', source='youtube')['tracks'] == []
    assert [name for name, _ in emitted] == ['search_completed']


def test_volume_read_is_public(api):
    assert BridgeApi(api).get_volume() == api.get_volume()


def test_new_renderer_replays_queue_once_per_document(api, core_ns, emitted):
    api.ui_ready('document-one')
    emitted.clear()
    api.ui_ready('document-one')
    assert emitted == []
    api.ui_ready('document-two')
    assert any(name == 'queue_updated' for name, _ in emitted)


@pytest.mark.parametrize('value', [True, '12', -1, 25, float('inf'), float('nan')])
def test_radius_rejects_values_outside_the_ui_contract(api, core_ns, value):
    before = core_ns.settings.get('interface', 'border_radius')
    assert api.save_setting('border_radius', value, 'interface') is False
    assert core_ns.settings.get('interface', 'border_radius') == before


@pytest.mark.parametrize('source', ['youtube', 'soundcloud'])
def test_source_opt_out_requires_a_boolean(api, core_ns, source):
    assert api.save_setting(source + '_enabled', 'false', 'services') is False
    assert api.save_setting(source + '_enabled', False, 'services') is True
    assert core_ns.settings.get('services', source + '_enabled') is False


def test_feedback_does_not_acknowledge_a_failed_durable_write(api, core_ns, monkeypatch):
    monkeypatch.setattr(core_ns.settings, 'sync_flush_now', lambda: False, raising=False)
    assert api.set_recommendation_feedback({'artist':'Artist', 'title':'Song'}, 'track')['success'] is False
    assert not api.get_recommendation_feedback({'artist':'Artist', 'title':'Song'})['track']
