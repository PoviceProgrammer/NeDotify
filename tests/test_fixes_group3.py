"""Tests for Group 3 fixes: BUG-WIN-001, BUG-WIN-002, BUG-WIN-035, BUG-WIN-036, BUG-WIN-052, BUG-WIN-053."""
import json
import os
import shutil
import struct
import threading
import types
from unittest.mock import MagicMock

import pytest

from core.database import DatabaseManager
from core.download_transfer import DownloadContext, DownloadInterrupted
from core.downloader import DownloadManager, _downloaded_file_defect, _is_403_error
from core.resolver import StreamResolver
from services.deezer_service import DeezerError, DeezerService
from services.soundcloud_service import SoundCloudService
from utils.audio_validation import audio_duration, ebml_audio_duration


# --------------------------------------------------------------------------- #
# BUG-WIN-001: Pure-Python EBML parsing without ffprobe
# --------------------------------------------------------------------------- #

def _build_minimal_ebml_audio(duration_sec=120.0, timecode_scale=1000000):
    """Construct a minimal valid EBML WebM byte payload with Duration (0x4489)."""
    # EBML header: ID 0x1A45DFA3, size 0 (empty header or minimal)
    ebml_header = b'\x1a\x45\xdf\xa3\x84\x42\x86\x81\x01'  # EBML header with DocType
    # Info: ID 0x1549A966
    # TimecodeScale: 0x2AD7B1, size 3, value
    tc_bytes = timecode_scale.to_bytes(3, 'big')
    tc_elem = b'\x2a\xd7\xb1' + bytes([0x80 | len(tc_bytes)]) + tc_bytes
    # Duration: 0x4489, size 4 (float)
    # duration in timecode_scale units: duration_sec * 1e9 / timecode_scale
    raw_dur = float(duration_sec * 1000000000.0 / timecode_scale)
    dur_bytes = struct.pack('>f', raw_dur)
    dur_elem = b'\x44\x89' + bytes([0x80 | len(dur_bytes)]) + dur_bytes

    info_payload = tc_elem + dur_elem
    info_elem = b'\x15\x49\xa9\x66' + bytes([0x80 | len(info_payload)]) + info_payload

    # Tracks: ID 0x1654AE6B -> TrackEntry 0xAE -> TrackType 0x83 (2 = audio)
    track_type_elem = b'\x83\x81\x02'  # TrackType audio
    entry_elem = b'\xae' + bytes([0x80 | len(track_type_elem)]) + track_type_elem
    tracks_elem = b'\x16\x54\xae\x6b' + bytes([0x80 | len(entry_elem)]) + entry_elem

    segment_payload = info_elem + tracks_elem
    segment_elem = b'\x18\x53\x80\x67' + bytes([0x80 | len(segment_payload)]) + segment_payload
    return ebml_header + segment_elem


def test_bug_win_001_ebml_validation_without_ffprobe(tmp_path, monkeypatch):
    """BUG-WIN-001: Missing ffprobe must not fail validation for valid WebM/Opus."""
    monkeypatch.setattr('utils.audio_validation.ffprobe_path', lambda: None)
    monkeypatch.setattr('mutagen.File', lambda path: None)

    webm_data = _build_minimal_ebml_audio(duration_sec=180.5)
    file_path = tmp_path / 'test_audio.webm'
    file_path.write_bytes(webm_data + b'\x00' * 40000)

    dur = audio_duration(str(file_path))
    assert abs(dur - 180.5) < 0.1

    defect = _downloaded_file_defect(str(file_path), expected_duration=180.0)
    assert defect == '', f'Unexpected defect: {defect}'


def test_bug_win_001_ebml_corrupt_rejected_without_ffprobe(tmp_path, monkeypatch):
    """BUG-WIN-001: A broken EBML container is still rejected without ffprobe."""
    monkeypatch.setattr('utils.audio_validation.ffprobe_path', lambda: None)
    monkeypatch.setattr('mutagen.File', lambda path: None)

    broken_file = tmp_path / 'broken.webm'
    broken_file.write_bytes(b'\x1a\x45\xdf\xa3\x00\x00\x00')

    with pytest.raises(ValueError):
        audio_duration(str(broken_file))


# --------------------------------------------------------------------------- #
# BUG-WIN-002: Spotify ytsearch downloads must verify recording and timing
# --------------------------------------------------------------------------- #

