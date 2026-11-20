"""Read-only probes for WX-01 (role B). Writes nothing into the repo."""
import os
import sys
import tempfile
import types

REPO = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main"
sys.path.insert(0, REPO)

import core.api as api_module

api_module.TrayIcon = lambda *a, **k: types.SimpleNamespace(update_state=lambda **kw: None)

from core.api import AppApi            # noqa: E402
from audio.engine import AudioEngine   # noqa: E402
from core import proxy as proxy_module  # noqa: E402


class FakeDb:
    def get_cached_stream(self, *a, **k):
        return None

    def get_track(self, *a, **k):
        return None

    def get_track_by_path(self, *a, **k):
        return None

    def get_track_by_source_id(self, *a, **k):
        return None

    def ensure_track_exists(self, *a, **k):
        return None

    def update_history_duration(self, *a, **k):
        pass

    def get_downloaded_tracks(self):
        return []


def build_core():
    stream_dir = tempfile.mkdtemp()
    core = types.SimpleNamespace(
        db=FakeDb(),
        settings=None,
        cache=types.SimpleNamespace(_streams_dir=stream_dir),
        proxy=None,
        engine=AudioEngine(),
        discord_rpc=None,
    )
    core.engine.app_core = core
    return core


def probe_double_resolution():
    print("=== PROBE 1: one user click -> how many provider resolutions? ===")
    core = build_core()
    calls = []

    def fake_re_resolve(source, source_id, callback=None, on_error=None,
                        quality="high", track=None):
        calls.append((source, source_id))
        return None

    core.re_resolve_stream_url_async = fake_re_resolve
    api = AppApi(core)
    emitted = []
    api._emit = lambda name, data=None: emitted.append((name, data))

    track = {"source": "youtube", "source_id": "dQw4w9WgXcQ",
             "title": "T", "artist": "A", "duration": 100}

    api.play_track(dict(track), [dict(track)], 0)
    print("  after api.play_track(track, [track], 0) ->", calls)
    for name, data in emitted:
        if name == "track_changed":
            print("  track_changed payload: stream_url=%r file_path=%r source=%r source_id=%r"
                  % (data.get("stream_url"), data.get("file_path"),
                     data.get("source"), data.get("source_id")))
            payload = data

    # player.js onTrackChanged(): stream_url falsy, file_path falsy, source set ->
    # falls into the "Stream not resolved yet" branch and calls api.play_track again.
    fires = (not payload.get("stream_url")) and (not payload.get("file_path")) \
        and payload.get("source") and payload.get("source") != "local" \
        and payload.get("source_id")
    print("  player.js fallback branch (play_track again) fires?", bool(fires))
    if fires:
        api.play_track({**track, "file_path": None, "stream_url": None})
    print("  total provider resolutions for ONE click ->", len(calls), calls)


def probe_url_shapes():
    print()
    print("=== PROBE 2: the 'stream URL contract' - who builds which shape ===")
    mgr = proxy_module.LocalProxyManager(object())
    mgr.port = 5555
    mgr.token = "TOKEN123"

    cases = [
        ("youtube", "yt1", "https://rr3---sn-x.googlevideo.com/videoplayback?expire=1"),
        ("soundcloud", "sc1", "https://cf-media.sndcdn.com/abc.mp3"),
        ("yandex", "ya1", "https://music.yandex.ru/track/123"),
        ("yandex", "ya2", "https://storage.mds.yandex.net/get-music/9/abc.mp3"),
        ("vk", "vk1", "https://vk.com/audio.mp3"),
    ]
    for source, sid, url in cases:
        built = mgr.get_proxy_url(source, sid, url, track_id=7)
        shape = "/api/stream" if "/api/stream" in built else "/?url="
        # engine.py rule: audio/engine.py:95
        engine_shape = ("/?url=" if not any(d in url for d in
                          ("youtube.com", "youtu.be", "soundcloud.com", "music.yandex.ru"))
                        else "/api/stream")
        creds = proxy_module._host_allows_credentials(url, source)
        print("  %-10s %-42s proxy.py=%-11s engine.py=%-11s creds_injected=%s"
              % (source, url[:42], shape, engine_shape, creds))
        if shape != engine_shape:
            print("      !! DIVERGENT SHAPES for the same track")
        print("      ", built)


def probe_recovery_mismatch():
    print()
    print("=== PROBE 3: playback_recovery builds the URL with the ORIGINAL source/id ===")
    mgr = proxy_module.LocalProxyManager(object())
    mgr.port = 5555
    mgr.token = "TOKEN123"
    # scenario: the track was 'soundcloud', the recovery fell back to YouTube
    original_source, original_id = "soundcloud", "sc-777"
    selected_source, selected_id = "youtube", "yt-999"
    stream = "https://rr3---sn-x.googlevideo.com/videoplayback?expire=1&sig=SECRET"
    url = mgr.get_proxy_url(original_source, original_id, stream, track_id=42)
    print("  built:", url)
    print("  url carries upstream host  :", proxy_module._host_of(stream))
    print("  url declares source        :", original_source)
    print("  actual resolved source     :", selected_source, "/", selected_id)
    print("  credentials for that host  :",
          proxy_module._host_allows_credentials(stream, original_source),
          "(withheld -> the recovery stream is fetched unauthenticated)")


def probe_ssrf_on_upstream():
    print()
    print("=== PROBE 4: is the SSRF gate applied to the upstream on this path? ===")
    print("  proxy '/' branch  -> _is_ssrf_safe_url(target_url) at core/proxy.py:954")
    print("  proxy '/api/stream' -> _is_ssrf_safe_url(target_url) at core/proxy.py:841")
    print("  SafeRedirectHandler.redirect_request -> _is_ssrf_safe_url(newurl) at :379")
    print("  _is_ssrf_safe_url('http://127.0.0.1:1/x') =",
          api_module._is_ssrf_safe_url("http://127.0.0.1:1/x"))
    print("  _is_ssrf_safe_url('https://example.com/x') =",
          api_module._is_ssrf_safe_url("https://example.com/x"))


if __name__ == "__main__":
    probe_double_resolution()
    probe_url_shapes()
    probe_recovery_mismatch()
    probe_ssrf_on_upstream()
