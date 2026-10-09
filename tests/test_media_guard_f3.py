"""SSRF guards on the media sinks (utils/url_safety.py) and their receivers.

Audit F3: a raw ``http(s)`` ``source_id`` used to travel unchecked from a track
row into yt-dlp / SoundCloud, so a poisoned row could make the app fetch
``http://127.0.0.1:...`` or the cloud metadata endpoint. Every receiver now
checks the URL first.

Hermetic: the DNS-dependent branches install a fake ``socket.getaddrinfo``,
and the resolver tests use in-process service stubs.
"""

import socket
import threading
import types
import urllib.request

import pytest

from audio.queue import PlaybackQueue
from services.youtube_service import (
    YouTubeService,
    _is_allowed_youtube_target,
)
from utils.url_safety import is_safe_media_url


# --------------------------------------------------------------------------- #
# utils/url_safety.py
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8080/admin",
    "https://127.0.0.1/admin",
    "http://[::1]:9200/_cluster/health",
    "http://10.0.0.1/",
    "http://192.168.1.1/",
    "http://172.16.0.5/",
    "http://169.254.169.254/latest/meta-data/",   # cloud metadata
    "http://0.0.0.0/",
    "http://224.0.0.1/",                          # multicast
    "http://240.0.0.1/",                          # reserved
])
def test_private_and_special_ip_literals_are_rejected(url):
    """Numeric literals resolve locally, so this needs no DNS and no network."""
    assert is_safe_media_url(url) is False


@pytest.mark.parametrize("url", [
    None, "", "   ", "not a url", "ftp://example.com/a.mp3",
    "file:///etc/passwd", "http://", "https:///", "//example.com/a.mp3",
    123,
])
def test_malformed_and_non_http_urls_are_rejected(url):
    assert is_safe_media_url(url) is False


def test_public_ip_literal_is_allowed():
    assert is_safe_media_url("https://93.184.216.34/track.mp3") is True


def test_dns_failure_fails_closed(monkeypatch):
    def _boom(*a, **kw):
        raise socket.gaierror("name resolution failed")

    monkeypatch.setattr(socket, "getaddrinfo", _boom)
    assert is_safe_media_url("https://cdn.example.com/a.mp3") is False


def test_hostname_resolving_to_a_private_address_is_rejected(monkeypatch):
    """The public-looking name must not launder an internal address."""
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))],
    )
    assert is_safe_media_url("https://cdn.example.com/a.mp3") is False


def test_hostname_with_one_private_answer_is_rejected(monkeypatch):
    """Every answer must be public: one private A record poisons the whole host."""
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 0)),
    ])
    assert is_safe_media_url("https://cdn.example.com/a.mp3") is False


def test_public_hostname_is_allowed(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )
    assert is_safe_media_url("https://cdn.example.com/a.mp3") is True


# --------------------------------------------------------------------------- #
# services/youtube_service.py - target allowlist
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("target", [
    "dQw4w9WgXcQ",                                  # canonical 11-char id
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtube.com/watch?v=dQw4w9WgXcQ",
    "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ",
])
def test_allowed_youtube_targets(target):
    assert _is_allowed_youtube_target(target) is True


@pytest.mark.parametrize("target", [
    "http://127.0.0.1:8080/",
    "http://169.254.169.254/latest/meta-data/",
    "https://evil.example.com/watch?v=dQw4w9WgXcQ",
    "https://youtube.com.evil.example/watch?v=x",
    "https://notyoutube.com/watch?v=x",
    "file:///etc/passwd",
    "dQw4w9WgXc",        # 10 chars
    "dQw4w9WgXcQQ",      # 12 chars
    "some song title",
    "",
    None,
])
def test_rejected_youtube_targets(target):
    assert _is_allowed_youtube_target(target) is False


def test_get_stream_url_refuses_a_non_youtube_target():
    """The allowlist runs before the cache and before extract_info."""
    svc = YouTubeService()
    calls = []
    svc._extract_info_safe = lambda *a, **kw: calls.append(a) or {}

    svc.get_stream_url("http://169.254.169.254/latest/meta-data/",
                       callback=lambda *a: calls.append("cb"),
                       error_callback=lambda e: calls.append(e))

    assert calls and all("169.254" not in str(c) for c in calls if c != "cb")
    assert "cb" not in calls


# --------------------------------------------------------------------------- #
# audio/engine.py - the cascade must not resolve an internal URL
# --------------------------------------------------------------------------- #

class _Service:
    """Records every call; never returns a stream."""

    def __init__(self, name):
        self.name = name
        self.calls = []

    def get_stream_url(self, target, callback=None, error_callback=None, quality="high", **kw):
        self.calls.append(("get_stream_url", target))
        if error_callback:
            error_callback("no stream")
        return None

    def search(self, query, max_results=20, callback=None, error_callback=None):
        self.calls.append(("search", query))
        if error_callback:
            error_callback("nothing found")
        return None


