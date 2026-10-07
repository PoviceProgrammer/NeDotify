"""AudioEngine._notify_track_changed + queue control surface (audio/engine.py).

Nothing here touches the network or the real disk: every stub is in-process,
callbacks fire synchronously, and the only files created live under tmp_path.

_notify_track_changed is the only place that decides what ``stream_url`` the
frontend receives, so the exact URL shape is asserted string-by-string: the
frontend and core/proxy.py parse it, and a silent change breaks playback.
"""

import os
import urllib.parse

import pytest

from audio.engine import AudioEngine


class _FakeProxy:
    """Stands in for core.proxy.LocalProxyManager (port + '&k=<token>' fragment)."""

    def __init__(self, port=8099, token="t0ken"):
        self.port = port
        self.token = token

    def auth_query(self):
        return f"&k={self.token}" if self.token else ""


def _engine(port=8099, token="t0ken"):
    """Headless engine whose _on_track_changed records every emitted track."""
    emitted = []
    engine = AudioEngine()
    if port is not None:
        engine.proxy = _FakeProxy(port, token)
    engine._on_track_changed = emitted.append
    return engine, emitted


def _local_file(tmp_path, name="track.mp3"):
    fp = tmp_path / name
    fp.write_bytes(b"ID3\x00\x01stub-audio")
    return str(fp)


# --------------------------------------------------------------------------- #
# stream_url routing: existing local file -> /api/stream?url=<fs path>
# --------------------------------------------------------------------------- #

def test_existing_local_file_is_served_through_the_stream_route(tmp_path):
    engine, emitted = _engine(port=8099)
    fp = _local_file(tmp_path)

    engine.play_track({
        "id": 3, "source": "local", "source_id": "x y", "title": "T & T",
        "artist": "A", "file_path": fp,
    })

    assert len(emitted) == 1
    q = urllib.parse.quote
    assert emitted[0]["stream_url"] == (
        "http://127.0.0.1:8099/api/stream?url=" + q(fp)
        + "&track_id=3&source=local&source_id=" + q("x y")
        + "&title=" + q("T & T") + "&artist=" + q("A")
        + "&k=t0ken"
    )


def test_whole_file_path_without_source_defaults_to_local_source(tmp_path):
    """``src = track.get("source") or "local"`` for the cached-file route."""
    engine, emitted = _engine()
    fp = _local_file(tmp_path, "no-source.mp3")

    engine.play_track({"id": 7, "title": "T", "artist": "A", "file_path": fp})

    assert "&source=local" in emitted[0]["stream_url"]
    assert "&track_id=7" in emitted[0]["stream_url"]


def test_local_source_uses_url_when_file_path_is_absent(tmp_path):
    """``fp = track.get("file_path")`` then ``track["url"]`` for local tracks."""
    engine, emitted = _engine()
    url = _local_file(tmp_path, "by-url.mp3")

    engine.play_track({"id": 1, "source": "local", "url": url, "title": "T", "artist": "A"})

    assert emitted[0]["stream_url"].startswith(
        "http://127.0.0.1:8099/api/stream?url=" + urllib.parse.quote(url)
    )


def test_remote_url_on_an_unknown_domain_uses_the_root_route():
    """Unlisted host -> the '/' endpoint with the raw url encoded in ?url=."""
    engine, emitted = _engine()
    q = urllib.parse.quote

    engine.play_track({
        "id": 11, "source": "soundcloud", "source_id": "s cid", "title": "Ti",
        "artist": "Ar", "file_path": "https://cdn.example.com/a b.mp3",
    })

    assert emitted[0]["stream_url"] == (
        "http://127.0.0.1:8099/?url=" + q("https://cdn.example.com/a b.mp3")
        + "&source=soundcloud&source_id=" + q("s cid")
        + "&title=" + q("Ti") + "&artist=" + q("Ar")
        + "&k=t0ken"
    ), "the raw CDN URL must reach the SSRF-guarded '/' endpoint, not /api/stream"


@pytest.mark.parametrize("domain", [
    "youtube.com", "youtu.be", "soundcloud.com", "music.yandex.ru",
])
def test_remote_url_on_a_listed_domain_uses_the_stream_route(domain):
    """Listed hosts are resolved by the proxy itself -> /api/stream?track_id=."""
    engine, emitted = _engine()

    engine.play_track({
        "id": 12, "source": "youtube", "source_id": "abc", "title": "Ti",
        "artist": "Ar", "file_path": f"https://{domain}/watch?v=abc",
    })

    url = emitted[0]["stream_url"]
    q = urllib.parse.quote
    assert url == (
        "http://127.0.0.1:8099/api/stream?track_id=12&source=youtube&source_id=" + q("abc")
        + "&title=" + q("Ti") + "&artist=" + q("Ar")
        + "&k=t0ken"
    )
    assert "?url=" not in url, "a listed domain must not be re-fetched by url="


