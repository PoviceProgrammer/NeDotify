"""Shared fixtures and deterministic harnesses used across test modules."""

import http.client
import io
import os
import socketserver
import threading
import types
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from tests.jsdom import run_node, source

from core.proxy import StreamProxyHandler, ThreadingHTTPServer
from services.base_service import BaseMusicService
from services.recommendation_service import RecommendationService
from services.taste_profile import UserTasteProfile


class DeferredExecutor:
    """Executor whose queued calls run only when a test invokes them."""

    def __init__(self):
        self.tasks = []

    def submit(self, fn, *args, **kwargs):
        self.tasks.append(lambda: fn(*args, **kwargs))


PROXY_TOKEN = "test-proxy-token"


def qs(**kwargs):
    """Percent-encoded query string, matching frontend encodeURIComponent."""
    return "&".join(
        "{}={}".format(key, urllib.parse.quote(str(value), safe=""))
        for key, value in kwargs.items() if value is not None
    )


def write_bytes(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)
    return path


class RecordingEngine:
    def __init__(self, result=None):
        self.calls = []
        self.result = result

    def resolve_stream_url(self, track):
        self.calls.append(track)
        return self.result


class ProxyResponse:
    def __init__(self, raw):
        self.status = raw.status
        self.reason = raw.reason
        self.headers = raw.headers
        self.body = raw.read()

    def header(self, name, default=None):
        return self.headers.get(name, default)


class ProxyClient:
    def __init__(self, server, token):
        self.server = server
        self.port = server.server_port
        self.token = token

    def url(self, path, **params):
        params.setdefault("k", self.token)
        query = qs(**params)
        return "{}?{}".format(path, query) if query else path

    def request(self, path, method="GET", headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, headers=dict(headers or {}))
            raw = conn.getresponse()
            return ProxyResponse(raw)
        finally:
            conn.close()

    def get(self, path, headers=None):
        return self.request(path, "GET", headers)

    def head(self, path, headers=None):
        return self.request(path, "HEAD", headers)


