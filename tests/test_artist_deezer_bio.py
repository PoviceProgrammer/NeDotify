"""Artist descriptions must use the same fallback for every catalogue."""
from types import SimpleNamespace

from services.artist_service import ArtistService


def test_deezer_profile_enriches_missing_description(monkeypatch):
    service = ArtistService(SimpleNamespace())
    monkeypatch.setattr(service, 'submit', lambda task: (task(), True)[1])
    monkeypatch.setattr(service.catalog, 'resolve_artist', lambda *a: {
        'status': 'found', 'source': 'deezer', 'source_id': '123', 'name': 'Test Artist',
        'profile_data': {'picture_xl': 'https://example.org/artist.jpg'}})
    monkeypatch.setattr(service.catalog, '_call', lambda *a: {'data': []})
    calls = []
    def enrich(name, **kwargs):
        calls.append((name, kwargs))
        return kwargs['avatar_url'], 'Original biography'
    monkeypatch.setattr(service, '_resolve_metadata_fallback', enrich)
    monkeypatch.setattr(service, '_translate_bio', lambda text, **kwargs: ('Описание артиста', text))
    profiles = []
    service.get_profile('Test Artist', callback=profiles.append)
    assert profiles[0]['bio'] == 'Описание артиста'
    assert profiles[0]['bio_original'] == 'Original biography'
    assert profiles[0]['avatar_url'] == 'https://example.org/artist.jpg'
    assert calls[0][0] == 'Test Artist'
