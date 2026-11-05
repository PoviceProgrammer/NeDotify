"""An artist candidate remains the same Deezer entity through profile selection."""
from types import SimpleNamespace
import threading
import time

from services.artist_service import ArtistService
from services.catalog_service import CatalogService
from services.itunes_gateway import ITunesGateway, CatalogueUnavailable


def test_deezer_artist_candidate_to_selected_profile(monkeypatch):
    svc = ArtistService(SimpleNamespace(_ytmusic=None))
    monkeypatch.setattr(ITunesGateway,'get',lambda *a,**k: (_ for _ in ()).throw(CatalogueUnavailable('offline')))
    calls = []
    def get(path, **params):
        calls.append(path)
        if path == 'search/artist':
            return {'data':[{'id':5,'name':'Adele & Other','type':'artist'},
                            {'id':75798,'name':'Adele','type':'artist','picture_big':'https://example.org/adele.jpg'},
                            {'id':999,'title':'Adele','type':'track'}]}
        if path == 'artist/75798':
            return {'id':75798,'type':'artist','name':'Adele','nb_fan':100,'picture_big':'https://example.org/adele.jpg'}
        if path == 'artist/75798/top':
            return {'data':[{'id':1,'title':'Hello','artist':{'id':75798,'name':'Adele'}},
                            {'id':2,'title':'Hello','artist':{'id':999,'name':'Cover Artist'}}]}
        raise AssertionError(path)
    monkeypatch.setattr(svc.catalog,'_deezer_get',get,raising=False)
    result = svc.catalog.resolve_artist('Adele',{'require_candidates':True})
    assert result['status'] == 'ambiguous'
    assert result['candidates'] == [dict(result['candidates'][0],source='deezer',source_id='75798',type='artist',name='Adele')]
    done=threading.Event();profiles=[];errors=[]
    svc.get_profile('Adele',artist_ref=result['candidates'][0],callback=lambda value:(profiles.append(value),done.set()),error_callback=lambda value:(errors.append(value),done.set()))
    assert done.wait(2)
    assert not errors
    profile=profiles[0]
    assert (profile['source'],profile['source_id'],profile['name']) == ('deezer','75798','Adele')
    assert profile['verified'] and profile['avatar_url']
    assert [t['source_id'] for t in profile['tracks']] == ['1']
    assert profile['tracks'][0]['source'] == 'deezer'
    assert calls == ['search/artist','artist/75798','artist/75798/top']


def test_deezer_artist_rejects_mismatched_profile_id(monkeypatch):
    svc=CatalogService()
    monkeypatch.setattr(svc,'_deezer_get',lambda *a,**k:{'id':123,'type':'artist','name':'Other'},raising=False)
    result=svc.resolve_artist('Adele',{'source':'deezer','source_id':'75798'})
    assert result['status'] == 'not_found'


def test_artist_primary_success_never_initializes_deezer(monkeypatch):
    yt=SimpleNamespace(search=lambda *a,**k:[{'artist':'Adele','browseId':'UC-adele'}])
    svc=CatalogService(SimpleNamespace(_ytmusic=yt))
    def unexpected(*a,**k):
        raise AssertionError('unnecessary backup catalogue request')
    monkeypatch.setattr(svc,'_deezer_get',unexpected)
    monkeypatch.setattr(ITunesGateway,'get',unexpected)
    result=svc.resolve_artist('Adele',{'require_candidates':True})
    assert result['status'] == 'ambiguous'
    assert result['candidates'][0]['source'] == 'youtube'


def test_artist_itunes_success_never_calls_deezer(monkeypatch):
    svc=CatalogService()
    monkeypatch.setattr(ITunesGateway,'get',lambda *a,**k:{'results':[{'artistId':1,'artistName':'Adele'}]})
    def unexpected(*a,**k):
        raise AssertionError('unnecessary Deezer fallback')
    monkeypatch.setattr(svc,'_deezer_get',unexpected)
    result=svc.resolve_artist('Adele',{'require_candidates':True})
    assert result['status'] == 'ambiguous'
    assert result['candidates'][0]['source'] == 'itunes'


def test_deezer_search_never_accepts_track_as_artist(monkeypatch):
    svc=CatalogService()
    monkeypatch.setattr(ITunesGateway,'get',lambda *a,**k:{'results':[]})
    monkeypatch.setattr(svc,'_deezer_get',lambda *a,**k:{'data':[{'id':1,'type':'track','name':'Adele'}]})
    result=svc.resolve_artist('Adele',{'require_candidates':True})
    assert result['status'] == 'not_found'


def test_deezer_selected_identity_is_persisted_and_reused(api, monkeypatch):
    from services.artist_identity import artist_binding, artist_aliases
    api._store_artist_binding('Local Adele',{'source':'deezer','source_id':'75798','name':'Adele'})
    binding=artist_binding(api._core.settings,'Local Adele')
    assert binding['catalog_ids'] == {'deezer':'75798'}
    assert artist_aliases(api._core.settings)['local adele'] == 'Adele'
    svc=CatalogService(settings=api._core.settings)
    calls=[]
    def get(path,**params):
        calls.append(path)
        return {'id':75798,'type':'artist','name':'Adele'}
    monkeypatch.setattr(svc,'_deezer_get',get)
    result=svc.resolve_artist('Local Adele')
    assert result['status'] == 'found'
    assert result['source_id'] == '75798'
    assert calls == ['artist/75798']
