"""Shared fixtures for the NeDotify Windows test-suite.

All tests are hermetic: a throwaway SQLite file per test, stub services
instead of network providers, and ``~`` redirected for download paths.
Nothing here touches the real ``~/.nedotify`` tree or the network.
"""

import os
import sys
import threading
import types
import tempfile
import wave

import pytest

pytest_plugins = ("tests.helpers",)


@pytest.fixture(autouse=True)
def isolate_artist_catalogue_fallback(request, monkeypatch):
    if request.node.get_closest_marker('network'):
        return
    from services.catalog_service import CatalogService
    from services.itunes_gateway import CatalogueUnavailable
    def unavailable(*args, **kwargs):
        raise CatalogueUnavailable('External artist catalogue mocked in offline tests')
    monkeypatch.setattr(CatalogService, '_deezer_get', unavailable)


@pytest.fixture(autouse=True)
def isolate_additional_lyrics_sources(request, monkeypatch):
    """Legacy fixtures own only original sources; rich tests mock transport."""
    if request.node.get_closest_marker('network') or request.node.get_closest_marker('rich_lyrics'):
        return
    from services.lyrics_providers import RichLyricsProviders
    for name in ('unison', 'betterlyrics', 'simpmusic'):
        monkeypatch.setattr(RichLyricsProviders, name, lambda *args: None)


@pytest.fixture(autouse=True)
def isolate_expanded_lyrics_sources(request, monkeypatch):
    if request.node.get_closest_marker('network') or request.node.get_closest_marker('lyrics_coverage'):
        return
    from services.lyrics_fallbacks import PublicLyricsFallbacks
    for name in ('ovh', 'better_qq', 'kugou', 'recover_upload'):
        monkeypatch.setattr(PublicLyricsFallbacks, name, lambda *args: None)

# Isolate collection-time imports as well as test bodies. Fixtures run after
# module imports, which is too late for modules that cache a default profile.
_PROFILE_ENV_KEYS = ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA")
if not hasattr(sys, "_nedotify_test_profile"):
    sys._nedotify_test_profile = (
        tempfile.TemporaryDirectory(prefix="nedotify-pytest-"),
        {key: os.environ.get(key) for key in _PROFILE_ENV_KEYS},
        os.path.realpath(os.path.join(os.path.expanduser("~"), ".nedotify")),
    )
_TEST_PROFILE, _ORIGINAL_PROFILE_ENV, _REAL_PROFILE_DIR = sys._nedotify_test_profile
for _profile_key in _PROFILE_ENV_KEYS:
    os.environ[_profile_key] = _TEST_PROFILE.name


def pytest_unconfigure(config):
    for key, value in _ORIGINAL_PROFILE_ENV.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    _TEST_PROFILE.cleanup()

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.api import AppApi
from core.database import DatabaseManager
from core.downloader import DownloadManager
from audio.engine import AudioEngine


class SettingsStub:
    """Minimal dict-backed stand-in for SettingsManager."""

    def __init__(self):
        self._d = {}

    def get(self, category, key, default=None):
        return self._d.get((category, key), default)

    def set(self, category, key, value):
        self._d[(category, key)] = value

    def get_category(self, category):
        return {k: v for (c, k), v in self._d.items() if c == category}

    def categories(self):
        return tuple({category for category, _key in self._d})


class ServiceStub:
    """Fake audio provider: writes a local file instead of downloading.

    The payload is deliberately above _MIN_AUDIO_BYTES (4 KiB): the real
    download path rejects anything smaller as a truncated file, and a stub that
    wrote a 19-byte file made the integrity gate fire on every test.
    """

    def __init__(self):
        self.calls = []
        self.fail = False
        self.n = 0

    def download_audio_sync(self, source_id, download_dir):
        self.calls.append((source_id, download_dir))
        if self.fail:
            raise RuntimeError("stub provider failure")
        self.n += 1
        os.makedirs(download_dir, exist_ok=True)
        fp = os.path.join(download_dir, "stub_%d.mp3" % self.n)
        with wave.open(fp, "wb") as audio:
            audio.setparams((1, 2, 22050, 0, 'NONE', 'not compressed'))
            audio.writeframes(b"\x00" * 8192)
        return fp


@pytest.fixture
def tmp_db(tmp_path):
    db = DatabaseManager(str(tmp_path / "test.db"))
    yield db
    try:
        db.close()
    except Exception:
        pass


@pytest.fixture
def settings_stub():
    return SettingsStub()


@pytest.fixture
def youtube_stub():
    return ServiceStub()


@pytest.fixture
def core_ns(tmp_db, settings_stub, youtube_stub):
    """AppCore-shaped namespace with the real queue engine and stub providers."""
    ns = types.SimpleNamespace(
        db=tmp_db,
        settings=settings_stub,
        youtube=youtube_stub,
        soundcloud=youtube_stub,
        cache=None,
    )
    ns.engine = AudioEngine()
    ns.engine.app_core = ns
    ns._service_lock = threading.RLock()
    ns._shutting_down = threading.Event()
    ns._resolution_timers = set()
    ns._resolve_threads = set()
    return ns


@pytest.fixture
def api(core_ns):
    app_api = AppApi(core_ns)
    yield app_api
    app_api.cleanup()


@pytest.fixture
def emitted(api, monkeypatch):
    """Capture bridge events emitted via api._emit."""
    events = []

    def _capture(event_name, data=None):
        events.append((event_name, data))

    monkeypatch.setattr(api, "_emit", _capture)
    return events


