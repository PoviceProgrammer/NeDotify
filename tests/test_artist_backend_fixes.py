"""
Unit tests for artist backend fixes:
- ART-002: youtube_service preserves artists list with browseId
- ART-007: artist bio HTML / Wikipedia footnotes / Last.fm tails sanitization
- ART-008: cascade fallback for artist avatar and bio (Deezer, Wikipedia, Last.fm)
- ART-009: remove_artist_binding in core/api.py
- ART-010: canonical_artist never returns @catalog hash & filter_artist_tracks works
- ART-011: homonym disambiguation via hint_track & discography isolation
- ART-015: search with result_type='artists' on YouTube and Deezer
- ART-017: KeyError: musicCarouselShelfRenderer resilience in _collect_albums
- ART-018: Cyrillic/Latin transliteration for artist candidates search
"""

import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from services.youtube_service import YouTubeService
from services.artist_service import ArtistService, clean_artist_bio
from services.artist_identity import canonical_artist, artist_aliases, binding_key, name_key
from services.catalog_service import CatalogService, credited_to
from services.deezer_service import DeezerService
from core.api import AppApi


# =====================================================================
# ART-002: youtube_service preserves artists list with browseId
# =====================================================================

def test_art_002_youtube_search_preserves_artists_list():
    service = YouTubeService()
    artists_raw = [
        {"name": "Artist One", "id": "UC_artist_1"},
        {"name": "Artist Two", "id": "UC_artist_2"}
    ]
    mock_yt = MagicMock()
    mock_yt.search.return_value = [
        {
            "resultType": "song",
            "videoId": "vid12345678",
            "title": "Test Track",
            "artists": artists_raw,
            "duration": "3:45",
            "thumbnails": [{"url": "http://img.jpg"}]
        }
    ]
    service._ytmusic = mock_yt

    results = []
    service.search("Test Track", callback=lambda tracks: results.extend(tracks), prefetch=False)
    time.sleep(0.1)

    assert len(results) == 1
    track = results[0]
    assert track["source_id"] == "vid12345678"
    assert "artists" in track, "artists field must be present in search result track dict"
    assert track["artists"] == artists_raw
    assert track["artists"][0]["id"] == "UC_artist_1"


# =====================================================================
# ART-007: artist bio sanitization
# =====================================================================

def test_art_007_clean_artist_bio_removes_html_footnotes_and_lastfm():
    raw_bio = (
        '<p><b>Radiohead</b> are an English rock band formed in Abingdon, Oxfordshire, in 1985.[1][2]<br>'
        'The band consists of <a href="https://example.com/thom">Thom Yorke</a> and others.[citation needed]</p>\n\n'
        'User-contributed text is available under the Creative Commons By-SA License; additional terms may apply.\n'
        '<a href="https://www.last.fm/music/Radiohead">Read more on Last.fm</a>.'
    )
    cleaned = clean_artist_bio(raw_bio)

    assert "<p>" not in cleaned
    assert "<b>" not in cleaned
    assert "</a>" not in cleaned
    assert "<br>" not in cleaned
    assert "[1]" not in cleaned
    assert "[2]" not in cleaned
    assert "[citation needed]" not in cleaned
    assert "Read more on Last.fm" not in cleaned
    assert "Creative Commons" not in cleaned
    assert "Radiohead are an English rock band formed in Abingdon" in cleaned
    assert "Thom Yorke and others." in cleaned


def test_art_007_clean_artist_bio_handles_empty_and_entities():
    assert clean_artist_bio("") == ""
    assert clean_artist_bio(None) == ""
    entity_bio = "AC&amp;DC &quot;Back in Black&#39;&quot; [note 1]"
    assert clean_artist_bio(entity_bio) == "AC&DC \"Back in Black'\""


# =====================================================================
# ART-008: cascade fallback for artist avatar and bio
# =====================================================================

def test_art_008_fallback_resolves_avatar_from_deezer(monkeypatch):
    svc = ArtistService(SimpleNamespace(), settings=None)

    mock_dz = MagicMock()
    mock_dz.get_artist.return_value = {
        'id': '123',
        'name': 'Daft Punk',
        'avatar_url': 'https://dzcdn.net/1000x1000.jpg'
    }
    monkeypatch.setattr("services.deezer_service.DeezerService", lambda settings=None: mock_dz)

    avatar, bio = svc._resolve_metadata_fallback("Daft Punk", avatar_url="", bio="")
    assert avatar == "https://dzcdn.net/1000x1000.jpg"
    assert mock_dz.get_artist.called