def test_bug_win_002_spotify_ytsearch_selects_recording_and_checks_duration(tmp_db, tmp_path):
    """BUG-WIN-002: ytsearch1 source_id must NOT bypass select_recording."""
    results = [
        {'source_id': 'clubmix123', 'title': 'Bohemian Rhapsody (Club Remix)', 'artist': 'Queen', 'duration': 600},
        {'source_id': 'correctvid', 'title': 'Bohemian Rhapsody', 'artist': 'Queen', 'duration': 355},
    ]

    class _MockYt:
        def __init__(self):
            self.download_calls = []

        def search_sync(self, query, limit=5):
            return results

        def download_audio_sync(self, sid, directory, download_context=None):
            self.download_calls.append(sid)
            return os.path.join(directory, f'{sid}.mp3')

    mock_yt = _MockYt()
    dm = DownloadManager.__new__(DownloadManager)
    dm._core = types.SimpleNamespace(db=tmp_db, settings=None, youtube=mock_yt)
    dm._worker_context = threading.local()

    tid = tmp_db.add_track(title='Bohemian Rhapsody', artist='Queen', source='spotify',
                           source_id='ytsearch1: Queen - Bohemian Rhapsody', duration=355)

    out_dir = str(tmp_path / 'downloads')
    os.makedirs(out_dir, exist_ok=True)

    result_path = dm._download_spotify_track('ytsearch1: Queen - Bohemian Rhapsody', tid, out_dir)

    # Must select the verified original cut, not the first remix and not raw "ytsearch1: ..."
    assert mock_yt.download_calls == ['correctvid']
    assert 'ytsearch1' not in mock_yt.download_calls[0]


def test_bug_win_002_spotify_ytsearch_rejects_unmatched_recording(tmp_db, tmp_path):
    """BUG-WIN-002: If no YouTube result matches the Spotify track, raise instead of downloading wrong file."""
    results = [
        {'source_id': 'wrongvid1', 'title': 'Totally Different Song', 'artist': 'Other', 'duration': 120},
    ]

    class _MockYt:
        def search_sync(self, query, limit=5):
            return results

        def download_audio_sync(self, sid, directory, download_context=None):
            return os.path.join(directory, f'{sid}.mp3')

    dm = DownloadManager.__new__(DownloadManager)
    dm._core = types.SimpleNamespace(db=tmp_db, settings=None, youtube=_MockYt())
    dm._worker_context = threading.local()

    tid = tmp_db.add_track(title='Bohemian Rhapsody', artist='Queen', source='spotify',
                           source_id='ytsearch1: Queen - Bohemian Rhapsody', duration=355)

    with pytest.raises(Exception, match='Не найдено подходящей записи'):
        dm._download_spotify_track('ytsearch1: Queen - Bohemian Rhapsody', tid, str(tmp_path))


# --------------------------------------------------------------------------- #
# BUG-WIN-035: Deezer retryable flag preservation on YouTube timeout
# --------------------------------------------------------------------------- #

def test_bug_win_035_deezer_preserves_retryable_on_youtube_timeout(tmp_path, monkeypatch):
    """BUG-WIN-035: When YouTube search times out, Deezer download error must retain retryable=True."""
    deezer = DeezerService()
    monkeypatch.setattr(deezer, 'get_track', lambda tid: {'id': '1', 'title': 'Test Song', 'artist': 'Test Artist', 'duration': 180})

    calls = []

    def providers(source):
        calls.append(source)
        if source == 'youtube':
            # simulate search failure / timeout via error_callback
            return types.SimpleNamespace(
                search=lambda q, callback=None, error_callback=None, **kw: error_callback('Search timed out')
            )
        else:
            cand = {'source': 'soundcloud', 'source_id': 'sc123', 'artist': 'Test Artist',
                    'title': 'Test Song', 'duration': 180}
            return types.SimpleNamespace(
                search=lambda q, callback=None, error_callback=None, **kw: callback([cand]),
                download_audio_sync=lambda sid, d, **kw: (_ for _ in ()).throw(RuntimeError('SoundCloud stream dead'))
            )

    deezer._providers = providers

    with pytest.raises(Exception) as exc_info:
        deezer.download_audio_sync('1', str(tmp_path))

    err = exc_info.value
    # retryable flag must be True so downloader retries!
    assert getattr(err, 'retryable', False) is True


# --------------------------------------------------------------------------- #
# BUG-WIN-036: SoundCloud fallback requests 5 results, not 1
# --------------------------------------------------------------------------- #