def test_listed_domain_route_defaults_source_to_youtube():
    engine, emitted = _engine()

    engine.play_track({
        "id": 0, "source_id": "abc", "title": "Ti", "artist": "Ar",
        "file_path": "https://youtu.be/abc",
    })

    assert "&source=youtube" in emitted[0]["stream_url"]
    assert "track_id=0&" in emitted[0]["stream_url"]


def test_track_metadata_is_percent_encoded(tmp_path):
    engine, emitted = _engine()
    fp = _local_file(tmp_path)

    engine.play_track({
        "id": 2, "source": "local", "file_path": fp, "title": "Кино & Другое",
        "artist": "Артист #1", "source_id": "id/with?chars",
    })

    url = emitted[0]["stream_url"]
    assert "title=%D0%9A%D0%B8%D0%BD%D0%BE%20%26%20%D0%94%D1%80%D1%83%D0%B3%D0%BE%D0%B5" in url
    assert "artist=%D0%90%D1%80%D1%82%D0%B8%D1%81%D1%82%20%231" in url
    # quote() keeps '/' unescaped (its default safe set) but must escape '?'.
    assert "source_id=id/with%3Fchars" in url
    assert " " not in url, "an unencoded space truncates the query string"


def test_auth_query_fragment_is_appended_when_the_proxy_has_a_token(tmp_path):
    engine, emitted = _engine(token="s3cret")
    fp = _local_file(tmp_path)

    engine.play_track({"id": 1, "source": "local", "file_path": fp})
    assert emitted[0]["stream_url"].endswith("&k=s3cret")


def test_no_auth_fragment_when_the_proxy_has_no_token(tmp_path):
    engine, emitted = _engine(token=None)
    fp = _local_file(tmp_path)

    engine.play_track({"id": 1, "source": "local", "file_path": fp})
    assert emitted[0]["stream_url"].endswith("&artist=A") or "&artist=" in emitted[0]["stream_url"]
    assert "&k=" not in emitted[0]["stream_url"]


# --------------------------------------------------------------------------- #
# stream_url routing: the "do not hang the player" branches
# --------------------------------------------------------------------------- #

def test_missing_file_leaves_stream_url_unset(tmp_path):
    """An unresolved/absent file must NOT be turned into a proxy URL:
    the frontend then shows a loading state instead of a 404 loop."""
    engine, emitted = _engine()
    missing = str(tmp_path / "gone.mp3")
    assert not os.path.exists(missing)

    engine.play_track({"id": 5, "source": "local", "file_path": missing,
                       "title": "T", "artist": "A"})

    assert not emitted[0].get("stream_url")


def test_no_proxy_leaves_stream_url_unset(tmp_path):
    """engine.proxy is None before AppCore starts the proxy (core/app.py:128)."""
    engine, emitted = _engine(port=None)
    fp = _local_file(tmp_path)

    engine.play_track({"id": 5, "source": "local", "file_path": fp,
                       "title": "T", "artist": "A"})

    assert not emitted[0].get("stream_url")
    assert emitted[0]["title"] == "T", "the track must still be published"


def test_proxy_without_a_port_leaves_stream_url_unset(tmp_path):
    """A stopped LocalProxyManager keeps port = 0 (core/proxy.py:1196)."""
    engine, emitted = _engine(port=0)
    fp = _local_file(tmp_path)

    engine.play_track({"id": 5, "source": "local", "file_path": fp})

    assert not emitted[0].get("stream_url")


def test_existing_stream_url_is_never_rewritten():
    engine, emitted = _engine()
    ready = "https://cdn.example.com/ready.mp3"

    engine.play_track({"id": 9, "source": "youtube", "file_path": "C:/gone.mp3",
                       "title": "T", "artist": "A", "stream_url": ready})

    assert emitted[0]["stream_url"] == ready, "an already-resolved URL must pass through"


def test_empty_stream_url_is_recomputed(tmp_path):
    """'' is falsy, so an unresolved track gets one more chance."""
    engine, emitted = _engine()
    fp = _local_file(tmp_path)

    engine.play_track({"id": 4, "source": "local", "file_path": fp, "stream_url": ""})

    assert emitted[0]["stream_url"].startswith("http://127.0.0.1:8099/api/stream?url=")


def test_queue_track_is_not_mutated(tmp_path):
    """The proxy URL belongs to the emitted copy, not to the queue's dict."""
    engine, emitted = _engine()
    fp = _local_file(tmp_path)
    track = {"id": 6, "source": "local", "file_path": fp, "title": "T", "artist": "A"}

    engine.play_track(track)

    assert emitted[0] is not track
    assert "stream_url" not in track
    assert "stream_url" not in engine.queue.current_track
    assert emitted[0]["stream_url"]


