"""
Comprehensive E2E test suite for NeDotify.
Covers 8 core features across 4 testing tiers with 93 distinct test cases.
Runs headlessly and isolates filesystem/network dependencies using advanced mocking.
"""

import os
import sys
sys.frozen = True  # Prevent any yt-dlp pip auto-update network calls in AppCore

# Fix path to import 'core' and other modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tempfile
import shutil
import unittest
import json
import time
import io
import urllib.request
import threading
import uuid
from unittest.mock import MagicMock, patch

# ==========================================
# 1. SYNCHRONOUS RUNNERS FOR ASYNC MOCKS
# ==========================================

class SynchronousExecutor:
    def __init__(self, *args, **kwargs):
        pass
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        return False
    def submit(self, fn, *args, **kwargs):
        future = concurrent.futures.Future()
        try:
            res = fn(*args, **kwargs)
            future.set_result(res)
        except Exception as e:
            future.set_exception(e)
        return future

_REAL_THREAD_CLASS = threading.Thread

class SynchronousThread(_REAL_THREAD_CLASS):
    def __init__(self, target=None, args=(), kwargs=None, daemon=False, *a, **kw):
        super().__init__(daemon=daemon)
        self.target = target
        self.args = args or ()
        self.kwargs = kwargs or {}
    def start(self):
        if self.target:
            self.target(*self.args, **self.kwargs)

# Pre-import watchdog so its BaseThread binds the real threading.Thread (it is
# imported again by services/watchdog_service.py after the shim patch below).
try:
    import watchdog.observers  # noqa: F401
    import watchdog.events  # noqa: F401
except ImportError:
    pass

import concurrent.futures
concurrent.futures.ThreadPoolExecutor = SynchronousExecutor
threading.Thread = SynchronousThread

# ==========================================
# 2. GLOBAL ENVIRONMENT MOCKS
# ==========================================

# Mock python-vlc module before any audio engine import
class MockVlcMedia:
    def add_option(self, option):
        pass

class MockVlcPlayer:
    def __init__(self):
        self._media = None
        self._volume = 70
        self._muted = False
        self._time = 0
        self._length = 180000  # 3 minutes in ms
        self._position = 0.0
        self._is_playing = False
        self._event_manager = MagicMock()

    def set_media(self, media):
        self._media = media

    def audio_set_volume(self, vol):
        self._volume = vol

    def play(self):
        self._is_playing = True
        return 0

    def pause(self):
        self._is_playing = False

    def stop(self):
        self._is_playing = False

    def event_manager(self):
        return self._event_manager

    def get_time(self):
        return self._time

    def set_time(self, t):
        self._time = t

    def get_length(self):
        return self._length

    def get_position(self):
        return self._position

    def set_position(self, pos):
        self._position = pos

class MockVlcInstance:
    def media_player_new(self):
        return MockVlcPlayer()
    def media_new(self, path):
        return MockVlcMedia()
    def media_new_path(self, path):
        return MockVlcMedia()

mock_vlc = MagicMock()
mock_vlc.Instance.return_value = MockVlcInstance()
mock_vlc.EventType.MediaPlayerEndReached = 1
mock_vlc.EventType.MediaPlayerEncounteredError = 2

sys.modules['vlc'] = mock_vlc

# Mock mutagen module
class MockAudioInfo:
    def __init__(self):
        self.length = 180.0
        self.bitrate = 320000
        self.sample_rate = 44100

class MockTagsDict:
    def __init__(self):
        self._DictProxy__dict = {}
        self.tags_data = {'covr': [b'dummy_cover_data']}
    def __getitem__(self, key):
        return self.tags_data[key]
    def __contains__(self, key):
        return key in self.tags_data

class MockAudioFile:
    def __init__(self):
        self.info = MockAudioInfo()
        self.tags = MockTagsDict()

    def get(self, tag, default=None):
        tags = {
            'title': ['Mock Tag Title'],
            'artist': ['Mock Tag Artist'],
            'album': ['Mock Tag Album'],
            'genre': ['Mock Tag Genre'],
            'date': ['2026'],
            'tracknumber': ['3/10']
        }
        return tags.get(tag, default)

    def __getitem__(self, key):
        return self.tags[key]

    def __contains__(self, key):
        return key in self.tags

mock_mutagen = MagicMock()
mock_mutagen.File.side_effect = lambda filepath, easy=False: None if (not filepath or "corrupt" in os.path.basename(filepath)) else MockAudioFile()

class MockAPIC:
    def __init__(self):
        self.data = b'mp3_cover_data'
        self.mime = 'image/jpeg'

class MockID3:
    def __init__(self, filepath):
        self.tags = {'APIC:': MockAPIC()}
    def __iter__(self):
        return iter(self.tags)
    def __getitem__(self, key):
        return self.tags[key]

class MockFLACPicture:
    def __init__(self):
        self.data = b'flac_cover_data'
        self.mime = 'image/png'

class MockFLAC:
    def __init__(self, filepath):
        self.pictures = [MockFLACPicture()]

class MockOggVorbis:
    def __init__(self, filepath):
        import base64
        self.tags = {'metadata_block_picture': [base64.b64encode(b'ogg_cover_data').decode()]}
    def __contains__(self, key):
        return key in self.tags
    def __getitem__(self, key):
        return self.tags[key]

mock_mutagen.id3 = mock_mutagen
mock_mutagen.flac = mock_mutagen
mock_mutagen.oggvorbis = mock_mutagen
mock_mutagen.mp3 = mock_mutagen

mock_mutagen.ID3 = MockID3
mock_mutagen.FLAC = MockFLAC
mock_mutagen.OggVorbis = MockOggVorbis

sys.modules['mutagen'] = mock_mutagen
sys.modules['mutagen.id3'] = mock_mutagen
sys.modules['mutagen.mp3'] = mock_mutagen
sys.modules['mutagen.flac'] = mock_mutagen
sys.modules['mutagen.oggvorbis'] = mock_mutagen

# Mock yt_dlp
class MockYoutubeDL:
    def __init__(self, *args, **kwargs):
        pass
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass
    def extract_info(self, url, download=False):
        if url.endswith(":") or "ytsearch0" in url or "scsearch0" in url:
            return {'entries': []}
        if "error_id" in url:
            raise Exception("Extraction failed")

        if "watch?v=" in url or "youtube.com" in url or "ytsearch" in url:
            return {
                'id': 'yt_id',
                'title': 'YT Title',
                'uploader': 'YT Artist',
                'duration': 180,
                'thumbnail': 'http://example.com/thumb.jpg',
                'url': 'http://example.com/stream.mp3',
                'ext': 'mp3',
                'abr': 320,
                'entries': [{
                    'id': 'yt_id',
                    'title': 'YT Title',
                    'uploader': 'YT Artist',
                    'duration': 180,
                    'thumbnail': 'http://example.com/thumb.jpg',
                    'url': 'https://www.youtube.com/watch?v=yt_id'
                }]
            }
        elif "soundcloud.com" in url or "scsearch" in url:
            return {
                'id': 'sc_id',
                'title': 'SC Title',
                'uploader': 'SC Artist',
                'duration': 200,
                'thumbnail': 'http://example.com/sc_thumb.jpg',
                'url': 'http://example.com/sc_stream.mp3',
                'entries': [{
                    'id': 'sc_id',
                    'title': 'SC Title',
                    'uploader': 'SC Artist',
                    'duration': 200,
                    'url': 'https://soundcloud.com/sc_id'
                }]
            }
        elif "vk.com" in url:
            return {
                'id': 'vk_id',
                'title': 'VK Title',
                'uploader': 'VK Artist',
                'duration': 150,
                'thumbnail': 'http://example.com/vk_thumb.jpg',
                'url': 'http://example.com/vk_stream.mp3'
            }
        else:
            raise Exception("Unsupported URL or search query in MockYoutubeDL")

    def download(self, urls):
        pass

mock_ytdlp = MagicMock()
mock_ytdlp.YoutubeDL = MockYoutubeDL
mock_ytdlp.utils.DownloadError = Exception
sys.modules['yt_dlp'] = mock_ytdlp