@pytest.fixture
def downloader(core_ns):
    """Real DownloadManager with its background processor halted.

    Workers are driven synchronously via ``_download_worker`` in tests,
    so there is no race with the processor thread.
    """
    dm = DownloadManager(core_ns)
    dm._running = False
    dm._queue_event.set()
    yield dm
    try:
        dm.stop()
    except Exception:
        pass


# Home-path spellings that must be redirected. ``os.sep`` alone was not enough:
# every production call site spells the profile as the literal "~/.nedotify"
# (forward slash, hard-coded in core/*.py and services/*.py), while native
# Windows callers use "~\\...". Keying only on os.sep == "\\" therefore let
# "~/.nedotify" escape the sandbox and hit the real user profile.
_HOME_SEP_CHARS = tuple(c for c in {"/", os.sep, os.altsep} if c)
# The separator that is NOT native to this OS; only rewritten when it exists.
_FOREIGN_SEP = "/" if os.sep != "/" else None


def home_expander(home, original=None):
    """Build a drop-in ``os.path.expanduser`` that maps ``~`` onto *home*.

    Accepts ``~``, ``~/x``, ``~\\x`` and mixed forms; returns a path joined with
    the OS-native separator. Anything else (``~user``, relative paths, non-str)
    is delegated to the original implementation.
    """
    orig = original or os.path.expanduser
    base = str(home)

    def _patched(path):
        if not isinstance(path, str) or not path.startswith("~"):
            return orig(path)
        rest = path[1:]
        if rest and rest[0] not in _HOME_SEP_CHARS:
            # "~someone-else" is a real home on POSIX; leave it to nt/posixpath.
            return orig(path)
        while rest and rest[0] in _HOME_SEP_CHARS:
            rest = rest[1:]
        if _FOREIGN_SEP:
            # Re-join natively so the value behaves like any other Windows path
            # (on POSIX "/" is already native, and "\" is a legal filename char).
            rest = rest.replace(_FOREIGN_SEP, os.sep)
        return base + (os.sep + rest if rest else "")

    return _patched


@pytest.fixture(autouse=True)
def redirect_home(tmp_path, monkeypatch):
    """Redirect ``~`` to a throwaway dir (keeps ~/.nedotify clean)."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("APPDATA", str(home))
    monkeypatch.setenv("LOCALAPPDATA", str(home))
    original = os.path.expanduser
    def expand(path):
        # Tests may override HOME within their own temporary directory.
        selected = os.environ.get('USERPROFILE' if os.name == 'nt' else 'HOME', str(home))
        return home_expander(selected, original)(path)
    monkeypatch.setattr(os.path, "expanduser", expand)
    return home


@pytest.fixture(autouse=True)
def isolated_process_caches(monkeypatch):
    from services.base_service import BaseMusicService, _SharedExecutor
    from services.soundcloud_service import SoundCloudService
    from services.taste_profile import _profile_cache, _profile_cache_lock
    import utils.url_safety as url_safety

    classes, pending = [], [BaseMusicService]
    while pending:
        cls = pending.pop()
        if cls in classes:
            continue
        classes.append(cls)
        pending.extend(cls.__subclasses__())
    with BaseMusicService._cache_lock:
        for cls in classes:
            monkeypatch.setattr(cls, '_search_cache', {})
        monkeypatch.setattr(BaseMusicService, '_stream_cache', {})
        original_executor = BaseMusicService._executor
        isolated_executor = _SharedExecutor(
            max_workers=getattr(original_executor, '_max_workers', 8),
            thread_name_prefix=getattr(original_executor, '_thread_name_prefix', 'test-shared'),
        )
        monkeypatch.setattr(BaseMusicService, '_executor', isolated_executor)
        isolated_playback_executor = _SharedExecutor(max_workers=4, thread_name_prefix='test-playback')
        monkeypatch.setattr(BaseMusicService, '_playback_executor', isolated_playback_executor)

    ttl_state = {}
    with BaseMusicService._cache_lock:
        for name in ('_shared_unavailable', '_shared_verified', '_shared_manifests'):
            cache = getattr(SoundCloudService, name, None)
            if cache is not None:
                ttl_state[name] = dict(cache._data)
                cache._data.clear()

    with _profile_cache_lock:
        profile_state = dict(_profile_cache)
        _profile_cache.clear()
    with url_safety._DNS_LOCK:
        dns_state = dict(url_safety._DNS_CACHE)
        url_safety._DNS_CACHE.clear()

    try:
        yield
    finally:
        isolated_executor.shutdown(wait=True, cancel_futures=True)
        isolated_playback_executor.shutdown(wait=True, cancel_futures=True)
        with BaseMusicService._cache_lock:
            for name, contents in ttl_state.items():
                getattr(SoundCloudService, name)._data.clear()
                getattr(SoundCloudService, name)._data.update(contents)
        with _profile_cache_lock:
            _profile_cache.clear()
            _profile_cache.update(profile_state)
        with url_safety._DNS_LOCK:
            url_safety._DNS_CACHE.clear()
            url_safety._DNS_CACHE.update(dns_state)


@pytest.fixture(autouse=True)
def offline_recommendation_catalogue(request, monkeypatch):
    """Only the new optional default factory is offline in non-network tests.

    Explicit catalogue fixtures still exercise the real discovery adapter;
    unrelated Deezer service tests and its HTTP transport remain untouched.
    """
    if request.node.get_closest_marker('network'):
        return
    import services.recommendation_discovery as discovery
    class EmptyCatalogue:
        def _get(self, *args, **kwargs):
            return {'data': []}
    monkeypatch.setattr(discovery, 'DeezerService', lambda *args, **kwargs: EmptyCatalogue())