class _Db:
    def update_track(self, *a, **kw):
        raise AssertionError("no track should be resolved")

    def cache_stream(self, *a, **kw):
        pass


@pytest.fixture
def _no_network(monkeypatch):
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("network disabled in tests")),
    )


def test_youtube_source_id_pointing_at_loopback_is_not_resolved(_no_network):
    from audio.engine import AudioEngine

    yt, sc, yx = _Service("yt"), _Service("sc"), _Service("yx")
    engine = AudioEngine()
    engine.app_core = types.SimpleNamespace(db=_Db(), youtube=yt, soundcloud=sc, yandex=yx)

    engine._resolve_via_network({"id": 1, "source": "youtube", "title": "Song",
                                 "artist": "Artist",
                                 "source_id": "http://127.0.0.1:9200/_search"})

    assert [c for c in yt.calls if c[0] == "get_stream_url"] == [], \
        "an internal URL must never reach the yt-dlp extractor"


def test_soundcloud_target_pointing_at_loopback_is_not_resolved(_no_network):
    from audio.engine import AudioEngine

    sc = _Service("sc")
    engine = AudioEngine()
    engine.app_core = types.SimpleNamespace(db=_Db(), soundcloud=sc)

    engine._resolve_via_network({"id": 2, "source": "soundcloud", "title": "Song",
                                 "artist": "Artist",
                                 "source_id": "http://169.254.169.254/latest/meta-data/"})

    assert [c for c in sc.calls if c[0] == "get_stream_url"] == [], \
        "an internal URL must never reach the SoundCloud extractor"


# --------------------------------------------------------------------------- #
# audio/queue.py - the history stack stores positions, so it must be rebased
# --------------------------------------------------------------------------- #

def _tracks(n=5):
    return [{"id": i, "title": "t%d" % i, "artist": "a", "source": "youtube",
             "source_id": "vid%d" % i} for i in range(n)]


def test_previous_track_after_removing_a_history_entry():
    """Removing a track must drop its index and shift the later ones down."""
    q = PlaybackQueue()
    q.set_tracks(_tracks(5), 0)
    q.next_track()
    q.next_track()
    q.next_track()            # history == [0, 1, 2], current index == 3

    q.remove_track(1)         # the queue entry history entry 1 pointed at
    assert q.current_track["id"] == 3, "the playing track survives the removal"
    assert q.current_index == 2

    seen = []
    while q._history_stack:
        seen.append(q.previous_track()["id"])
    # History 1 is gone (its track was removed) and the old 2 moved down to 1.
    assert seen == [2, 0]
    assert 0 <= q.current_index < q.count


def test_previous_track_skips_every_out_of_range_history_index():
    """A history left over from a shrinking queue must not index out of bounds."""
    q = PlaybackQueue()
    q.set_tracks(_tracks(5), 0)
    q.next_track()
    q.next_track()
    q._history_stack.extend([9, 7, -3])

    # The three impossible indices are dropped, the top valid one wins.
    assert q.previous_track()["id"] == 1
    assert q._history_stack == [0]
    assert q.previous_track()["id"] == 0
    assert q._history_stack == []


def test_previous_track_on_a_shrunk_queue_never_raises():
    q = PlaybackQueue()
    q.set_tracks(_tracks(3), 2)
    q._history_stack = [2, 1]

    for _ in range(5):
        assert q.previous_track() is None or 0 <= q.current_index < q.count


def test_toggling_shuffle_clears_history():
    q = PlaybackQueue()
    q.set_tracks(_tracks(5), 0)
    q.next_track()
    q.next_track()
    assert q._history_stack

    q.shuffle = True
    assert q._history_stack == []


def test_moving_a_track_clears_history():
    q = PlaybackQueue()
    q.set_tracks(_tracks(5), 0)
    q.next_track()
    q.next_track()
    assert q._history_stack

    q.move_track(0, 4)
    assert q._history_stack == []


def test_set_tracks_clamps_a_negative_start_index():
    q = PlaybackQueue()
    q.set_tracks(_tracks(3), -5)
    assert q.current_index == 0
    assert q.current_track["id"] == 0


# --------------------------------------------------------------------------- #
# services/youtube_service.py - info=None must still notify the caller
# --------------------------------------------------------------------------- #

def test_none_info_reports_an_error_instead_of_hanging():
    """A None payload used to fall out of _extract() with no callback at all,
    leaving the engine blocked on its event until the timeout expired."""
    svc = YouTubeService()
    svc._extract_info_safe = lambda *a, **kw: None
    done = threading.Event()
    errors = []

    svc.get_stream_url("dQw4w9WgXcQ",
                       callback=lambda *a: done.set(),
                       error_callback=lambda e: (errors.append(e), done.set()))
    try:
        assert done.wait(5), "neither callback fired"
    finally:
        svc._executor.shutdown(wait=True)

    assert errors and "Не удалось извлечь аудио поток" in errors[0]