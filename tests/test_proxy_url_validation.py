"""Regression tests for `auth.proxy_url` validation (services/base_service.py).

Background: `auth.proxy_url` is a free-text settings field. `requests` and
yt-dlp both accept a bare token in it - they prepend "http://" and dial that
name - so an unparseable value does not fail where it is configured. It becomes
the proxy for EVERY provider call and takes search, stream resolution and
downloads down together with

    ProxyError: Unable to connect to proxy, NameResolutionError(...)

which reads like a network outage although direct egress works. These tests pin
the validation so that failure mode cannot come back.

No test here touches the network or the real profile: only the pure validator
and per-service proxy assignment are exercised.
"""

import pytest

from services.base_service import normalize_proxy_url


# ── the validator itself ──────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [
    "AuraQA46638",        # bare token: the exact shape that caused the outage
    "AuraQA38589",
    "not a url at all",
    "example.com",
    "127.0.0.1:1080",     # host:port without a scheme
    "ftp://127.0.0.1:21",
    "http://",
    "   ",
    "",
    None,
])
def test_unusable_proxy_values_are_ignored(raw):
    assert normalize_proxy_url(raw) == ""


@pytest.mark.parametrize("raw", [
    "http://127.0.0.1:1080",
    "https://proxy.example.com:8443",
    "socks5://127.0.0.1:9050",
    "socks5h://127.0.0.1:9050",
])
def test_valid_proxy_urls_pass_through_unchanged(raw):
    assert normalize_proxy_url(raw) == raw


def test_surrounding_whitespace_is_stripped_not_rejected():
    assert normalize_proxy_url("  http://127.0.0.1:1080  ") == "http://127.0.0.1:1080"


def test_rejection_is_logged_with_the_offending_value(caplog):
    """A silently ignored proxy would change behaviour with no explanation."""
    with caplog.at_level("WARNING", logger="services.base_service"):
        normalize_proxy_url("AuraQA46638")
    assert any("AuraQA46638" in r.getMessage() for r in caplog.records)


# ── the providers must not install an unusable proxy ──────────────────────────

class _Settings:
    """Settings double returning one fixed auth value."""

    def __init__(self, proxy_url):
        self._proxy_url = proxy_url

    def get(self, category, key, default=None):
        if (category, key) == ("auth", "proxy_url"):
            return self._proxy_url
        return default


def _real_module(name):
    """Import a provider module by file, bypassing sys.modules stubs.

    tests/test_lazy_service_deadlock.py replaces sys.modules entries with
    stand-in modules and one of them assigns into sys.modules WITHOUT restoring
    it (plain `sys.modules[...] = ...`, not monkeypatch.setitem). Importing
    normally can therefore hand back a stub whose class has no `_session`. Going
    to the file directly is immune to that.
    """
    import importlib.util
    import os

    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "services", f"{name}.py",
    )
    spec = importlib.util.spec_from_file_location(f"_real_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def offline_soundcloud():
    """The real SoundCloudService with its eager network probes neutralised.

    __init__ submits _get_client_id / _get_ydl to the shared pool, and that work
    reaches the network (directly, or through whatever proxy is installed).
    Stubbing both keeps these tests hermetic; nothing else is stubbed.
    """
    sc_module = _real_module("soundcloud_service")
    sc_module.SoundCloudService._get_client_id = lambda self: None
    sc_module.SoundCloudService._get_ydl = lambda self, *a, **k: None
    return sc_module


@pytest.fixture
def offline_youtube():
    """The real YouTubeService with the eager _get_ydl warm-up neutralised."""
    yt_module = _real_module("youtube_service")
    yt_module.YouTubeService._get_ydl = lambda self, *a, **k: None
    return yt_module


def test_soundcloud_does_not_install_an_unusable_proxy(offline_soundcloud):
    """The exact stored value that took every provider down."""
    svc = offline_soundcloud.SoundCloudService(_Settings("AuraQA46638"))
    assert svc._session.proxies == {}


def test_soundcloud_installs_a_valid_proxy(offline_soundcloud):
    """A syntactically valid proxy is honoured as-is; it is never dialed here."""
    svc = offline_soundcloud.SoundCloudService(_Settings("http://127.0.0.1:1080"))
    assert svc._session.proxies == {
        "http": "http://127.0.0.1:1080",
        "https": "http://127.0.0.1:1080",
    }


def test_spotify_clears_a_stale_proxy_from_the_shared_session():
    """`_session` is module-level, so a stale proxy used to outlive its config.

    With the old `if proxy:` form, constructing a second service with no proxy
    left the first instance's proxy installed on the shared session.
    """
    spotify_module = _real_module("spotify_service")
    spotify_module._session.proxies = {"http": "http://stale:1", "https": "http://stale:1"}
    spotify_module.SpotifyService(_Settings(""))
    assert spotify_module._session.proxies == {}


def test_spotify_does_not_install_an_unusable_proxy():
    spotify_module = _real_module("spotify_service")
    spotify_module._session.proxies = {}
    spotify_module.SpotifyService(_Settings("AuraQA46638"))
    assert spotify_module._session.proxies == {}


def test_spotify_installs_a_valid_proxy():
    spotify_module = _real_module("spotify_service")
    spotify_module._session.proxies = {}
    spotify_module.SpotifyService(_Settings("http://127.0.0.1:1080"))
    assert spotify_module._session.proxies == {
        "http": "http://127.0.0.1:1080",
        "https": "http://127.0.0.1:1080",
    }


def test_youtube_yt_dlp_options_omit_an_unusable_proxy(offline_youtube):
    """yt-dlp receives the proxy through `opts["proxy"]`; it must be absent."""
    svc = offline_youtube.YouTubeService(_Settings("AuraQA46638"))
    assert "proxy" not in svc._get_ydl_opts("high", fallback=False)


def test_youtube_yt_dlp_options_carry_a_valid_proxy(offline_youtube):
    svc = offline_youtube.YouTubeService(_Settings("http://127.0.0.1:1080"))
    assert svc._get_ydl_opts("high", fallback=False)["proxy"] == "http://127.0.0.1:1080"