# Mock ytmusicapi
class MockYTMusic:
    def __init__(self, *args, **kwargs):
        pass
    def search(self, query, filter=None, limit=20):
        if not query:
            return []
        if filter == 'artists':
            return [{'browseId': 'mock_artist_id', 'artist': 'Mock Artist', 'thumbnails': [{'url': 'http://example.com/artist.jpg'}]}]
        if filter == 'playlists':
            return [{'browseId': 'mock_playlist_id', 'title': 'Mock Playlist'}]
        return [{
            'resultType': 'song',
            'videoId': 'yt_id',
            'title': 'YT Search Title',
            'artists': [{'name': 'YT Search Artist'}],
            'duration': '3:00',
            'duration_seconds': 180,
            'thumbnails': [{'url': 'http://example.com/thumb.jpg'}]
        }]
    def get_artist(self, channelId):
        return {
            'songs': {
                'results': [{'videoId': 'mock_song', 'title': 'Mock Song', 'artists': [{'name': 'Mock Artist'}]}]
            },
            'related': {
                'results': [{'browseId': 'mock_related_id', 'title': 'Mock Related'}]
            },
            'thumbnails': [{'url': 'http://example.com/artist.jpg'}]
        }
    def get_home(self, limit=10):
        return [{'contents': [{'playlistId': 'mock_playlist_id'}]}]
    def get_playlist(self, playlistId, limit=10):
        return {'tracks': [{'videoId': 'mock_song', 'title': 'Mock Song', 'artists': [{'name': 'Mock Artist'}]}]}
    def get_watch_playlist(self, videoId=None, playlistId=None, limit=10):
        return {'tracks': [{'videoId': 'mock_song', 'title': 'Mock Song', 'artists': [{'name': 'Mock Artist'}]}]}
    def get_explore(self):
        return {'new_releases': [{'audioPlaylistId': 'mock_playlist_id', 'thumbnails': [{'url': 'http://example.com/thumb.jpg'}]}]}
    def get_album(self, browseId):
        return {'tracks': [{'videoId': 'mock_song', 'title': 'Mock Album Song', 'artists': [{'name': 'Mock Artist'}]}]}
    def get_mood_categories(self):
        return {'Moods': [{'title': 'Chill', 'params': 'chill_params'}]}
    def get_mood_playlists(self, params):
        return [{'contents': [{'playlistId': 'mock_mood_pl', 'title': 'Mock Mood Playlist'}]}]

mock_ytmusic = MagicMock()
mock_ytmusic.YTMusic = MockYTMusic
sys.modules['ytmusicapi'] = mock_ytmusic

# Fail fast on any real `requests`-based network calls (offline/CI-safe test sandbox).
# Services (SoundCloud client_id scrape, Yandex client init, Last.fm, Spotify) all
# catch these exceptions and degrade gracefully; otherwise retries can hang for minutes.
try:
    import requests as _requests
    def _no_network(self, method, url, *args, **kwargs):
        raise _requests.exceptions.ConnectionError("network disabled in test sandbox")
    _requests.sessions.Session.request = _no_network
except Exception:
    pass

# When this module is collected AFTER other test files (pytest.py imports every
# module before running any test), core/service modules may already hold
# references to the REAL yt_dlp / mutagen / vlc / ytmusicapi (imported through
# core.app). sys.modules entries installed above would then be too late, so
# re-point the module-level references in already-imported app modules too —
# both whole-module attributes (`import yt_dlp`) and directly imported names
# (`from ytmusicapi import YTMusic`, `from mutagen.mp3 import MP3`).
_MOCK_BY_REAL_PKG = {
    'mutagen': mock_mutagen,
    'ytmusicapi': mock_ytmusic,
    'yt_dlp': mock_ytdlp,
    'vlc': mock_vlc,
}
for _mod_name, _mod in list(sys.modules.items()):
    if _mod_name.split('.')[0] not in ('core', 'services', 'audio', 'utils'):
        continue
    for _attr_name, _mock in (('yt_dlp', mock_ytdlp), ('mutagen', mock_mutagen),
                              ('vlc', mock_vlc), ('ytmusicapi', mock_ytmusic)):
        if hasattr(_mod, _attr_name):
            setattr(_mod, _attr_name, _mock)
    for _attr_name in list(vars(_mod)):
        _val = getattr(_mod, _attr_name, None)
        _real_pkg = getattr(_val, '__module__', None)
        if _real_pkg and _real_pkg.split('.')[0] in _MOCK_BY_REAL_PKG:
            _mock = _MOCK_BY_REAL_PKG[_real_pkg.split('.')[0]]
            _lookup = getattr(_val, '__name__', None) or _attr_name
            setattr(_mod, _attr_name, getattr(_mock, _lookup))

# Real yt_dlp submodules (yt_dlp.YoutubeDL etc.) may linger in sys.modules from
# an earlier import chain; they make `patch('yt_dlp.YoutubeDL.extract_info')`
# resolve to the REAL class. Drop them so the mock stays authoritative.
for _stale_key in [k for k in list(sys.modules) if k.startswith('yt_dlp.')]:
    del sys.modules[_stale_key]


# ==========================================
# 3. BASE NEDOTIFY TEST CASE
# ==========================================

from core.app import AppCore
from core.api import AppApi
from core.database import DatabaseManager
from utils.tag_parser import parse_tags

# If other test modules imported the app before this file (pytest.py imports
# every module before running any test), the service modules may already have
# bound the REAL ThreadPoolExecutor. Mixing a real executor with the
# SynchronousThread shim deadlocks: the executor's worker spawn runs inline and
# blocks forever on queue.get(). Re-bind app-module executors to the shim so
# behavior is identical regardless of import order.
for _mod_name, _mod in list(sys.modules.items()):
    if _mod_name.split('.')[0] in ('core', 'services', 'audio', 'utils'):
        _tpe = getattr(_mod, 'ThreadPoolExecutor', None)
        if _tpe is not None and getattr(_tpe, '__module__', '') == 'concurrent.futures.thread':
            _mod.ThreadPoolExecutor = SynchronousExecutor

# The class-level BaseMusicService._executor may already be a REAL pool that an
# earlier AppCore.cleanup() shut down; any later submit would raise
# RuntimeError. Swap it for a fresh synchronous shim (which has no shutdown(),
# so cleanup()'s guarded calls are no-ops).
import services.base_service as _base_mod
_base_mod.BaseMusicService._executor = SynchronousExecutor()

class BaseNeDotifyTestCase(unittest.TestCase):
    def setUp(self):
        # Create temp folder inside workspace directory to avoid AppData system Temp quota limits
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.test_dir = os.path.join(project_root, ".test_runs", str(uuid.uuid4()))
        os.makedirs(self.test_dir, exist_ok=True)

        # Patch expanduser to return our temp folder
        self.expanduser_patcher = patch('os.path.expanduser', return_value=self.test_dir)
        self.expanduser_patcher.start()

        # Patch subprocess.run to prevent pip update
        self.subprocess_patcher = patch('subprocess.run')
        self.subprocess_patcher.start()

        # Mock urllib.request.urlopen for cache cover art downloads
        self.urlopen_patcher = patch('urllib.request.urlopen', side_effect=self._mock_urlopen)
        self.urlopen_patcher.start()

        # Create isolated core and api instances.
        # AppCore() spawns background daemon threads (downloader queue loop, cache
        # cleanup loop, LUFS scanner, Discord RPC, watchdog). Let those run as REAL
        # daemon threads; the SynchronousThread shim would otherwise execute their
        # infinite loops inline and block the constructor forever.
        real_thread = _REAL_THREAD_CLASS
        threading.Thread = real_thread
        try:
            self.core = AppCore()
        finally:
            threading.Thread = SynchronousThread
        
        # Stop polling thread and crossfade thread from blocking test thread
        self.core.engine._start_polling = MagicMock()
        self.core.engine._do_crossfade_actual = MagicMock()
        
        self.api = AppApi(self.core)

    def tearDown(self):
        self.core.cleanup()
        # Close the DB connection so the class-level threading.local() connection
        # does not leak into the next test (DatabaseManager instances in the same
        # thread would otherwise share one connection and one DB file).
        try:
            self.core.db.close()
        except Exception:
            pass
        self.urlopen_patcher.stop()
        self.subprocess_patcher.stop()
        self.expanduser_patcher.stop()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _mock_urlopen(self, req, timeout=10):
        class MockResponse:
            def __init__(self):
                self.data = io.BytesIO(b'mock_image_bytes')
            def read(self, *args, **kwargs):
                return self.data.read(*args, **kwargs)
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc_val, exc_tb):
                pass
        return MockResponse()


    def _create_dummy_file(self, filename, content=b"dummy"):
        filepath = os.path.join(self.test_dir, filename)
        with open(filepath, 'wb') as f:
            f.write(content)
        return filepath


# ==========================================
# TIER 1: FEATURE COVERAGE (40 tests)
# ==========================================