def test_art_008_fallback_resolves_bio_from_wikipedia(monkeypatch):
    svc = ArtistService(SimpleNamespace(), settings=None)

    # Deezer returns no bio and empty avatar
    mock_dz = MagicMock()
    mock_dz.get_artist.return_value = {}
    monkeypatch.setattr("services.deezer_service.DeezerService", lambda settings=None: mock_dz)

    import urllib.request
    import json
    import io

    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, 'full_url') else str(req)
        if "ru.wikipedia.org" in url:
            data = {
                "type": "standard",
                "extract": "Daft Punk — французский музыкальный электронный дуэт.[1]",
                "thumbnail": {"source": "https://wiki.org/thumb.jpg"}
            }
            resp = MagicMock()
            resp.status = 200
            resp.read.return_value = json.dumps(data).encode("utf-8")
            resp.__enter__.return_value = resp
            return resp
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    avatar, bio = svc._resolve_metadata_fallback("Daft Punk", avatar_url="", bio="")
    assert avatar == "https://wiki.org/thumb.jpg"
    assert "Daft Punk — французский музыкальный электронный дуэт." in bio
    assert "[1]" not in bio  # cleaned


def test_art_008_itunes_profile_uses_fallback_metadata(monkeypatch):
    svc = ArtistService(SimpleNamespace(), settings=None)
    monkeypatch.setattr(svc, "_collect_itunes_albums", lambda *a, **k: [])
    monkeypatch.setattr(svc, "_collect_itunes_tracks", lambda *a, **k: [])
    monkeypatch.setattr(svc, "_resolve_metadata_fallback", lambda name, **k: ("https://cdn.example.com/avatar.jpg", "Bio text"))

    profile = svc._build_itunes_profile({'results': []}, '123', 'Test Artist')
    assert profile['avatar_url'] == "https://cdn.example.com/avatar.jpg"
    assert profile['bio_original'] == "Bio text"


# =====================================================================
# ART-009: remove_artist_binding in core/api.py
# =====================================================================

def test_art_009_remove_artist_binding():
    settings_store = {
        'personalization': {
            'artist_bindings': {
                'кино': {'local_name': 'Кино', 'canonical_name': 'Кино', 'catalog_ids': {'youtube': 'UC_kino'}},
                'кино\0youtube\0track_123': {'local_name': 'Кино', 'canonical_name': 'Кино', 'context': {'source': 'youtube', 'source_id': 'track_123'}, 'catalog_ids': {'youtube': 'UC_kino'}},
                'pharaoh': {'local_name': 'PHARAOH', 'canonical_name': 'PHARAOH', 'catalog_ids': {'youtube': 'UC_ph'}}
            }
        }
    }

    class DummySettings:
        def get(self, section, key, default=None):
            return settings_store.get(section, {}).get(key, default)
        def set(self, section, key, value):
            settings_store.setdefault(section, {})[key] = value

    core = SimpleNamespace(settings=DummySettings(), db=MagicMock())
    api = AppApi(core)

    # 1. Remove context binding
    res = api.remove_artist_binding('Кино', context={'source': 'youtube', 'source_id': 'track_123'})
    assert res['success'] is True
    assert res['removed'] is True
    assert 'кино\0youtube\0track_123' not in settings_store['personalization']['artist_bindings']
    # Unqualified binding still exists
    assert 'кино' in settings_store['personalization']['artist_bindings']

    # 2. Remove unqualified binding
    res2 = api.remove_artist_binding('Кино')
    assert res2['success'] is True
    assert res2['removed'] is True
    assert 'кино' not in settings_store['personalization']['artist_bindings']
    # Other artist preserved
    assert 'pharaoh' in settings_store['personalization']['artist_bindings']

    # 3. Removing non-existent binding returns removed=False
    res3 = api.remove_artist_binding('NonExistent')
    assert res3['success'] is True
    assert res3['removed'] is False


# =====================================================================
# ART-010: canonical_artist never returns @catalog hash
# =====================================================================

def test_art_010_canonical_artist_never_returns_system_hash():
    class DummySettings:
        revision = 1
        def get(self, section, key, default=None):
            if key == 'artist_bindings':
                return {
                    'кино': {
                        'local_name': 'Кино',
                        'canonical_name': 'Кино',
                        'catalog_ids': {'youtube': 'UC_kino_channel_id'}
                    }
                }
            return {}

    settings = DummySettings()
    aliases = artist_aliases(settings)

    # In artist_aliases, unqualified binding maps to canonical_name, not @catalog hash
    assert aliases['кино'] == 'Кино'
    # canonical_artist must return displayable canonical name
    assert canonical_artist('кино', aliases) == 'кино'
    assert canonical_artist('Кино', aliases) == 'кино'

    # If aliases contains a hash, canonical_artist must never return it
    dirty_aliases = {'ghost': '@catalog:youtube:abcdef123456'}
    assert canonical_artist('ghost', dirty_aliases) == 'ghost'
    assert canonical_artist('@catalog:youtube:abcdef123456', dirty_aliases) == ''


