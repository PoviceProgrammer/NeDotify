"""Credentials never enable external listening metadata requests by themselves."""
import logging
import sqlite3
from types import SimpleNamespace

import pytest
import requests

from core.settings import DEFAULT_SETTINGS
from services.lastfm_service import LastFMService


@pytest.fixture
def lastfm(settings_stub, monkeypatch):
    monkeypatch.delenv('LASTFM_API_KEY', raising=False)
    settings_stub.set('services', 'lastfm_api_key', 'private-key')
    service = LastFMService(settings_stub)
    monkeypatch.setattr(service, '_acquire_token', lambda: None)
    return service


def test_default_and_saved_credentials_do_not_authorize_requests(lastfm, settings_stub, monkeypatch):
    assert DEFAULT_SETTINGS['services']['lastfm_enabled'] is False
    monkeypatch.setattr(lastfm, '_get_session', lambda: pytest.fail('No consent: no HTTP request'))
    assert lastfm._api_request('user.gettopartists', {'user':'private-user'}, 60) is None
    assert lastfm.artist_get_top_tracks('Artist') == []


def test_explicit_consent_allows_request_and_revocation_stops_cached_results(lastfm, settings_stub, monkeypatch):
    calls = []
    settings_stub.set('services', 'lastfm_enabled', True)
    def get(url, **kwargs):
        calls.append((url, kwargs['params']))
        return SimpleNamespace(status_code=200, json=lambda: {'topartists': {'artist': []}})
    monkeypatch.setattr(lastfm, '_get_session', lambda: SimpleNamespace(get=get))
    assert lastfm._api_request('user.gettopartists', {'user':'private-user'}, 60) == {'topartists': {'artist': []}}
    assert calls[0][1]['user'] == 'private-user'
    assert calls[0][1]['api_key'] == 'private-key'
    settings_stub.set('services', 'lastfm_enabled', False)
    assert lastfm._api_request('user.gettopartists', {'user':'private-user'}, 60) is None
    assert len(calls) == 1


def test_live_keys_use_services_then_legacy_fallback(lastfm, settings_stub):
    settings_stub.set('auth', 'lastfm_api_key', 'legacy-secret')
    assert lastfm._resolve_api_keys() == ['private-key']
    settings_stub.set('services', 'lastfm_api_key', '')
    assert lastfm._resolve_api_keys() == ['legacy-secret']
    settings_stub.set('services', 'lastfm_api_key', 'new-key')
    assert lastfm._resolve_api_keys() == ['new-key']


def test_bridge_hides_legacy_keys_and_explicit_clear_removes_both_categories(api, settings_stub):
    settings_stub.set('auth', 'lastfm_api_key', 'legacy-secret')
    settings_stub.set('services', 'lastfm_api_key', 'new-secret')
    tree = api.get_settings()
    assert tree['auth']['lastfm_api_key'] == ''
    assert tree['services']['lastfm_api_key'] == ''
    assert 'secret' not in str(tree)
    assert api.save_setting('lastfm_api_key', None, 'services') is True
    assert settings_stub.get('auth', 'lastfm_api_key') == ''
    assert settings_stub.get('services', 'lastfm_api_key') == ''


def test_lastfm_diagnostics_redact_credentials_user_and_remote_payloads(
    lastfm, settings_stub, monkeypatch, caplog
):
    from services import lastfm_service

    settings_stub.set('services', 'lastfm_enabled', True)
    username = 'private-listener@example.test'
    secret_marker = 'DO_NOT_LOG_PRIVATE_KEY'
    caplog.set_level(logging.DEBUG, logger='LastFMService')

    def fail_with_prepared_url(_url, *, params, **_kwargs):
        raise requests.ConnectionError(
            f"request failed for ?api_key={params['api_key']}&user={params['user']}&token={secret_marker}"
        )

    monkeypatch.setattr(lastfm, '_get_session', lambda: SimpleNamespace(get=fail_with_prepared_url))
    assert lastfm._api_request('user.getrecenttracks', {'user': username}, 60) is None
    assert secret_marker not in caplog.text
    assert 'private-key' not in caplog.text
    assert username not in caplog.text
    assert 'ConnectionError' in caplog.text

    caplog.clear()
    monkeypatch.setattr(
        lastfm, '_get_session',
        lambda: SimpleNamespace(get=lambda *_args, **_kwargs: SimpleNamespace(
            status_code=500, text=f'{secret_marker} {username}', json=lambda: {}
        )),
    )
    assert lastfm._api_request('chart.gettoptracks', {}, 60) is None
    assert secret_marker not in caplog.text
    assert username not in caplog.text
    assert '500' in caplog.text

    caplog.clear()
    monkeypatch.setattr(
        lastfm, '_get_session',
        lambda: SimpleNamespace(get=lambda *_args, **_kwargs: SimpleNamespace(
            status_code=200,
            text='',
            json=lambda: {'error': f'{secret_marker}{username}',
                          'message': f'{secret_marker} {username}'},
        )),
    )
    assert lastfm._api_request('chart.gettoptracks', {}, 60) is None
    assert secret_marker not in caplog.text
    assert username not in caplog.text
    assert 'error code unknown' in caplog.text

    caplog.clear()
    def fail_cache_connect(*_args, **_kwargs):
        raise sqlite3.OperationalError(f'{secret_marker} {username}')

    monkeypatch.setattr(lastfm_service.sqlite3, 'connect', fail_cache_connect)
    assert lastfm._get_cached(f'user.getrecenttracks:user={username}') is None
    assert secret_marker not in caplog.text
    assert username not in caplog.text
    assert 'OperationalError' in caplog.text

    caplog.clear()
    assert lastfm._get_stale_cache(f'user.getrecenttracks:user={username}') is None
    assert secret_marker not in caplog.text
    assert username not in caplog.text
    assert 'OperationalError' in caplog.text