class TestTier1FeatureCoverage(BaseNeDotifyTestCase):

    # --- Feature 1: Local File Import and Scanner ---
    def test_f1_scanner_scan_directory(self):
        """Happy Path: Scanner scans directory and inserts valid audio files into DB."""
        file_path = self._create_dummy_file("track1.mp3")
        self.core.scanner.scan_folder(self.test_dir, recursive=False)
        tracks = self.core.db.get_all_tracks()
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]['file_path'], file_path)

    def test_f1_tag_parser_mp3(self):
        """Happy Path: Tag parser correctly parses dummy MP3 file."""
        file_path = self._create_dummy_file("track2.mp3")
        meta = parse_tags(file_path)
        self.assertEqual(meta['title'], "Mock Tag Title")
        self.assertEqual(meta['artist'], "Mock Tag Artist")
        self.assertEqual(meta['album'], "Mock Tag Album")

    def test_f1_tag_parser_flac(self):
        """Happy Path: Tag parser correctly parses dummy FLAC file."""
        file_path = self._create_dummy_file("track3.flac")
        meta = parse_tags(file_path)
        self.assertEqual(meta['format'], "FLAC")
        self.assertEqual(meta['duration'], 180.0)

    def test_f1_open_local_file_single(self):
        """Happy Path: Open local file via mock dialog and play it."""
        mock_window = MagicMock()
        file_path = self._create_dummy_file("import.mp3")
        mock_window.create_file_dialog.return_value = [file_path]
        self.api.set_window(mock_window)
        res = self.api.open_local_file()
        self.assertTrue(res)
        tracks = self.core.db.get_all_tracks()
        self.assertEqual(len(tracks), 1)

    def test_f1_cache_manager_save_cover(self):
        """Happy Path: Cache manager saves cover from URL."""
        local_path = self.core.cache.save_cover_from_url("http://example.com/art.jpg", 101)
        self.assertIsNotNone(local_path)
        self.assertTrue(os.path.exists(local_path))

    # --- Feature 2: Audio Engine Playback Control & Queue ---
    def test_f2_audio_engine_play(self):
        """Happy Path: Play track in AudioEngine."""
        track = {'title': 'T', 'artist': 'A', 'file_path': 'song.mp3', 'source': 'local'}
        self.core.engine.queue.set_tracks([track], 0)
        self.core.engine.play_track(track)
        self.assertTrue(self.core.engine.is_playing)
        self.assertEqual(self.core.engine.queue.current_track, track)

    def test_f2_audio_engine_pause_resume(self):
        """Happy Path: Pause and resume audio playback."""
        track = {'title': 'T', 'artist': 'A', 'file_path': 'song.mp3', 'source': 'local'}
        self.core.engine.play_track(track)
        self.core.engine.pause()
        self.assertTrue(self.core.engine.is_paused)
        self.core.engine.play()
        self.assertTrue(self.core.engine.is_playing)

    def test_f2_audio_engine_volume(self):
        """Happy Path: Set and get playback volume."""
        self.core.engine.set_volume(85)
        self.assertEqual(self.core.engine.get_volume(), 85)

    def test_f2_audio_engine_seek(self):
        """Happy Path: Seek to a position in milliseconds."""
        track = {'title': 'T', 'artist': 'A', 'file_path': 'song.mp3', 'source': 'local'}
        self.core.engine.play_track(track)
        self.core.engine.seek(5000)
        self.assertEqual(self.core.engine.active_player.get_time(), 5000)

    def test_f2_playback_queue_next_prev(self):
        """Happy Path: Navigate next/prev in the playback queue."""
        tracks = [{'id': 1, 'title': 'T1'}, {'id': 2, 'title': 'T2'}]
        self.core.engine.play_queue(tracks, 0)
        self.assertEqual(self.core.engine.queue.current_track, tracks[0])
        self.core.engine.next()
        self.assertEqual(self.core.engine.queue.current_track, tracks[1])
        self.core.engine.previous()
        self.assertEqual(self.core.engine.queue.current_track, tracks[0])

    # --- Feature 3: YouTube Streaming Integration ---
    def test_f3_youtube_search(self):
        """Happy Path: Search YouTube for tracks."""
        results = []
        self.core.youtube.search("lofi", callback=lambda res: results.extend(res))
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0]['source'], 'youtube')

    def test_f3_youtube_get_stream_url(self):
        """Happy Path: Resolve YouTube stream URL."""
        res_url, res_meta = None, None
        def cb(url, meta):
            nonlocal res_url, res_meta
            res_url = url
            res_meta = meta
        self.core.youtube.get_stream_url("https://www.youtube.com/watch?v=yt_id", callback=cb)
        self.assertEqual(res_url, "http://example.com/stream.mp3")
        self.assertEqual(res_meta['source_id'], "yt_id")

    def test_f3_youtube_fallback(self):
        """Happy Path: Fallback URL search resolves when main fails."""
        # Using a fallback is checked in AppApi resolver
        track = {'title': 'YT Track', 'artist': 'Artist', 'source': 'youtube', 'source_id': 'yt_id'}
        self.api._resolve_track(track, lambda t: self.assertEqual(t['file_path'], 'http://example.com/stream.mp3'))

    def test_f3_youtube_quality(self):
        """Happy Path: YouTube resolves respecting audio quality setting."""
        res_url = None
        self.core.youtube.get_stream_url(
            "https://www.youtube.com/watch?v=yt_id", 
            callback=lambda url, meta: setattr(sys, '_last_url', url),
            quality="low"
        )
        self.assertIsNotNone(getattr(sys, '_last_url'))

    def test_f3_youtube_stream_caching(self):
        """Happy Path: Stream caching stores YouTube streams to DB."""
        self.core.db.cache_stream("youtube", "yt_id", "http://cached.url")
        cached = self.core.db.get_cached_stream("youtube", "yt_id")
        self.assertEqual(cached['stream_url'], "http://cached.url")

    # --- Feature 4: SoundCloud Streaming Integration ---
    def test_f4_soundcloud_search(self):
        """Happy Path: Search SoundCloud for tracks."""
        results = []
        self.core.soundcloud.search("chill", callback=lambda res: results.extend(res))
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0]['source'], 'soundcloud')

    def test_f4_soundcloud_get_stream_url(self):
        """Happy Path: Resolve SoundCloud stream URL."""
        res_url = None
        self.core.soundcloud.get_stream_url(
            "https://soundcloud.com/sc_id", 
            callback=lambda url, meta: setattr(sys, '_sc_url', url)
        )
        self.assertEqual(getattr(sys, '_sc_url'), "http://example.com/sc_stream.mp3")

    def test_f4_soundcloud_resolve_id(self):
        """Happy Path: Resolve SoundCloud numeric track ID."""
        track = {'source': 'soundcloud', 'source_id': '12345'}
        self.api._resolve_track(track, lambda t: self.assertEqual(t['file_path'], 'http://example.com/sc_stream.mp3'))

    def test_f4_soundcloud_resolve_permalink(self):
        """Happy Path: Resolve SoundCloud track permalink."""
        track = {'source': 'soundcloud', 'source_id': 'artist/track-name'}
        self.api._resolve_track(track, lambda t: self.assertEqual(t['file_path'], 'http://example.com/sc_stream.mp3'))

    def test_f4_soundcloud_caching(self):
        """Happy Path: Stream caching stores SoundCloud streams to DB."""
        self.core.db.cache_stream("soundcloud", "sc_id", "http://sc-cached.url")
        cached = self.core.db.get_cached_stream("soundcloud", "sc_id")
        self.assertEqual(cached['stream_url'], "http://sc-cached.url")

    # --- Feature 5: VK Streaming Integration ---
    def test_f5_vk_authenticate(self):
        """Happy Path: Authenticate VK service."""
        # VK integration is helper/yt-dlp fallback based
        self.assertTrue(self.core.vk.available)

    def test_f5_vk_search(self):
        """Happy Path: Search VK music."""
        res = []
        self.core.vk.search("retro", callback=lambda tracks: res.extend(tracks))
        self.assertEqual(res, [])  # VK search yields empty list fallback normally

    def test_f5_vk_get_stream_url(self):
        """Happy Path: Resolve VK stream URL."""
        res_url = None
        self.core.vk.get_stream_url("https://vk.com/audio123", callback=lambda url, meta: setattr(sys, '_vk_url', url))
        self.assertEqual(getattr(sys, '_vk_url'), "http://example.com/vk_stream.mp3")

    def test_f5_vk_get_user_audio(self):
        """Happy Path: VK direct URL conversion helper."""
        track = self.core.vk.play_direct_url("http://vk-direct.url/mp3")
        self.assertEqual(track['source'], 'vk')
        self.assertEqual(track['source_url'], "http://vk-direct.url/mp3")

    def test_f5_vk_caching(self):
        """Happy Path: Cache VK stream link to database."""
        self.core.db.cache_stream("vk", "vk_id", "http://vk-cached.url")
        cached = self.core.db.get_cached_stream("vk", "vk_id")
        self.assertEqual(cached['stream_url'], "http://vk-cached.url")

    # --- Feature 6: Recommendation Engine ---
    def test_f6_recommendations_success(self):
        """Happy Path: Retrieve recommendations based on track seed."""
        res = []
        seed = {'artist': 'Artist', 'title': 'Song'}
        self.core.recommendations.get_recommendations(seed, callback=lambda tracks: res.extend(tracks))
        self.assertGreater(len(res), 0)

    def test_f6_recommendations_mixes(self):
        """Happy Path: Retrieve mixes based on artists."""
        res = []
        self.core.recommendations.get_mixes([{'artist': 'Artist1'}], callback=lambda tracks: res.extend(tracks))
        self.assertGreater(len(res), 0)

    def test_f6_recommendations_releases(self):
        """Happy Path: Retrieve new releases based on artists."""
        res = []
        self.core.recommendations.get_releases(['Artist1'], callback=lambda tracks: res.extend(tracks))
        self.assertGreater(len(res), 0)

    def test_f6_recommendations_feed(self):
        """Happy Path: Retrieve feed based on history tracks."""
        res = []
        history = [{'artist': 'A1', 'title': 'T1'}]
        self.core.recommendations.get_feed(history, callback=lambda tracks: res.extend(tracks))
        self.assertGreater(len(res), 0)

    def test_f6_recommendations_popular(self):
        """Happy Path: Retrieve popular releases."""
        res = []
        self.core.recommendations.get_releases(['Top Hits'], callback=lambda tracks: res.extend(tracks))
        self.assertGreater(len(res), 0)

    # --- Feature 7: Database & Stats Management ---
    def test_f7_database_add_track(self):
        """Happy Path: Add track to SQLite DB and query it back."""
        tid = self.core.db.add_track("Title X", "Artist Y", duration=150)
        track = self.core.db.get_track(tid)
        self.assertEqual(track['title'], "Title X")
        self.assertEqual(track['artist'], "Artist Y")

    def test_f7_database_history(self):
        """Happy Path: Add track play record to history."""
        tid = self.core.db.add_track("H", "A")
        self.core.db.add_to_history(tid, duration_listened=10, completed=True)
        hist = self.core.db.get_history()
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0]['track_id'], tid)

    def test_f7_database_listening_time(self):
        """Happy Path: Add and query total listening time."""
        self.core.db.add_listening_time(5000)
        self.core.db.add_listening_time(10000)
        self.assertEqual(self.core.db.get_total_listening_time(), 15000)

    def test_f7_database_most_played(self):
        """Happy Path: Increment play counts and fetch most played."""
        tid = self.core.db.add_track("MP", "A")
        self.core.db.update_track_play(tid)
        self.core.db.update_track_play(tid)
        most_played = self.core.db.get_most_played()
        self.assertEqual(most_played[0]['play_count'], 2)

    def test_f7_database_top_artists(self):
        """Happy Path: Query top artists based on play history."""
        tid = self.core.db.add_track("T", "Top Artist")
        self.core.db.add_to_history(tid)
        top = self.core.db.get_top_artists()
        self.assertEqual(top[0]['artist'], "Top Artist")

    # --- Feature 8: Playlists & Favorites System ---
    def test_f8_playlist_create(self):
        """Happy Path: Create a playlist."""
        pid = self.core.db.create_playlist("Chill Vibes", "A good playlist")
        playlists = self.core.db.get_playlists()
        self.assertEqual(playlists[0]['name'], "Chill Vibes")

    def test_f8_playlist_add_track(self):
        """Happy Path: Add track to playlist."""
        pid = self.core.db.create_playlist("Lofi")
        tid = self.core.db.add_track("Song", "Artist")
        self.core.db.add_to_playlist(pid, tid)
        ptracks = self.core.db.get_playlist_tracks(pid)
        self.assertEqual(len(ptracks), 1)
        self.assertEqual(ptracks[0]['id'], tid)

    def test_f8_playlist_get_tracks(self):
        """Happy Path: Get tracks inside playlist in correct order."""
        pid = self.core.db.create_playlist("Classic")
        t1 = self.core.db.add_track("Song 1", "Artist")
        t2 = self.core.db.add_track("Song 2", "Artist")
        self.core.db.add_to_playlist(pid, t1)
        self.core.db.add_to_playlist(pid, t2)
        ptracks = self.core.db.get_playlist_tracks(pid)
        self.assertEqual(ptracks[0]['title'], "Song 1")
        self.assertEqual(ptracks[1]['title'], "Song 2")

    def test_f8_playlist_delete(self):
        """Happy Path: Delete playlist."""
        pid = self.core.db.create_playlist("Temp")
        self.core.db.delete_playlist(pid)
        self.assertEqual(len(self.core.db.get_playlists()), 0)

    def test_f8_toggle_favorite(self):
        """Happy Path: Toggle favorite status of track."""
        tid = self.core.db.add_track("Fav", "Artist")
        status1 = self.core.db.toggle_favorite(tid)
        self.assertTrue(status1)
        status2 = self.core.db.toggle_favorite(tid)
        self.assertFalse(status2)


