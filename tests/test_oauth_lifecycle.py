"""OAuth persistence and refresh contracts with a fully mocked transport."""

from __future__ import annotations

import math

import pytest

import core.oauth as oauth
from core.api import _mask_secrets


class Settings:
    def __init__(self, values=None, flush_result=True):
        self.values = dict(values or {})
        self.flush_result = flush_result
        self.flushes = 0

    def get(self, category, key, default=None):
        return self.values.get((category, key), default)

    def set(self, category, key, value):
        self.values[(category, key)] = value

    def sync_flush_now(self):
        self.flushes += 1
        return self.flush_result

    def get_category(self, category):
        return {key: value for (cat, key), value in self.values.items() if cat == category}


def test_store_yandex_token_persists_access_refresh_and_expiry():
    settings = Settings()
    oauth.store_yandex_token(settings, {
        "access_token": "access-secret",
        "refresh_token": "refresh-secret",
        "expires_in": 120,
    }, now=1_000)

    assert settings.values[("auth", "yandex_token")] == "access-secret"
    assert settings.values[("auth", "yandex_refresh_token")] == "refresh-secret"
    assert settings.values[("auth", "yandex_token_expires_at")] == 1_120
    assert settings.values[("auth", "yandex_token_valid")] is True
    assert settings.flushes == 1


@pytest.mark.parametrize("token", [
    {},
    {"access_token": " "},
    {"access_token": "x", "expires_in": math.inf},
    {"access_token": "x", "expires_in": -1},
])
def test_store_rejects_invalid_oauth_payloads(token):
    with pytest.raises(ValueError):
        oauth.store_yandex_token(Settings(), token, now=0)


def test_store_fails_when_durable_flush_fails():
    with pytest.raises(RuntimeError, match="could not be persisted"):
        oauth.store_yandex_token(Settings(flush_result=False), {"access_token": "x"}, now=0)


def test_refresh_uses_mocked_proxy_aware_session_and_never_returns_credentials(monkeypatch, caplog):
    settings = Settings({
        ("auth", "yandex_refresh_token"): "old-refresh-secret",
        ("auth", "oauth_client_id"): "client-id-secret",
        ("auth", "oauth_client_secret"): "client-secret-secret",
    })
    calls = []

    class Response:
        status_code = 200
        content = b'{"token":"redacted"}'

        def json(self):
            return {"access_token": "new-access-secret", "refresh_token": "new-refresh-secret",
                    "expires_in": 60}

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url, **kwargs):
            calls.append((url, kwargs))
            return Response()

    monkeypatch.setattr(oauth.requests, "Session", Session)
    monkeypatch.setattr(oauth.BaseMusicService, "configure_session", lambda _self, session: session)

    result = oauth.refresh_yandex_token(settings)

    assert result is True
    assert calls == [("https://oauth.yandex.ru/token", {
        "data": {"grant_type": "refresh_token", "refresh_token": "old-refresh-secret",
                 "client_id": "client-id-secret", "client_secret": "client-secret-secret"},
        "timeout": (2, 4), "allow_redirects": False,
    })]
    assert settings.values[("auth", "yandex_token")] == "new-access-secret"
    assert settings.values[("auth", "yandex_refresh_token")] == "new-refresh-secret"
    assert result is True
    for secret in ("old-refresh-secret", "client-id-secret", "client-secret-secret", "new-access-secret"):
        assert secret not in caplog.text


@pytest.mark.parametrize("refresh,client_id", [
    ("", "client"),
    ("refresh", ""),
])
def test_refresh_skips_network_when_credentials_missing(monkeypatch, refresh, client_id):
    settings = Settings({
        ("auth", "yandex_refresh_token"): refresh,
        ("auth", "oauth_client_id"): client_id,
    })
    monkeypatch.setattr(oauth.requests, "Session", lambda: pytest.fail("network session must not be opened"))
    assert oauth.refresh_yandex_token(settings) is False


@pytest.mark.parametrize("status,content_size", [(500, 2), (200, 65_537)])
def test_refresh_rejects_http_error_or_oversized_response(monkeypatch, status, content_size):
    settings = Settings({
        ("auth", "yandex_refresh_token"): "refresh",
        ("auth", "oauth_client_id"): "client",
    })

    class Response:
        def __init__(self):
            self.status_code = status
            self.content = b"x" * content_size

        def json(self):
            pytest.fail("invalid response must not be decoded")

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(oauth.requests, "Session", Session)
    monkeypatch.setattr(oauth.BaseMusicService, "configure_session", lambda _self, session: session)
    assert oauth.refresh_yandex_token(settings) is False
    assert settings.flushes == 0


def test_secret_settings_are_masked_for_bridge_reads():
    settings = Settings({
        ("auth", "yandex_token"): "access-secret",
        ("auth", "yandex_refresh_token"): "refresh-secret",
        ("auth", "oauth_client_secret"): "client-secret",
        ("auth", "proxy_url"): "http://user:pass@proxy.example:8080",
        ("auth", "oauth_client_id"): "public-client-id",
    })
    masked = _mask_secrets("auth", settings.get_category("auth"))
    assert masked["oauth_client_id"] == "public-client-id"
    for key in ("yandex_token", "yandex_refresh_token", "oauth_client_secret", "proxy_url"):
        assert masked[key] == ""
        assert masked[f"has_{key}"] is True
    assert all(secret not in repr(masked) for secret in (
        "access-secret", "refresh-secret", "client-secret", "user:pass"))