def test_no_callback_configured_is_a_noop(tmp_path):
    engine = AudioEngine()
    engine.proxy = _FakeProxy()
    engine._on_track_changed = None

    engine.play_track({"id": 1, "source": "local", "file_path": _local_file(tmp_path)})  # must not raise


def test_notify_on_an_empty_queue_is_a_noop():
    engine, emitted = _engine()

    engine._notify_track_changed()

    assert emitted == []


# --------------------------------------------------------------------------- #
# repeat / shuffle cycling
# --------------------------------------------------------------------------- #

def test_toggle_repeat_cycles_off_all_one_off():
    engine, _ = _engine()

    assert engine.queue.repeat == "off"
    assert engine.toggle_repeat() == "all"
    assert engine.queue.repeat == "all"
    assert engine.toggle_repeat() == "one"
    assert engine.queue.repeat == "one"
    assert engine.toggle_repeat() == "off"
    assert engine.queue.repeat == "off"


def test_toggle_repeat_starts_from_a_preset_mode():
    engine, _ = _engine()
    engine.queue.repeat = "one"

    assert engine.toggle_repeat() == "off"


def test_repeat_setter_ignores_an_unknown_mode():
    """PlaybackQueue.repeat guards its own setter; toggle_repeat() would
    otherwise raise ValueError from modes.index()."""
    engine, _ = _engine()
    engine.queue.repeat = "nonsense"

    assert engine.queue.repeat == "off"
    assert engine.toggle_repeat() == "all"


def test_toggle_shuffle_returns_the_new_flag():
    engine, _ = _engine()

    assert engine.toggle_shuffle() is True
    assert engine.queue.shuffle is True
    assert engine.toggle_shuffle() is False
    assert engine.queue.shuffle is False


# --------------------------------------------------------------------------- #
# play_track / play_queue / next / prev
# --------------------------------------------------------------------------- #

def _tracks(n=3, prefix="t"):
    return [{"id": i, "title": f"{prefix}{i}", "artist": "a",
             "source": "youtube", "source_id": f"v{i}"} for i in range(n)]


@pytest.mark.parametrize("empty", [None, {}, []])
def test_play_track_with_nothing_returns_none_and_does_not_notify(empty):
    engine, emitted = _engine()

    assert engine.play_track(empty) is None
    assert engine.queue.count == 0
    assert emitted == []


def test_play_track_replaces_the_queue_and_notifies():
    engine, emitted = _engine()
    engine.play_track(_tracks(5, "old")[3])
    emitted.clear()

    assert engine.play_track(_tracks(1)[0]) is None
    assert engine.queue.count == 1
    assert [t["id"] for t in engine.queue.tracks] == [0]
    assert [e["title"] for e in emitted] == ["t0"]


def test_play_queue_with_an_empty_list_wipes_the_queue_without_notifying():
    """Current behaviour, pinned deliberately: set_tracks([]) clears the queue,
    yet play_queue() returns None and emits nothing, so the frontend keeps
    rendering a queue the backend no longer has (see AUDIT-F BUG-4)."""
    engine, emitted = _engine()
    engine.play_track(_tracks(2)[0])

    assert engine.play_queue([]) is None
    assert engine.queue.count == 0
    assert len(emitted) == 1, "no track_changed was emitted for the wipe"


@pytest.mark.xfail(
    strict=True,
    reason="BUG audio/engine.py:40 - play_queue([]) destroys the playback queue "
           "while reporting 'nothing happened' (no _on_track_changed), leaving the "
           "frontend and the backend out of sync",
)
def test_play_queue_with_an_empty_list_must_be_a_noop():
    engine, emitted = _engine()
    engine.play_track(_tracks(2)[0])

    engine.play_queue([])

    assert engine.queue.count == 1


def test_play_queue_notifies_the_current_track():
    engine, emitted = _engine()

    engine.play_queue(_tracks(4), 2)

    assert engine.queue.current_index == 2
    assert emitted[0]["id"] == 2


def test_play_queue_clamps_the_start_index():
    engine, emitted = _engine()

    engine.play_queue(_tracks(3), 99)

    assert engine.queue.current_index == 2
    assert emitted[0]["id"] == 2


def test_play_queue_with_a_negative_index_clamps_to_zero():
    engine, emitted = _engine()

    engine.play_queue(_tracks(3), -5)

    assert engine.queue.current_index == 0
    assert emitted[0]["id"] == 0


def test_play_queue_without_a_list_reuses_the_queue():
    engine, emitted = _engine()
    engine.play_queue(_tracks(3), 0)

    engine.play_queue()

    assert engine.queue.count == 3
    assert emitted[-1]["id"] == 0