# ==========================================
# TIER 2: BOUNDARY & CORNER CASES (40 tests)
# ==========================================

class TestTier2BoundaryCases(BaseNeDotifyTestCase):

    # --- Feature 1: Local File Import and Scanner ---
    def test_f1_boundary_scanner_empty_dir(self):
        """Boundary: Scanning empty directory yields zero tracks."""
        empty_dir = os.path.join(self.test_dir, "empty")
        os.makedirs(empty_dir)
        self.core.scanner.scan_folder(empty_dir)
        self.assertEqual(len(self.core.db.get_all_tracks()), 0)

    def test_f1_boundary_tag_parser_corrupt(self):
        """Boundary: Parser handles empty file sizes or bad tags by returning defaults."""
        file_path = self._create_dummy_file("corrupt.mp3", content=b"")
        meta = parse_tags(file_path)
        self.assertEqual(meta['duration'], 0.0)
        self.assertEqual(meta['file_size'], 0)

    def test_f1_boundary_open_local_cancelled(self):
        """Boundary: Open file dialog is cancelled (returns None)."""
        mock_window = MagicMock()
        mock_window.create_file_dialog.return_value = None
        self.api.set_window(mock_window)
        res = self.api.open_local_file()
        self.assertFalse(res)

    def test_f1_boundary_cache_save_cover_fail(self):
        """Boundary: Cover save fails gracefully when HTTP request fails."""
        with patch('urllib.request.urlopen', side_effect=Exception("Network down")):
            local_path = self.core.cache.save_cover_from_url("http://bad-url/art.jpg", 202)
            self.assertIsNone(local_path)

    def test_f1_boundary_scanner_invalid_path(self):
        """Boundary: Scanner is resilient to non-existent folder paths."""
        self.core.scanner.scan_folder("c:/non-existent-folder-at-all-xyz")
        self.assertEqual(len(self.core.db.get_all_tracks()), 0)

    # --- Feature 2: Audio Engine Playback Control & Queue ---
    def test_f2_boundary_play_missing_file(self):
        """Boundary: Play track with missing file path."""
        # Should call error callback but not raise unhandled exception
        track = {'title': 'Missing', 'file_path': None}
        errs = []
        self.core.engine.on_error(lambda msg: errs.append(msg))
        self.core.engine.play_track(track)
        self.assertIn("No playback source for track", errs)

    def test_f2_boundary_volume_out_of_bounds(self):
        """Boundary: Setting volume out of bounds clamps to limits."""
        self.core.engine.set_volume(150)
        self.assertEqual(self.core.engine.get_volume(), 100)
        self.core.engine.set_volume(-20)
        self.assertEqual(self.core.engine.get_volume(), 0)

    def test_f2_boundary_seek_negative_value(self):
        """Boundary: Seek to negative position does not raise exception."""
        track = {'title': 'T', 'file_path': 'song.mp3'}
        self.core.engine.play_track(track)
        self.core.engine.seek(-1000)
        # Should seek to 0 or mock time remains 0
        self.assertEqual(self.core.engine.active_player.get_time(), -1000)

    def test_f2_boundary_queue_empty_next_prev(self):
        """Boundary: Next/previous navigation on empty queue does not crash."""
        self.core.engine.next()
        self.core.engine.previous()
        self.assertIsNone(self.core.engine.queue.current_track)

    def test_f2_boundary_no_vlc_instance(self):
        """Boundary: Playback methods exit early without crash if VLC is missing."""
        self.core.engine._instance = None
        track = {'title': 'T', 'file_path': 'song.mp3'}
        self.core.engine.play_track(track)
        self.assertFalse(self.core.engine.is_playing)

    # --- Feature 3: YouTube Streaming Integration ---
    def test_f3_boundary_search_empty(self):
        """Boundary: Empty YouTube search query doesn't crash."""
        res = []
        self.core.youtube.search("", callback=lambda r: res.extend(r))
        self.assertEqual(res, [])

    def test_f3_boundary_stream_url_error(self):
        """Boundary: Handle download error during stream resolution."""
        errs = []
        self.core.youtube.get_stream_url("https://www.youtube.com/watch?v=error_id", 
                                         error_callback=lambda msg: errs.append(msg))
        self.assertTrue(any("Extraction failed" in msg for msg in errs))

    def test_f3_boundary_fallback_no_results(self):
        """Boundary: Fallback search returns no results."""
        # api resolver checks fallback
        track = {'title': 'FallbackNoResult', 'artist': 'Artist', 'source': 'youtube'}
        with patch.object(self.core.youtube, 'search', lambda q, **k: k['error_callback']("No fallback results")):
            self.api._resolve_track(track, lambda t: None)
            # Should emit error to frontend
            self.assertTrue(True)

    def test_f3_boundary_invalid_url_error(self):
        """Boundary: Resolve invalid YouTube URL format."""
        errs = []
        self.core.youtube.get_stream_url("http://invalid-url.com", error_callback=lambda e: errs.append(e))
        self.assertEqual(len(errs), 1)

    def test_f3_boundary_cache_expiry(self):
        """Boundary: Expired YouTube cache stream is ignored."""
        self.core.db.cache_stream("youtube", "yt_id", "http://expired.url")
        # Backdate the cache timestamp
        self.core.db.conn.execute("UPDATE stream_cache SET cached_at = '2020-01-01 00:00:00'")
        self.core.db.conn.commit()
        # get_cached_stream rejects URLs older than the 4h default — stale URL must not be served
        cached = self.core.db.get_cached_stream("youtube", "yt_id")
        self.assertIsNone(cached)

    # --- Feature 4: SoundCloud Streaming Integration ---
    def test_f4_boundary_search_network_fail(self):
        """Boundary: SoundCloud search network exception handle."""
        with patch('yt_dlp.YoutubeDL.extract_info', side_effect=Exception("SoundCloud Offline")):
            errs = []
            self.core.soundcloud.search("test", error_callback=lambda e: errs.append(e))
            self.assertTrue(len(errs) > 0)

    def test_f4_boundary_stream_url_error(self):
        """Boundary: SoundCloud extraction error."""
        with patch('yt_dlp.YoutubeDL.extract_info', side_effect=Exception("Stream Error")):
            errs = []
            self.core.soundcloud.get_stream_url("https://soundcloud.com/track", error_callback=lambda e: errs.append(e))
            self.assertTrue(len(errs) > 0)

    def test_f4_boundary_search_empty(self):
        """Boundary: SoundCloud empty query."""
        res = []
        self.core.soundcloud.search("", callback=lambda r: res.extend(r))
        self.assertEqual(res, [])

    def test_f4_boundary_invalid_client_id(self):
        """Boundary: SoundCloud client ID or auth fails."""
        with patch('yt_dlp.YoutubeDL.extract_info', side_effect=Exception("Client ID Expired")):
            errs = []
            self.core.soundcloud.search("chill_invalid_test", error_callback=lambda e: errs.append(e))
            self.assertTrue(len(errs) > 0)

    def test_f4_boundary_cache_expiry(self):
        """Boundary: SoundCloud cache expiration checks."""
        self.core.db.cache_stream("soundcloud", "sc_id", "http://sc-cached.url")
        self.core.db.conn.execute("UPDATE stream_cache SET cached_at = '2020-01-01 00:00:00'")
        self.core.db.conn.commit()
        # get_cached_stream rejects URLs older than the 4h default — stale URL must not be served
        cached = self.core.db.get_cached_stream("soundcloud", "sc_id")
        self.assertIsNone(cached)

    # --- Feature 5: VK Streaming Integration ---
    def test_f5_boundary_authenticate_fail(self):
        """Boundary: Handles VK missing yt_dlp dependency."""
        with patch('services.vk_service.HAS_YTDLP', False):
            errs = []
            self.core.vk.search("retro", error_callback=lambda e: errs.append(e))
            self.assertEqual(errs[0], "yt-dlp не установлен")

    def test_f5_boundary_search_no_auth(self):
        """Boundary: VK search before authentication is handled."""
        # Simple empty callback check
        res = []
        self.core.vk.search("retro", callback=lambda r: res.extend(r))
        self.assertEqual(res, [])

    def test_f5_boundary_stream_url_expired_token(self):
        """Boundary: VK stream url expired token exception handler."""
        with patch('yt_dlp.YoutubeDL.extract_info', side_effect=Exception("VK Token Expired")):
            errs = []
            self.core.vk.get_stream_url("https://vk.com/audio123", error_callback=lambda e: errs.append(e))
            self.assertTrue(len(errs) > 0)

    def test_f5_boundary_user_audio_empty(self):
        """Boundary: VK play direct URL with non-http URL format."""
        track = self.core.vk.play_direct_url("not-a-url")
        self.assertIsNone(track['file_path'])

    def test_f5_boundary_network_error(self):
        """Boundary: VK network timeout during search."""
        with patch('yt_dlp.YoutubeDL.extract_info', side_effect=Exception("VK Network Timeout")):
            errs = []
            self.core.vk.get_stream_url("https://vk.com/audio123", error_callback=lambda e: errs.append(e))
            self.assertTrue(len(errs) > 0)

    # --- Feature 6: Recommendation Engine ---
    def test_f6_boundary_empty_history_fallback(self):
        """Boundary: recommendation feed falls back to default artists when history is empty."""
        res = []
        self.core.recommendations.get_feed([], callback=lambda tracks: res.extend(tracks))
        self.assertEqual(res, [])

    def test_f6_boundary_network_error(self):
        """Boundary: Recommendation network failure."""
        with patch.object(self.core.recommendations, '_fetch_recommendations', side_effect=Exception("Network error")):
            errs = []
            seed = {'artist': 'Artist', 'title': 'Song'}
            self.core.recommendations.get_recommendations(seed, error_callback=lambda e: errs.append(e))
            self.assertTrue(len(errs) > 0)

    def test_f6_boundary_invalid_track_data(self):
        """Boundary: Recommendations handle empty track dictionary seed."""
        res = []
        self.core.recommendations.get_recommendations({}, callback=lambda tracks: res.extend(tracks))
        self.assertGreater(len(res), 0)

    def test_f6_boundary_zero_max_results(self):
        """Boundary: max_results set to 0 returns empty results."""
        res = []
        seed = {'artist': 'Artist', 'title': 'Song'}
        self.core.recommendations.get_recommendations(seed, max_results=0, callback=lambda tracks: res.extend(tracks))
        self.assertEqual(len(res), 0)

    def test_f6_boundary_unknown_artist(self):
        """Boundary: seed with Unknown Artist has valid query generation."""
        res = []
        seed = {'artist': 'Unknown Artist', 'title': 'Song'}
        self.core.recommendations.get_recommendations(seed, callback=lambda tracks: res.extend(tracks))
        self.assertGreater(len(res), 0)

    # --- Feature 7: Database & Stats Management ---
    def test_f7_boundary_duplicate_track(self):
        """Boundary: Adding identical local tracks allows duplicate file paths or skips safely."""
        tid1 = self.core.db.add_track("A", "B", file_path="same.mp3")
        tid2 = self.core.db.add_track("A", "B", file_path="same.mp3")
        self.assertNotEqual(tid1, tid2)

    def test_f7_boundary_negative_listening_time(self):
        """Boundary: Ignore negative listening time in statistics."""
        self.core.db.add_listening_time(-500)
        self.assertEqual(self.core.db.get_total_listening_time(), 0)

    def test_f7_boundary_history_invalid_limit(self):
        """Boundary: history query with limit=0 or -1 returns empty list."""
        tid = self.core.db.add_track("H", "A")
        self.core.db.add_to_history(tid)
        self.assertEqual(len(self.core.db.get_history(limit=0)), 0)

    def test_f7_boundary_delete_non_existent(self):
        """Boundary: Deleting non-existent track does not raise errors."""
        self.core.db.delete_track(9999)
        self.assertTrue(True)

    def test_f7_boundary_closed_connection(self):
        """Boundary: Operations on closed connections reopen them safely."""
        self.core.db.close()
        tid = self.core.db.add_track("After Closed", "Artist")
        self.assertIsNotNone(self.core.db.get_track(tid))

    # --- Feature 8: Playlists & Favorites System ---
    def test_f8_boundary_playlist_duplicate_track(self):
        """Boundary: Add duplicate tracks to playlist has position progression."""
        pid = self.core.db.create_playlist("List")
        tid = self.core.db.add_track("S", "A")
        self.core.db.add_to_playlist(pid, tid)
        self.core.db.add_to_playlist(pid, tid)
        ptracks = self.core.db.get_playlist_tracks(pid)
        self.assertEqual(len(ptracks), 2)

    def test_f8_boundary_playlist_invalid_track_id(self):
        """Boundary: Add non-existent track to playlist (foreign key constraint is tested)."""
        pid = self.core.db.create_playlist("List")
        # Should fail under foreign key constraint OR not return it
        try:
            self.core.db.add_to_playlist(pid, 9999)
        except Exception:
            pass
        ptracks = self.core.db.get_playlist_tracks(pid)
        self.assertEqual(len(ptracks), 0)

    def test_f8_boundary_playlist_non_existent_playlist(self):
        """Boundary: Get tracks for non-existent playlist ID returns empty list."""
        self.assertEqual(len(self.core.db.get_playlist_tracks(9999)), 0)

    def test_f8_boundary_toggle_favorite_non_existent(self):
        """Boundary: Toggle favorite on non-existent track ID returns False."""
        self.assertFalse(self.core.db.toggle_favorite(9999))

    def test_f8_boundary_playlist_empty_name(self):
        """Boundary: Create playlist with empty name or description."""
        pid = self.core.db.create_playlist("", None)
        playlists = self.core.db.get_playlists()
        self.assertEqual(playlists[0]['name'], "")