@pytest.fixture
def nedotify_home(tmp_path, monkeypatch):
    """Redirect literal `~/.nedotify` paths and create managed subfolders."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    original = os.path.expanduser

    def expand(path):
        if path == "~" or path[:2] in ("~" + os.sep, "~/", "~\\"):
            return str(home) + path[1:]
        return original(path)

    monkeypatch.setattr(os.path, "expanduser", expand)
    base = os.path.join(str(home), ".nedotify")
    for subdir in ("covers", "avatars", "streams", "temp", "downloads"):
        os.makedirs(os.path.join(base, subdir), exist_ok=True)
    return base


@pytest.fixture
def app_core(tmp_db, nedotify_home):
    return SimpleNamespace(
        db=tmp_db, settings=None, youtube=None, soundcloud=None,
        cache=SimpleNamespace(
            _streams_dir=os.path.join(nedotify_home, "streams"),
            _temp_dir=os.path.join(nedotify_home, "temp"),
        ),
        engine=RecordingEngine(),
    )


@pytest.fixture
def proxy_factory(app_core):
    servers = []

    def make(token=PROXY_TOKEN):
        server = ThreadingHTTPServer(("127.0.0.1", 0), StreamProxyHandler, app_core, token)
        thread = threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        )
        thread.start()
        servers.append(server)
        return ProxyClient(server, token)

    yield make
    for server in servers:
        server.shutdown()
        try:
            server.server_close()
        except AttributeError:
            pass


@pytest.fixture
def proxy(proxy_factory):
    return proxy_factory()


def offline_handler(app_core, headers=None, token=PROXY_TOKEN):
    handler = StreamProxyHandler.__new__(StreamProxyHandler)
    handler.server = SimpleNamespace(app_core=app_core, auth_token=token)
    handler.headers = dict(headers or {})
    handler.wfile = io.BytesIO()
    handler.request_version = "HTTP/1.1"
    handler.requestline = "GET / HTTP/1.1"
    handler._headers_buffer = []
    return handler


def track(sid, title, artist="Artist", source="youtube", **kwargs):
    return dict(source=source, source_id=sid, title=title, artist=artist, duration=180, **kwargs)


@pytest.fixture
def recommendations(monkeypatch):
    import services.recommendation_service as module

    monkeypatch.delenv("LASTFM_USERNAME", raising=False)

    def unexpected(*args, **kwargs):
        raise AssertionError("Last.fm must not be needed without a configured key")

    lastfm = SimpleNamespace(
        _resolve_api_keys=lambda: [],
        artist=SimpleNamespace(getTopTracks=unexpected),
        track=SimpleNamespace(getSimilar=unexpected),
    )
    monkeypatch.setattr(module, "LastFMService", lambda **kwargs: lastfm)
    with BaseMusicService._cache_lock:
        monkeypatch.setattr(BaseMusicService, "_search_cache", {})
    executor = ThreadPoolExecutor(max_workers=4)
    monkeypatch.setattr(RecommendationService, "_executor", executor)
    yt = SimpleNamespace(get_related_tracks_sync=lambda *a, **k: [], search_sync=lambda *a, **k: [])
    sc = SimpleNamespace(get_related_tracks_sync=lambda *a, **k: [])
    service = RecommendationService(youtube_service=yt, soundcloud_service=sc)
    yield service
    executor.shutdown(wait=True, cancel_futures=True)
    service._candidate_executor.shutdown(wait=True, cancel_futures=True)


@pytest.fixture
def providers(monkeypatch):
    import services.youtube_service as yt
    import services.soundcloud_service as sc
    import services.spotify_service as sp

    for module in (yt, sc, sp):
        monkeypatch.setattr(module, "ThreadPoolExecutor", lambda **kw: DeferredExecutor())
    monkeypatch.setattr(yt, "HAS_YTMUSIC", False)
    monkeypatch.setattr(sc.SoundCloudService, "_get_client_id", lambda self: "cid")
    youtube, soundcloud, spotify = yt.YouTubeService(), sc.SoundCloudService(), sp.SpotifyService()
    monkeypatch.setattr(yt, "HAS_YTMUSIC", True)
    youtube._ytmusic = SimpleNamespace(search=lambda *a, **k: [
        {"resultType": "song", "videoId": "dQw4w9WgXcQ", "title": "Track"},
    ])
    soundcloud.settings = SimpleNamespace(get=lambda category, key, default=None: default)
    soundcloud._ydl_tls = threading.local()
    soundcloud._get_ydl_search = lambda: SimpleNamespace(extract_info=lambda *a, **k: {
        "entries": [{"id": "123", "title": "Track"}],
    })
    soundcloud._api_get = lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: {"collection": []})
    monkeypatch.setattr(sp, "_cached_spotify_search", lambda *a, **k: (
        ("spotify_1", "Track", "Artist", "Album", 180, "", "spotify", "ytsearch1: Artist - Track", ""),
    ))
    with BaseMusicService._cache_lock:
        monkeypatch.setattr(BaseMusicService, "_search_cache", {})
        monkeypatch.setattr(BaseMusicService, "_stream_cache", {})
    for service in (youtube, soundcloud, spotify):
        service._executor.tasks.clear()
        service._search_cache.clear()
    return youtube, soundcloud, spotify


def fetch(method, *args, **kwargs):
    event, result = threading.Event(), {}
    method(
        *args,
        callback=lambda data: (result.update(data=data), event.set()),
        error_callback=lambda error: (result.update(error=error), event.set()),
        **kwargs,
    )
    assert event.wait(3), "Recommendation callback did not complete"
    assert "error" not in result, result
    return result["data"]


HARNESS = r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const frames = new Map(), documentEvents = new Map(), elements = new Map();
let nextFrame = 0, textWrites = 0, attributeWrites = 0, transforms = 0, prefetches = 0;
const classes = new Set();
const classList = {contains: value => classes.has(value), add() {}, remove() {}, toggle() {}};
for (const prefix of ['pb', 'pp', 'mp']) {
    const attributes = new Map();
    let text = '';
    elements.set(prefix + '-time-current', {
        get textContent() {return text}, set textContent(value) {text = value; textWrites++},
    });
    elements.set(prefix + '-progress-track', {
        style: {setProperty() {}},
        getAttribute: name => attributes.get(name),
        setAttribute(name, value) {attributes.set(name, value); attributeWrites++},
    });
    elements.set(prefix + '-progress-fill', {style: {
        set transform(value) {transforms++},
    }});
}
class AudioStub {
    constructor() {this.duration = 180; this.currentTime = 1; this.paused = false; this.events = new Map()}
    addEventListener(name, callback) {this.events.set(name, callback)}
    removeAttribute() {} load() {} pause() {} play() {return Promise.resolve()}
}
const context = vm.createContext({console, Promise, Date, URLSearchParams,
    Audio: AudioStub, navigator: {},
    playbackState: {track: null, status: 'stopped', durationMs: 0, positionMs: 0, lastAnimTimestamp: 0},
    localStorage: {getItem() {return null}},
    window: {location: {href: 'http://localhost/'}, addEventListener() {}, dispatchEvent() {},
        pywebview: {api: {report_position() {}, get_next_track() {prefetches++; return Promise.resolve(null)}}}},
    document: {getElementById: name => elements.get(name) || null, querySelector() {return null},
        querySelectorAll() {return []}, hidden: false, readyState: 'loading',
        addEventListener(name, callback) {
            if (!documentEvents.has(name)) documentEvents.set(name, []);
            documentEvents.get(name).push(callback);
        }, dispatchEvent() {},
        documentElement: {classList, getAttribute() {return null}, style: {setProperty() {}, removeProperty() {}}}, body: {classList}},
    requestAnimationFrame(callback) {const frame = ++nextFrame; frames.set(frame, callback); return frame},
    cancelAnimationFrame(frame) {frames.delete(frame)}, performance: {now() {return 10000}},
    setTimeout() {return 1}, clearTimeout() {},
    formatTime: seconds => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`,
    renderIcons() {}, registerCanvasDprListener() {},
    CustomEvent: class {constructor(name, options) {this.detail = options.detail}},
});
vm.runInContext(SOURCE.replace(/^import .*;\r?$/gm, '').replace(/\bexport\s+/g, '') + `
globalThis.subject = {advanceFrame: animateProgress, onStateChanged, setUiFps,
    audio: activeAudio, setPlaying() {playbackState.status = 'playing'; playbackState.durationMs = 180000},
    get frame() {return animFrameId}};`, context);
const subject = context.subject;
subject.setPlaying();
function visibilityChanged() {for (const callback of documentEvents.get('visibilitychange')) callback()}
"""


def player_test(script):
    run_node((HARNESS + script).replace("SOURCE", source("player.js")))