def test_art_010_filter_artist_tracks_matches_tracks_with_bindings():
    class DummySettings:
        revision = 2
        def get(self, section, key, default=None):
            if key == 'artist_bindings':
                return {
                    'кино': {
                        'local_name': 'Кино',
                        'canonical_name': 'Кино',
                        'catalog_ids': {'youtube': 'UC_kino'}
                    }
                }
            return {}

    core = SimpleNamespace(settings=DummySettings(), db=MagicMock())
    api = AppApi(core)

    tracks = [
        {'title': 'Группа крови', 'artist': 'Кино'},
        {'title': 'Звезда по имени Солнце', 'artist': 'КИНО'},
        {'title': 'Кукушка', 'artist': 'Полина Гагарина'}
    ]

    filtered = api.filter_artist_tracks(tracks, 'Кино')
    assert len(filtered) == 2
    assert [t['title'] for t in filtered] == ['Группа крови', 'Звезда по имени Солнце']


# =====================================================================
# ART-011: homonym disambiguation via hint_track & discography isolation
# =====================================================================

def test_art_011_homonym_disambiguation_with_hint_track():
    yt = MagicMock()
    # Two candidates with the same name 'Ghost'
    cands = [
        {'artist': 'Ghost', 'browseId': 'UC_metal_ghost'},
        {'artist': 'Ghost', 'browseId': 'UC_indie_ghost'}
    ]
    yt.search.return_value = cands

    # UC_metal_ghost released "Square Hammer"
    def fake_get_artist(sid):
        if sid == 'UC_metal_ghost':
            return {'name': 'Ghost', 'songs': {'results': [{'title': 'Square Hammer'}, {'title': 'Mary On A Cross'}]}}
        return {'name': 'Ghost', 'songs': {'results': [{'title': 'Some Indie Song'}]}}

    yt.get_artist.side_effect = fake_get_artist

    catalog = CatalogService(SimpleNamespace(_ytmusic=yt))

    # Without hint_track, homonyms are ambiguous
    res_ambiguous = catalog.resolve_artist('Ghost')
    assert res_ambiguous['status'] == 'ambiguous'
    assert len(res_ambiguous['candidates']) == 2

    # With hint_track 'Square Hammer', it selects UC_metal_ghost
    res_resolved = catalog.resolve_artist('Ghost', {'hint_track': 'Square Hammer'})
    assert res_resolved['status'] == 'found'
    assert res_resolved['source_id'] == 'UC_metal_ghost'


def test_art_011_homonym_discography_isolation_in_credited_to():
    # Album from a different channel with same artist name
    hit_other_channel = {
        'title': 'Other Album',
        'artists': [{'name': 'Ghost', 'id': 'UC_other_ghost'}]
    }
    # Album from the target channel
    hit_target_channel = {
        'title': 'Target Album',
        'artists': [{'name': 'Ghost', 'id': 'UC_target_ghost'}]
    }

    assert not credited_to(hit_other_channel, 'Ghost', channel_id='UC_target_ghost')
    assert credited_to(hit_target_channel, 'Ghost', channel_id='UC_target_ghost')


# =====================================================================
# ART-015: search with result_type='artists' on YouTube and Deezer
# =====================================================================

def test_art_015_youtube_search_artists():
    yt_svc = YouTubeService()
    mock_yt = MagicMock()
    mock_yt.search.return_value = [
        {
            'resultType': 'artist',
            'browseId': 'UC_artist_abc',
            'artist': 'Test Band',
            'subscribers': '1.5M',
            'thumbnails': [{'url': 'https://yt.com/photo.jpg'}]
        }
    ]
    yt_svc._ytmusic = mock_yt

    results = []
    yt_svc.search("Test Band", result_type="artists", callback=lambda items: results.extend(items), prefetch=False)
    time.sleep(0.1)

    assert len(results) == 1
    assert results[0]['type'] == 'artist'
    assert results[0]['source'] == 'youtube'
    assert results[0]['source_id'] == 'UC_artist_abc'
    assert results[0]['name'] == 'Test Band'
    assert results[0]['avatar_url'] == 'https://yt.com/photo.jpg'