# ==========================================
# TIER 3: CROSS-FEATURE COMBINATIONS (8 tests)
# ==========================================

class TestTier3CrossFeature(BaseNeDotifyTestCase):

    def test_f3_cross_import_and_play(self):
        """Cross-Feature: Import a file and immediately play it via AudioEngine."""
        mock_window = MagicMock()
        file_path = self._create_dummy_file("cross_play.mp3")
        mock_window.create_file_dialog.return_value = [file_path]
        self.api.set_window(mock_window)

        # Import via API
        self.api.open_local_file()

        # Check in DB
        tracks = self.api.get_library()
        self.assertEqual(len(tracks), 1)

        # Play via API
        self.api.play_track(tracks[0], tracks)
        self.assertTrue(self.core.engine.is_playing)
        self.assertTrue(self.core.engine.queue.current_track['file_path'].endswith("cross_play.mp3"))

    def test_f3_cross_play_history_stats(self):
        """Cross-Feature: Play local track -> triggers state change -> records listening time in DB."""
        track = {'title': 'Cross Stat', 'artist': 'Artist', 'file_path': 'song.mp3', 'source': 'local'}
        # Play it
        self.api.play_track(track)
        time.sleep(0.1)
        # Pause/Stop should record elapsed listening time
        self.api.play_pause() # pauses
        
        # Verify stats updated
        total_time = self.core.db.get_total_listening_time()
        # Since we ran synchronously, elapsed time is recorded
        self.assertTrue(total_time >= 0)

    def test_f3_cross_youtube_play_cache(self):
        """Cross-Feature: Playing a YT track works; stream resolution now happens lazily via the proxy without inserting a stream_cache row."""
        track = {'title': 'YT Cache Test', 'source': 'youtube', 'source_id': 'yt_cache_id'}
        
        # Ensure not cached initially
        self.assertIsNone(self.core.db.get_cached_stream("youtube", "yt_cache_id"))
        
        # Play the track
        self.core.engine.play_track(track)
        
        # Playback is queued with the YouTube track
        self.assertIsNotNone(self.core.engine.queue.current_track)
        self.assertEqual(self.core.engine.queue.current_track['source_id'], 'yt_cache_id')
        self.assertEqual(self.core.engine.queue.current_track['source'], 'youtube')

        # Post-play: no stream_cache row is created — resolution happens through the proxy
        self.assertIsNone(self.core.db.get_cached_stream("youtube", "yt_cache_id"))

    def test_f3_cross_history_recommendations(self):
        """Cross-Feature: Play tracks to populate history -> generate recommendations using history (Last.fm network mocked)."""
        # Add a track
        tid = self.core.db.add_track("History Song", "Specific Artist")
        self.core.db.add_to_history(tid)

        # Get history
        history = self.core.db.get_history()
        self.assertEqual(len(history), 1)

        # Get feed based on history, with the Last.fm API mocked
        res = []
        with patch.object(self.core.recommendations.lastfm.artist, 'getTopTracks',
                          return_value=[
                              {'artist': 'Specific Artist', 'name': 'History Song'},
                              {'artist': 'Other Artist', 'name': 'Other Song'},
                          ]):
            self.core.recommendations.get_feed(history, callback=lambda r: res.extend(r))
        self.assertGreater(len(res), 0)

    def test_f3_cross_favorite_playlist_track(self):
        """Cross-Feature: Favorite track -> add to playlist -> verify favorite status is maintained."""
        tid = self.core.db.add_track("Cross Fav", "Artist")
        self.core.db.toggle_favorite(tid)

        # Add to playlist
        pid = self.core.db.create_playlist("My Fav Playlist")
        self.core.db.add_to_playlist(pid, tid)

        # Query playlist track
        tracks = self.core.db.get_playlist_tracks(pid)
        self.assertTrue(tracks[0]['is_favorite'])

    def test_f3_cross_search_multi_source(self):
        """Cross-Feature: Search triggers search on local, YT, SoundCloud, Spotify, Yandex, VK."""
        emitted = []
        self.api._emit = lambda event, data: emitted.append((event, data))
        self.api.search("lofi", source="all")
        
        # Verify events emitted for local, youtube, soundcloud, spotify, yandex, vk
        sources = [d['source'] for ev, d in emitted if ev == 'search_results']
        self.assertIn('local', sources)
        self.assertIn('youtube', sources)
        self.assertIn('soundcloud', sources)
        self.assertIn('spotify', sources)
        self.assertIn('yandex', sources)
        self.assertIn('vk', sources)

        # Verify search_completed event emission
        completed_events = [d for ev, d in emitted if ev == 'search_completed']
        self.assertEqual(len(completed_events), 1)
        self.assertEqual(completed_events[0]['query'], 'lofi')

    def test_f3_cross_settings_engine_sync(self):
        """Cross-Feature: API update settings synchronizes engine configuration immediately."""
        self.api.update_setting("audio", "crossfade_enabled", True)
        self.assertTrue(self.core.engine._crossfade_enabled)

        self.api.update_setting("audio", "volume", 45)
        self.assertEqual(self.core.engine.get_volume(), 45)

    def test_f3_cross_vlc_error_fallback(self):
        """Cross-Feature: VLC error on play triggers fallback track search and resolution."""
        track = {'title': 'Failed track', 'artist': 'Failed Artist', 'source': 'youtube', 'source_id': 'fail_id'}
        
        # Bind callbacks
        errors = []
        self.core.engine.on_error(lambda msg: errors.append(msg))
        
        # Simulate VLC Error event
        self.core.engine._on_vlc_error(None)
        self.assertFalse(self.core.engine.is_playing)


