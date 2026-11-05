"""Playlist formats must produce usable playback/download identities."""
import pytest

from services.playlist_import_service import PlaylistImportService, PlaylistImportError


def test_m3u_relative_path_is_relative_to_playlist(tmp_path, monkeypatch):
    folder = tmp_path / 'music'
    folder.mkdir()
    audio = folder / 'song.mp3'
    audio.write_bytes(b'audio')
    playlist = folder / 'mix.m3u8'
    playlist.write_text('#EXTM3U\n#EXTINF:180,Artist - Song\nsong.mp3\n', encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    result = PlaylistImportService().resolve(str(playlist))
    assert result['tracks'][0]['file_path'] == str(audio)
    assert result['tracks'][0]['title'] == 'Song'


def test_text_list_uses_search_expression_instead_of_video_id(tmp_path):
    playlist = tmp_path / 'songs.txt'
    playlist.write_text('Artist - Song\nAnother song\n', encoding='utf-8')
    tracks = PlaylistImportService().resolve(str(playlist))['tracks']
    assert [t['source_id'] for t in tracks] == ['ytsearch1:Artist - Song', 'ytsearch1:Another song']


def test_provider_names_in_host_suffix_are_not_provider_urls():
    result = PlaylistImportService()._parse_content('https://youtube.com.evil.test/watch?v=abcdefghijk', 'list', 'list.txt')
    assert result['tracks'][0]['source'] != 'youtube'


@pytest.mark.parametrize('source, url', [('youtube', 'https://www.youtube.com/playlist?list=PLtest'),
                                       ('soundcloud', 'https://soundcloud.com/artist/sets/list')])
def test_external_import_skips_unavailable_entries_and_preserves_metadata(monkeypatch, source, url):
    monkeypatch.setattr('utils.url_safety.safe_public_url', lambda value: True)
    class Ydl:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, target, download):
            assert not download
            return {'title': 'Mix', 'entries': [None, {}, {'id': 'abcdefghijk', 'title': 'Song',
                    'uploader': 'Artist', 'duration': 180, 'thumbnail': 'https://example.com/cover.jpg'}]}
    result = PlaylistImportService(ydl_factory=lambda options: Ydl()).resolve(url)
    assert len(result['tracks']) == 1
    assert result['tracks'][0]['title'] == 'Song'
    assert result['tracks'][0]['source'] == source


def test_invalid_json_fails_before_import(tmp_path):
    path = tmp_path / 'broken.json'
    path.write_text('{bad json', encoding='utf-8')
    with pytest.raises(PlaylistImportError):
        PlaylistImportService().resolve(str(path))


def test_json_metadata_keeps_covers_and_produces_playable_search_identity(tmp_path):
    import json
    path=tmp_path/'tracks.json'
    path.write_text(json.dumps({'name':'Imported','tracks':[{'title':'Song','artist':'Artist','cover_url':'https://example.org/cover.jpg'}]}),encoding='utf-8')
    result=PlaylistImportService().resolve(str(path))
    assert result['tracks'][0]['source']=='youtube'
    assert result['tracks'][0]['source_id']=='ytsearch1:Artist - Song'
    assert result['tracks'][0]['cover_url']=='https://example.org/cover.jpg'


def test_local_m3u_survives_atomic_library_import(tmp_path,tmp_db):
    song=tmp_path/'song.mp3';song.write_bytes(b'audio')
    path=tmp_path/'tracks.m3u8';path.write_text('#EXTM3U\n#EXTINF:180,Artist - Song\nsong.mp3\n',encoding='utf-8')
    result=PlaylistImportService().resolve(str(path))
    pid,count=tmp_db.import_playlist_atomic(result['name'],'',result['tracks'])
    track=tmp_db.get_playlist_tracks(pid)[0]
    assert count==1 and track['file_path']==str(song)
    assert track['is_downloaded']==1
    _,count=tmp_db.import_playlist_atomic(result['name'],'',result['tracks'])
    assert count==0


def test_oversized_playlist_fails_instead_of_silently_truncating(tmp_path):
    import json
    path=tmp_path/'too-many.json'
    path.write_text(json.dumps({'tracks':[{'title':str(i),'artist':'Artist'} for i in range(PlaylistImportService.MAX_TRACKS+1)]}),encoding='utf-8')
    with pytest.raises(PlaylistImportError,match=str(PlaylistImportService.MAX_TRACKS)):
        PlaylistImportService().resolve(str(path))


def test_existing_import_api_accepts_supported_local_playlist_files(api,tmp_db,tmp_path):
    song=tmp_path/'song.mp3';song.write_bytes(b'audio')
    path=tmp_path/'local.m3u8';path.write_text('#EXTM3U\n#EXTINF:180,Artist - Song\nsong.mp3\n',encoding='utf-8')
    api._core.db=tmp_db
    api._core.playlist_importer=PlaylistImportService()
    result=api.import_external_playlist(str(path))
    assert result['success'],result
    assert tmp_db.get_playlist_tracks(result['playlist_id'])[0]['file_path']==str(song)