def test_play_queue_on_an_empty_queue_returns_none():
    engine, emitted = _engine()

    assert engine.play_queue() is None
    assert emitted == []


def test_next_track_on_an_empty_queue_returns_none_and_ends_the_queue():
    engine, emitted = _engine()
    queue_end = []
    engine._on_queue_end = lambda: queue_end.append(True)

    assert engine.next_track() is None
    assert queue_end == [True]
    assert emitted == []


def test_next_track_notifies_the_new_track():
    engine, emitted = _engine()
    engine.play_queue(_tracks(3), 0)
    emitted.clear()

    assert engine.next_track()["id"] == 1
    assert [e["id"] for e in emitted] == [1]
    assert engine.queue.current_index == 1


def test_next_track_does_not_fire_queue_end_when_advancing():
    engine, emitted = _engine()
    engine.play_queue(_tracks(3), 0)
    queue_end = []
    engine._on_queue_end = lambda: queue_end.append(True)

    assert engine.next_track()["id"] == 1
    assert queue_end == []


def test_next_track_at_the_end_fires_queue_end_once():
    engine, emitted = _engine()
    engine.play_queue(_tracks(2), 0)
    emitted.clear()
    queue_end = []
    engine._on_queue_end = lambda: queue_end.append(True)

    assert engine.next_track()["id"] == 1
    assert engine.next_track() is None
    assert queue_end == [True]
    assert len(emitted) == 1


def test_next_track_wraps_with_repeat_all():
    engine, emitted = _engine()
    engine.queue.repeat = "all"
    engine.play_queue(_tracks(2), 1)
    emitted.clear()
    queue_end = []
    engine._on_queue_end = lambda: queue_end.append(True)

    assert engine.next_track()["id"] == 0
    assert engine.queue.current_index == 0
    assert queue_end == [], "wrapping with repeat=all is not the end of the queue"
    assert [e["id"] for e in emitted] == [0]


def test_next_track_with_repeat_one_notifies_the_same_track_again():
    engine, emitted = _engine()
    engine.queue.repeat = "one"
    engine.play_queue(_tracks(3), 1)
    emitted.clear()

    assert engine.next_track()["id"] == 1
    assert engine.queue.current_index == 1
    assert [e["id"] for e in emitted] == [1]


def test_prev_track_on_an_empty_queue_returns_none_without_queue_end():
    """Asymmetry with next_track() is intentional (test_api_audit_b H-5):
    going back is not the end of playback, so no 'queue_ended' is emitted."""
    engine, emitted = _engine()
    queue_end = []
    engine._on_queue_end = lambda: queue_end.append(True)

    assert engine.prev_track() is None
    assert queue_end == []
    assert emitted == []


def test_prev_track_walks_back_through_history():
    engine, emitted = _engine()
    engine.play_queue(_tracks(4), 0)
    emitted.clear()

    engine.next_track()
    engine.next_track()
    assert engine.queue.current_index == 2

    assert engine.prev_track()["id"] == 1
    assert engine.prev_track()["id"] == 0
    assert [e["id"] for e in emitted] == [1, 2, 1, 0]


def test_prev_track_never_walks_before_the_first_track():
    engine, emitted = _engine()
    engine.play_queue(_tracks(3), 0)
    emitted.clear()

    assert engine.prev_track()["id"] == 0
    assert engine.queue.current_index == 0
    assert [e["id"] for e in emitted] == [0]


def test_prev_track_is_not_pinned_by_repeat_one():
    """repeat='one' only pins *next*; prev_track() still walks back."""
    engine, emitted = _engine()
    engine.queue.repeat = "one"
    engine.play_queue(_tracks(3), 1)
    emitted.clear()

    assert engine.prev_track()["id"] == 0
    assert engine.queue.current_index == 0


# --------------------------------------------------------------------------- #
# queue mutation helpers must not notify the frontend
# --------------------------------------------------------------------------- #

def test_add_to_queue_does_not_notify(tmp_path):
    engine, emitted = _engine()
    fp = _local_file(tmp_path)

    engine.play_track({"id": 1, "source": "local", "file_path": fp})
    emitted.clear()

    engine.add_to_queue({"id": 2, "source": "local", "file_path": fp})
    engine.add_tracks_to_queue([{"id": 3}, {"id": 4}])

    assert engine.queue.count == 4
    assert [t["id"] for t in engine.queue.tracks] == [1, 2, 3, 4]
    assert emitted == [], "queueing tracks is not a track change"


def test_add_tracks_to_queue_ignores_an_empty_list_and_non_dicts():
    engine, emitted = _engine()

    engine.add_tracks_to_queue([])
    engine.add_tracks_to_queue(["not a dict", {"id": 8}])

    assert engine.queue.count == 1
    assert engine.queue.current_track["id"] == 8
    assert emitted == []