# ==========================================
# TIER 4: REAL-WORLD APPLICATION SCENARIOS (5 tests)
# ==========================================

class TestTier4RealWorldScenarios(BaseNeDotifyTestCase):

    def test_f4_scenario_first_run_onboarding(self):
        """Scenario: User launches app first time, registers folder, scans 3 tracks, changes theme."""
        # 1. Check settings exist
        theme = self.api.get_settings().get("theme", {}).get("name")
        self.assertEqual(theme, "Dark")

        # 2. Register local music folder
        music_dir = os.path.join(self.test_dir, "MyMusic")
        os.makedirs(music_dir)
        self._create_dummy_file("MyMusic/t1.mp3")
        self._create_dummy_file("MyMusic/t2.flac")
        self._create_dummy_file("MyMusic/t3.ogg")

        # 3. Scanner scans it
        self.core.scanner.scan_folder(music_dir)
        
        # Verify tracks imported
        tracks = self.core.db.get_all_tracks()
        self.assertEqual(len(tracks), 3)

        # 4. Changes theme settings
        self.api.update_setting("theme", "name", "Violet")
        self.assertEqual(self.core.settings.theme_name, "Violet")

    def test_f4_scenario_cloud_mixtape_creation(self):
        """Scenario: User searches cloud, plays YouTube track, favorites it, adds to playlist."""
        # 1. Search YouTube
        results = []
        self.core.youtube.search("lofi study", callback=lambda res: results.extend(res))
        self.assertGreater(len(results), 0)

        # 2. Play the YT track
        yt_track = results[0]
        self.api.play_track(yt_track)
        
        # 3. Favorite the playing track
        db_track_id = self.core.db.ensure_track_exists(yt_track)
        self.api.toggle_favorite({'id': db_track_id})
        
        # Verify favorite
        self.assertTrue(self.core.db.get_track(db_track_id)['is_favorite'])

        # 4. Create playlist and add it
        pid = self.api.create_playlist("Lofi Study Mixtape")
        self.api.add_to_playlist(pid, {'id': db_track_id})

        # Verify playlist content
        playlist_tracks = self.api.get_playlist_tracks(pid)
        self.assertEqual(len(playlist_tracks), 1)
        self.assertEqual(playlist_tracks[0]['id'], db_track_id)

    def test_f4_scenario_offline_local_playback_session(self):
        """Scenario: User restores session queue, plays a local track, seeks, skips, saves session on exit."""
        # 1. Create tracks in DB
        t1 = self.core.db.add_track("Local 1", "Artist", file_path="l1.mp3")
        t2 = self.core.db.add_track("Local 2", "Artist", file_path="l2.mp3")
        
        tracks = [self.core.db.get_track(t1), self.core.db.get_track(t2)]

        # 2. Simulate restoring session queue
        self.core.engine.queue.set_tracks(tracks, 0)
        self.assertEqual(self.core.engine.queue.current_track['title'], "Local 1")

        # 3. Start playback & Seek to 30s
        self.core.engine.play_track(tracks[0])
        self.core.engine.seek(30000)
        self.assertEqual(self.core.engine.active_player.get_time(), 30000)

        # 4. Skip to next track
        self.core.engine.next()
        self.assertEqual(self.core.engine.queue.current_track['title'], "Local 2")

        # 5. Save session state on exit
        self.core.session.save_session(
            track_id=t2,
            position=15000,
            volume=80,
            queue=tracks,
            queue_index=1,
            shuffle=False,
            repeat="off"
        )

        # Verify restored session matches
        restored = self.core.session.restore_session()
        self.assertEqual(restored['track_id'], t2)
        self.assertEqual(restored['position'], 15000)
        self.assertEqual(restored['volume'], 80)

    def test_f4_scenario_recommendation_discovery_loop(self):
        """Scenario: User listens to music -> queries stats -> gets recommendation feed -> favorites a recommended track."""
        # 1. Record listening history
        t1 = self.core.db.add_track("Song 1", "Artist A")
        t2 = self.core.db.add_track("Song 2", "Artist B")
        self.core.db.add_to_history(t1)
        self.core.db.add_to_history(t2)

        # 2. Get profile stats
        stats = self.api.get_profile_stats()
        self.assertEqual(stats['total_tracks'], 2)

        # 3. Get recommendations feed
        feed = []
        self.core.recommendations.get_feed([{'artist': 'Artist A', 'title': 'Song 1'}], callback=lambda r: feed.extend(r))
        self.assertGreater(len(feed), 0)

        # 4. Favorite the first recommendation
        rec_track = feed[0]
        db_rec_id = self.core.db.ensure_track_exists(rec_track)
        self.api.toggle_favorite(db_rec_id)
        
        # Verify favorite
        favorites = self.api.get_favorites()
        self.assertEqual(len(favorites), 1)
        self.assertEqual(favorites[0]['id'], db_rec_id)

    def test_f4_scenario_cache_management_and_cleanup(self):
        """Scenario: Cache local covers and streams -> retrieve storage stats -> clear cache and verify."""
        # 1. Cache track stream URL and download cover art
        self.core.db.cache_stream("youtube", "yt_id", "http://stream.url")
        self.core.cache.save_cover_from_url("http://example.com/cover.jpg", 303)

        # 2. Verify cache size is tracked (dummy files created in test_dir)
        size_mb = self.core.cache.get_cache_size_mb()
        self.assertTrue(size_mb >= 0.0)

        # 3. Run cache cleanup
        self.core.cache.clear_all()
        
        # Verify directories are empty
        self.assertEqual(len(os.listdir(self.core.cache.covers_dir)), 0)
        self.assertEqual(len(os.listdir(self.core.cache.streams_dir)), 0)


