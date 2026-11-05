import time
from services.recommendation_discovery import RecommendationDiscovery


class Catalogue:
    _id = staticmethod(str)
    def __init__(self): self.calls=[]
    def _get(self,path,**params):
        self.calls.append(path)
        data={'search/artist':[{'id':1,'name':'Artist'}], 'artist/1/radio':[{'id':10}],
              'search':[{'id':5,'title':'Seed','duration':180,'artist':{'id':1,'name':'Artist'}}],
              'artist/1/related':[{'id':2}], 'artist/2/top':[{'id':11},{'id':10}]}
        return {'data':data.get(path,[])}
    def _track(self,item):
        return dict(source='deezer',source_id=str(item['id']),title='Song',artist='Related',duration=180)


def test_catalogue_radio_and_related_are_real_metadata_without_stream_resolution():
    provider=Catalogue()
    result=RecommendationDiscovery(deezer=provider).get_candidates([{'artist':'Artist','title':'Seed','duration':180}],['Artist'],10)
    assert [r['source_id'] for r in result]==['10','11']
    assert result[1]['recommendation_source']=='deezer_related'
    assert result[1]['recommendation_seed_artists']==['artist']
    assert all('stream_url' not in r for r in result)


def test_unmatched_uploader_does_not_select_unrelated_catalogue_artist():
    provider=Catalogue()
    assert RecommendationDiscovery(deezer=provider).get_candidates([],['Uploader'],10)==[]
    assert provider.calls==['search/artist']


def test_disabled_or_expired_catalogue_makes_no_requests():
    provider=Catalogue()
    class Settings:
        def get(self,*args): return False
    assert RecommendationDiscovery(Settings(),provider).get_candidates([],['Artist'])==[]
    assert RecommendationDiscovery(deezer=provider).get_candidates([],['Artist'],deadline=time.monotonic()-1)==[]
    assert provider.calls==[]


def test_exact_artist_name_without_recording_identity_is_not_enough():
    provider=Catalogue()
    assert RecommendationDiscovery(deezer=provider).get_candidates([{'artist':'Artist','title':'Other song','duration':180}],['Artist'],10)==[]
    assert 'artist/1/radio' not in provider.calls


def test_seed_recording_disambiguates_identical_artist_names():
    class Homonyms(Catalogue):
        def _get(self,path,**params):
            if path=='search/artist':
                self.calls.append(path)
                return {'data':[{'id':1,'name':'Artist'},{'id':99,'name':'Artist'}]}
            return super()._get(path,**params)
    provider=Homonyms()
    result=RecommendationDiscovery(deezer=provider).get_candidates([{'artist':'Artist','title':'Seed','duration':180}],['Artist'],10)
    assert len(result)==2
    assert 'artist/1/radio' in provider.calls
    assert 'artist/99/radio' not in provider.calls


def test_seed_search_accepts_catalogue_that_returns_no_structured_query_results():
    class PlainSearch(Catalogue):
        def _get(self,path,**params):
            if path=='search' and ':' in params.get('q',''):
                return {'data':[]}
            return super()._get(path,**params)
    result=RecommendationDiscovery(deezer=PlainSearch()).get_candidates([{'artist':'Artist','title':'Seed','duration':180}],['Artist'],10)
    assert len(result)==2