def test_bug_win_036_soundcloud_fallback_queries_multiple_results():
    """BUG-WIN-036: SoundCloud fallback to YouTube must use max_results=5 to find matching audio."""
    sc = SoundCloudService()
    search_calls = []

    mock_yt = types.SimpleNamespace(
        search=lambda query, max_results, callback, error_callback: search_calls.append(max_results)
    )
    sc._youtube = mock_yt

    with open('services/soundcloud_service.py', 'r', encoding='utf-8') as f:
        content = f.read()

    assert 'yt.search(query, max_results=5,' in content
    assert 'yt.search(query, max_results=1,' not in content


# --------------------------------------------------------------------------- #
# BUG-WIN-052: Cache invalidation upon 403 Forbidden
# --------------------------------------------------------------------------- #

def test_bug_win_052_downloader_invalidates_cache_on_403(tmp_db):
    """BUG-WIN-052: HTTP 403 Forbidden must purge the dead stream URL from SQLite cache."""
    # Seed stream cache
    tmp_db.cache_stream('youtube', 'video403', 'https://googlevideo.com/dead_token', 'Title')
    assert tmp_db.get_cached_stream('youtube', 'video403') is not None

    mock_resolver = StreamResolver(db=tmp_db)
    mock_resolver.refresh('youtube', 'video403', 'https://googlevideo.com/dead_token')
    assert mock_resolver.get_cached_url('youtube', 'video403') is not None

    dm = DownloadManager.__new__(DownloadManager)
    dm._core = types.SimpleNamespace(db=tmp_db, resolver=mock_resolver, youtube=None)

    err = Exception('HTTP Error 403: Forbidden')
    assert _is_403_error(err) is True

    dm._invalidate_stream_cache('youtube', 'video403')

    # SQLite stream cache must now have stream_url cleared
    cached = tmp_db.get_cached_stream('youtube', 'video403')
    assert cached is None or cached.get('stream_url') is None
    assert mock_resolver.get_cached_url('youtube', 'video403') is None


def test_bug_win_052_resolver_purges_expired_timestamp_row(tmp_db):
    """BUG-WIN-052: get_cached_url purges row when expires_at timestamp has passed."""
    # Insert expired cache row
    tmp_db.cache_stream('youtube', 'exp_vid', 'https://cdn.example/exp', 'Title')
    with tmp_db._write_lock, tmp_db.conn:
        tmp_db.conn.execute(
            "UPDATE stream_cache SET expires_at = '2020-01-01T00:00:00' WHERE source = 'youtube' AND source_id = 'exp_vid'"
        )

    resolver = StreamResolver(db=tmp_db)
    url = resolver.get_cached_url('youtube', 'exp_vid')
    assert url is None


# --------------------------------------------------------------------------- #
# BUG-WIN-053: Cleanup of .part.json on failure or orphan removal
# --------------------------------------------------------------------------- #

def test_bug_win_053_remove_managed_orphan_cleans_part_and_part_json(tmp_path, monkeypatch):
    """BUG-WIN-053: _remove_managed_orphan removes .part and .part.json alongside target."""
    monkeypatch.setenv('USERPROFILE', str(tmp_path))
    monkeypatch.setenv('HOME', str(tmp_path))

    dl_dir = tmp_path / '.nedotify' / 'downloads'
    dl_dir.mkdir(parents=True, exist_ok=True)

    base = dl_dir / 'track123.mp3'
    part = dl_dir / 'track123.mp3.part'
    meta = dl_dir / 'track123.mp3.part.json'

    base.write_bytes(b'audio')
    part.write_bytes(b'partial')
    meta.write_text('{"etag": "123"}', encoding='utf-8')

    DownloadManager._remove_managed_orphan(str(base))

    assert not base.exists()
    assert not part.exists()
    assert not meta.exists()


def test_bug_win_053_startup_cleanup_removes_unattached_part_json(tmp_path):
    """BUG-WIN-053: Standalone .part.json without a .part file is purged on startup."""
    dl_dir = tmp_path / 'downloads'
    dl_dir.mkdir(parents=True, exist_ok=True)

    orphan_json = dl_dir / 'orphan_download.mp3.part.json'
    orphan_json.write_text('{"etag": "xyz"}', encoding='utf-8')

    # And a valid pair with both .part and .part.json
    valid_part = dl_dir / 'valid.mp3.part'
    valid_json = dl_dir / 'valid.mp3.part.json'
    valid_part.write_bytes(b'in progress')
    valid_json.write_text('{"etag": "valid"}', encoding='utf-8')

    DownloadManager._cleanup_orphaned_part_files(str(dl_dir))

    assert not orphan_json.exists(), 'Orphaned .part.json should have been deleted'
    assert valid_part.exists(), 'Active .part should be kept'
    assert valid_json.exists(), 'Active .part.json should be kept'