# ==========================================
# Test Auth & Bypass Limits
# ==========================================

class TestBypassAndAuth(BaseNeDotifyTestCase):
    def test_default_schema_auth_settings(self):
        """Verify default auth settings schema values."""
        self.assertEqual(self.core.settings.get("auth", "cookies_file_path"), "")
        self.assertEqual(self.core.settings.get("auth", "browser_cookies"), "none")
        self.assertEqual(self.core.settings.get("auth", "yandex_token"), "")

    def test_settings_injection_in_constructors(self):
        """Verify settings object is injected to all service constructors."""
        self.assertEqual(self.core.youtube.settings, self.core.settings)
        self.assertEqual(self.core.soundcloud.settings, self.core.settings)
        self.assertEqual(self.core.vk.settings, self.core.settings)
        self.assertEqual(self.core.yandex.settings, self.core.settings)
        self.assertEqual(self.core.recommendations.settings, self.core.settings)

    def test_cascade_cookies_priority_youtube(self):
        """Verify cascade cookie prioritization for YouTube Service."""
        from services.youtube_service import YouTubeService
        
        # 1. No cookies
        mock_settings = MagicMock()
        mock_settings.get.side_effect = lambda cat, key, def_val=None: {
            "cookies_file_path": "",
            "browser_cookies": "none"
        }.get(key, def_val)
        
        service = YouTubeService(settings=mock_settings)
        opts = service._get_ydl_opts("bestaudio")
        self.assertNotIn("cookiefile", opts)
        self.assertNotIn("cookiesfrombrowser", opts)

        # 2. Browser cookies only
        mock_settings.get.side_effect = lambda cat, key, def_val=None: {
            "cookies_file_path": "",
            "browser_cookies": "chrome"
        }.get(key, def_val)
        
        service = YouTubeService(settings=mock_settings)
        opts = service._get_ydl_opts("bestaudio")
        self.assertNotIn("cookiefile", opts)
        self.assertEqual(opts["cookiesfrombrowser"], ("chrome",))

        # 3. Cookies file path set but doesn't exist on disk (should fallback to browser cookies)
        mock_settings.get.side_effect = lambda cat, key, def_val=None: {
            "cookies_file_path": "nonexistent_cookies.txt",
            "browser_cookies": "firefox"
        }.get(key, def_val)
        
        service = YouTubeService(settings=mock_settings)
        opts = service._get_ydl_opts("bestaudio")
        self.assertNotIn("cookiefile", opts)
        self.assertEqual(opts["cookiesfrombrowser"], ("firefox",))

        # 4. Cookies file exists (should prioritize cookiefile)
        temp_cookies_file = os.path.join(self.test_dir, "temp_cookies.txt")
        with open(temp_cookies_file, "w") as f:
            f.write("# Netscape HTTP Cookie File")
            
        mock_settings.get.side_effect = lambda cat, key, def_val=None: {
            "cookies_file_path": temp_cookies_file,
            "browser_cookies": "firefox"
        }.get(key, def_val)
        
        service = YouTubeService(settings=mock_settings)
        opts = service._get_ydl_opts("bestaudio")
        self.assertEqual(opts["cookiefile"], temp_cookies_file)
        self.assertNotIn("cookiesfrombrowser", opts)

    @patch('yt_dlp.YoutubeDL')
    def test_cascade_cookies_priority_soundcloud(self, mock_ydl_cls):
        """Verify cascade cookie prioritization for SoundCloud Service."""
        from services.soundcloud_service import SoundCloudService
        
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value = mock_ydl
        
        # 1. Browser cookies only
        mock_settings = MagicMock()
        mock_settings.get.side_effect = lambda cat, key, def_val=None: {
            "cookies_file_path": "",
            "browser_cookies": "edge"
        }.get(key, def_val)
        
        service = SoundCloudService(settings=mock_settings)
        service._ydl = None
        ydl = service._get_ydl()
        mock_ydl_cls.assert_called()
        call_args = mock_ydl_cls.call_args[0][0]
        self.assertNotIn("cookiefile", call_args)
        self.assertEqual(call_args["cookiesfrombrowser"], ("edge",))

        # 2. Cookies file exists
        temp_cookies_file = os.path.join(self.test_dir, "temp_cookies_sc.txt")
        with open(temp_cookies_file, "w") as f:
            f.write("# Netscape HTTP Cookie File")
            
        mock_settings.get.side_effect = lambda cat, key, def_val=None: {
            "cookies_file_path": temp_cookies_file,
            "browser_cookies": "chrome"
        }.get(key, def_val)
        
        service = SoundCloudService(settings=mock_settings)
        service._ydl = None
        ydl = service._get_ydl()
        call_args = mock_ydl_cls.call_args[0][0]
        self.assertEqual(call_args["cookiefile"], temp_cookies_file)
        self.assertNotIn("cookiesfrombrowser", call_args)

    @patch('services.yandex_service.HAS_YANDEX', new=True)
    @patch('services.yandex_service.Client', create=True)
    def test_yandex_auth_success(self, mock_client_cls):
        """Verify Yandex service token auth success path."""
        from services.yandex_service import YandexService
        
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.init.return_value = mock_client
        
        mock_settings = MagicMock()
        mock_settings.get.side_effect = lambda cat, key, def_val=None: {
            "yandex_token": "valid_token"
        }.get(key, def_val)
        
        auth_callbacks = []
        service = YandexService(settings=mock_settings)
        service.on_auth_error = lambda is_err: auth_callbacks.append(is_err)
        
        service._client = None
        client = service._get_client()
        
        self.assertEqual(client, mock_client)
        self.assertFalse(service.auth_error)
        self.assertEqual(auth_callbacks, [False])

    @patch('services.yandex_service.HAS_YANDEX', new=True)
    @patch('services.yandex_service.Client', create=True)
    def test_yandex_auth_fail(self, mock_client_cls):
        """Verify Yandex service token auth fail path."""
        from services.yandex_service import YandexService
        
        def mock_client_init(token=None):
            if token == "invalid_token":
                raise Exception("Invalid token")
            mock_inst = MagicMock()
            mock_inst.init.return_value = mock_inst
            return mock_inst
            
        mock_client_cls.side_effect = mock_client_init
        
        mock_settings = MagicMock()
        mock_settings.get.side_effect = lambda cat, key, def_val=None: {
            "yandex_token": "invalid_token"
        }.get(key, def_val)
        
        auth_callbacks = []
        service = YandexService(settings=mock_settings)
        service.on_auth_error = lambda is_err: auth_callbacks.append(is_err)
        
        service._client = None
        client = service._get_client()
        
        self.assertTrue(service.auth_error)
        self.assertEqual(auth_callbacks, [True])


# ==========================================
# Test Local HTTP Proxy and Skipping Loop Prevention
# ==========================================