def test_art_015_deezer_search_artists(monkeypatch):
    dz_svc = DeezerService()
    mock_get = MagicMock()
    mock_get.return_value = {
        'data': [
            {
                'id': 456,
                'name': 'Daft Punk',
                'picture_xl': 'https://dz.com/daft_1000.jpg',
                'nb_fan': 5000000
            }
        ]
    }
    monkeypatch.setattr(dz_svc, "_get", mock_get)

    results = []
    dz_svc.search("Daft Punk", result_type="artists", callback=lambda items: results.extend(items))
    time.sleep(0.1)

    assert len(results) == 1
    assert results[0]['type'] == 'artist'
    assert results[0]['source'] == 'deezer'
    assert results[0]['source_id'] == '456'
    assert results[0]['name'] == 'Daft Punk'
    assert results[0]['avatar_url'] == 'https://dz.com/daft_1000.jpg'


def test_art_015_core_api_search_artists_targets_youtube_and_deezer():
    core = SimpleNamespace(
        settings=SimpleNamespace(get=lambda *a, **k: True),
        db=MagicMock(),
        youtube=MagicMock(),
        deezer=MagicMock(),
        soundcloud=MagicMock(),
        spotify=MagicMock(),
        yandex=MagicMock()
    )
    core.db.search_artists.return_value = []
    api = AppApi(core)

    api.search("Queen", source="all", result_type="artists")

    for _ in range(20):
        if core.youtube.search.called and core.deezer.search.called:
            break
        time.sleep(0.05)

    # YouTube and Deezer must be called for artists search
    assert core.youtube.search.called
    assert core.deezer.search.called
    # SoundCloud / Spotify should not be queried for artist search in all mode
    assert not core.soundcloud.search.called
    assert not core.spotify.search.called


# =====================================================================
# ART-017: KeyError: musicCarouselShelfRenderer resilience
# =====================================================================

def test_art_017_collect_albums_resilient_to_key_error(monkeypatch):
    svc = ArtistService(SimpleNamespace(), settings=None)
    mock_yt = MagicMock()

    # yt.get_artist_albums raises KeyError: 'musicCarouselShelfRenderer'
    mock_yt.get_artist_albums.side_effect = KeyError("Unable to find 'musicCarouselShelfRenderer'")

    # Raw response has section with musicCarouselShelfRenderer
    mock_yt._send_request.return_value = {
        'contents': {
            'singleColumnBrowseResultsRenderer': {
                'tabs': [{
                    'tabRenderer': {
                        'content': {
                            'sectionListRenderer': {
                                'contents': [
                                    {
                                        'musicShelfRenderer': {'contents': []}
                                    },
                                    {
                                        'musicCarouselShelfRenderer': {
                                            'header': {
                                                'musicCarouselShelfBasicHeaderRenderer': {
                                                    'title': {'runs': [{'text': 'Albums'}]}
                                                }
                                            },
                                            'contents': [
                                                {
                                                    'musicTwoRowItemRenderer': {
                                                        'title': {'runs': [{'text': 'Continuation Album'}]},
                                                        'navigationEndpoint': {
                                                            'browseEndpoint': {'browseId': 'MPREb_cont123'}
                                                        },
                                                        'subtitle': {'runs': [{'text': 'Album'}, {'text': '2023'}]},
                                                        'thumbnailRenderer': {
                                                            'musicThumbnailRenderer': {
                                                                'thumbnail': {'thumbnails': [{'url': 'http://cover.jpg'}]}
                                                            }
                                                        }
                                                    }
                                                }
                                            ]
                                        }
                                    }
                                ]
                            }
                        }
                    }
                }]
            }
        }
    }

    # Should safely recover without raising KeyError
    albums = svc._safe_get_artist_albums(mock_yt, 'UC_channel', 'params_token', deadline=time.monotonic() + 5)
    assert len(albums) == 1
    assert albums[0]['browseId'] == 'MPREb_cont123'
    assert albums[0]['title'] == 'Continuation Album'


# =====================================================================
# ART-018: Cyrillic/Latin transliteration for artist candidates search
# =====================================================================

def test_art_018_artist_candidates_searches_both_scripts(monkeypatch):
    from services.itunes_gateway import ITunesGateway
    monkeypatch.setattr(ITunesGateway, "get", lambda *a, **k: {"results": []})

    yt = MagicMock()
    searches = []

    def fake_search(query, filter=None, limit=None):
        searches.append(query)
        if query.lower() == "skriptonit":
            return [{'browseId': 'UC_skrip', 'artist': 'Skriptonit'}]
        return []

    yt.search.side_effect = fake_search
    catalog = CatalogService(SimpleNamespace(_ytmusic=yt))

    # User searches in Cyrillic "Скриптонит"
    candidates, failed = catalog._artist_candidates("Скриптонит", deadline=time.monotonic() + 5, is_current=lambda: True)

    assert "Скриптонит" in searches
    assert "skriptonit" in [s.lower() for s in searches]
    assert len(candidates) == 1
    assert candidates[0]['source_id'] == 'UC_skrip'
    assert candidates[0]['name'] == 'Skriptonit'