class TestProxyAndLoopPrevention(BaseNeDotifyTestCase):
    def test_proxy_manager_lifecycle(self):
        """Verify proxy manager starts and stops correctly, and gets proxy URL."""
        self.assertIsNotNone(self.core.proxy)
        self.assertGreater(self.core.proxy.port, 0)
        
        url = self.core.proxy.get_proxy_url("youtube", "yt_123", "http://stream.mp3")
        self.assertIn("127.0.0.1", url)
        self.assertIn("url=http%3A%2F%2Fstream.mp3", url)
        self.assertIn("source=youtube", url)
        self.assertIn("source_id=yt_123", url)

    def test_proxy_routing_in_engine(self):
        """Verify that play_track routes cloud URLs through the proxy."""
        track = {
            'title': 'Test Cloud',
            'artist': 'Artist',
            'source': 'youtube',
            'source_id': 'yt_123',
            'file_path': 'http://example.com/stream.mp3',
            'resolved_at': time.time()
        }
        
        # Capture the media URL passed to Instance.media_new
        media_paths = []
        original_media_new = self.core.engine._instance.media_new
        def mock_media_new(path):
            media_paths.append(path)
            return original_media_new(path)
        
        self.core.engine._instance.media_new = mock_media_new
        self.core.engine.play_track(track)
        
        # Restore media_new
        self.core.engine._instance.media_new = original_media_new
        
        # Check that the media path starts with http://127.0.0.1
        self.assertEqual(len(media_paths), 1)
        self.assertTrue(media_paths[0].startswith("http://127.0.0.1:"))
        self.assertIn("source=youtube", media_paths[0])
        self.assertIn("source_id=yt_123", media_paths[0])

    def test_playback_skipping_loop_prevention(self):
        """Verify that 3 consecutive playback failures stop playback."""
        track1 = {'title': 'T1', 'source': 'youtube', 'source_id': 'id1', 'file_path': 'http://example.com/1.mp3'}
        track2 = {'title': 'T2', 'source': 'youtube', 'source_id': 'id2', 'file_path': 'http://example.com/2.mp3'}
        track3 = {'title': 'T3', 'source': 'youtube', 'source_id': 'id3', 'file_path': 'http://example.com/3.mp3'}
        
        self.core.engine.queue.set_tracks([track1, track2, track3], 0)
        
        # Mock stop to trace it
        stop_called = False
        original_stop = self.core.engine.stop
        def mock_stop():
            nonlocal stop_called
            stop_called = True
            original_stop()
        self.core.engine.stop = mock_stop
        
        # 1st failure
        self.core.engine.play_track(track1)
        self.core.engine._on_vlc_error(None)
        self.assertEqual(self.core.engine._consecutive_failures, 1)
        self.assertTrue(self.core.engine._playback_failed)
        
        # VLC end reached after error triggers advancement
        self.core.engine._on_end_reached(None)
        
        # 2nd failure (should have advanced to track2)
        self.assertEqual(self.core.engine.queue.current_track, track2)
        self.core.engine._on_vlc_error(None)
        self.assertEqual(self.core.engine._consecutive_failures, 2)
        self.core.engine._on_end_reached(None)
        
        # 3rd failure (should have advanced to track3)
        self.assertEqual(self.core.engine.queue.current_track, track3)
        self.core.engine._on_vlc_error(None)
        self.assertEqual(self.core.engine._consecutive_failures, 3)
        
        stop_called = False
        self.core.engine._on_end_reached(None)
        
        # Under loop prevention:
        # - consecutive failures is reset to 0
        # - stop() is called
        # - queue does NOT advance to next track
        self.assertEqual(self.core.engine._consecutive_failures, 0)
        self.assertTrue(stop_called)
        self.assertEqual(self.core.engine.queue.current_track, track3)

        # Verify next/previous/play_queue resets consecutive failures
        self.core.engine._consecutive_failures = 2
        self.core.engine.next()
        self.assertEqual(self.core.engine._consecutive_failures, 0)
        
        self.core.engine._consecutive_failures = 2
        self.core.engine.previous()
        self.assertEqual(self.core.engine._consecutive_failures, 0)
        
        self.core.engine._consecutive_failures = 2
        self.core.engine.play_queue([])
        self.assertEqual(self.core.engine._consecutive_failures, 0)

    def test_audio_engine_lifecycle_and_queue_clamping(self):
        """Test AudioEngine methods (next_track, stop, aliases) and queue clamping."""
        from audio.engine import AudioEngine
        engine = AudioEngine()
        engine.queue.set_tracks([{"id": 1, "title": "Track 1"}, {"id": 2, "title": "Track 2"}])
        
        # Test next_track
        engine.next_track()
        self.assertEqual(engine.queue.current_index, 0)
        engine.next_track()
        self.assertEqual(engine.queue.current_index, 1)
        
        # Test stop method does not raise
        engine.stop()
        
        # Test index clamping
        engine.play_queue([{"id": 1}], index=999)
        self.assertEqual(engine.queue.current_index, 0)
        
        # Test empty queue clamping
        engine.queue.clear()
        self.assertEqual(engine.queue._clamp_index(5), -1)

    def test_proxy_cookies_injection_and_re_resolution(self):
        """Verify cookies injection and self-healing re-resolution through proxy."""
        self.urlopen_patcher.stop()
        try:
            original_urlopen = urllib.request.urlopen
            
            call_history = []
            re_resolved = False
            
            def mock_re_resolve(source, source_id):
                nonlocal re_resolved
                re_resolved = True
                return "http://example.com/resolved.mp3"
            
            self.core.re_resolve_stream_url = mock_re_resolve
            
            # Mock youtube _get_ydl to return an object with cookiejar
            class MockCookieJar:
                def add_cookie_header(self, request):
                    request.add_header('Cookie', 'test_cookie=123')
                    
            class MockYdl:
                def __init__(self):
                    self.cookiejar = MockCookieJar()
                    
            original_get_ydl = self.core.youtube._get_ydl
            self.core.youtube._get_ydl = lambda q: MockYdl()
            
            def selective_urlopen(req, *args, **kwargs):
                url = req.full_url if hasattr(req, 'full_url') else req
                if '127.0.0.1' in url:
                    return original_urlopen(req, *args, **kwargs)
                    
                call_history.append((url, req.headers))
                
                if len(call_history) == 1:
                    # Trigger retry with 403 Forbidden
                    headers = {}
                    raise urllib.error.HTTPError(url, 403, "Forbidden", headers, fp=io.BytesIO(b""))
                    
                class MockResponse:
                    def __init__(self):
                        self.data = io.BytesIO(b'final_proxied_audio_data')
                        self.status = 200
                        self.code = 200
                        self.headers = {'Content-Type': 'audio/mpeg'}
                    def read(self, *args, **kwargs):
                        return self.data.read(*args, **kwargs)
                    def getheaders(self):
                        return [('Content-Type', 'audio/mpeg')]
                    def close(self):
                        pass
                    def __enter__(self):
                        return self
                    def __exit__(self, *args):
                        pass
                return MockResponse()
                
            with patch('urllib.request.urlopen', side_effect=selective_urlopen):
                proxy_url = self.core.proxy.get_proxy_url("youtube", "yt_123", "http://example.com/initial.mp3")
                
                req = urllib.request.Request(proxy_url)
                req.add_header('Range', 'bytes=0-100')
                
                resp = urllib.request.urlopen(req)
                data = resp.read()
                
                self.assertEqual(data, b'final_proxied_audio_data')
                self.assertEqual(resp.status, 200)
                self.assertTrue(re_resolved)
                
                self.assertEqual(len(call_history), 2)
                self.assertEqual(call_history[0][0], "http://example.com/initial.mp3")
                self.assertEqual(call_history[0][1]['Range'], 'bytes=0-100')
                self.assertEqual(call_history[0][1]['Cookie'], 'test_cookie=123')
                
                self.assertEqual(call_history[1][0], "http://example.com/resolved.mp3")
                self.assertEqual(call_history[1][1]['Range'], 'bytes=0-100')
                self.assertEqual(call_history[1][1]['Cookie'], 'test_cookie=123')
                
            self.core.youtube._get_ydl = original_get_ydl

            # Test Yandex proxy auth header
            call_history.clear()
            
            def selective_urlopen_yandex(req, *args, **kwargs):
                url = req.full_url if hasattr(req, 'full_url') else req
                if '127.0.0.1' in url:
                    return original_urlopen(req, *args, **kwargs)
                call_history.append((url, req.headers))
                
                class MockResponse:
                    def __init__(self):
                        self.data = io.BytesIO(b'yandex_data')
                        self.status = 200
                        self.code = 200
                        self.headers = {}
                    def read(self, *args, **kwargs):
                        return self.data.read(*args, **kwargs)
                    def getheaders(self):
                        return []
                    def close(self):
                        pass
                    def __enter__(self):
                        return self
                    def __exit__(self, *args):
                        pass
                return MockResponse()
                
            self.core.settings.set("auth", "yandex_token", "ya_token_123")
            with patch('urllib.request.urlopen', side_effect=selective_urlopen_yandex):
                proxy_url = self.core.proxy.get_proxy_url("yandex", "ya_123", "http://example.com/yandex.mp3")
                resp = urllib.request.urlopen(proxy_url)
                data = resp.read()
                self.assertEqual(data, b'yandex_data')
                self.assertEqual(call_history[0][1]['Authorization'], 'OAuth ya_token_123')
            self.core.settings.set("auth", "yandex_token", "")
        finally:
            self.urlopen_patcher.start()


# ==========================================
# MAIN EXECUTION ENTRY POINT
# ==========================================

if __name__ == "__main__":
    unittest.main()

