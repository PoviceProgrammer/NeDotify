"""Tests for the NeDotify application update checker and bridge integration."""

import json
from unittest.mock import MagicMock, patch
import pytest

from core.updater import (
    APP_VERSION,
    AppUpdater,
    fetch_latest_release,
    is_newer_version,
    parse_version_tag,
)
from core.bridge import PUBLIC_METHODS


def test_parse_version_tag():
    assert parse_version_tag("2.5.1") == (2, 5, 1)
    assert parse_version_tag("v2.5.1") == (2, 5, 1)
    assert parse_version_tag("V3.0.0") == (3, 0, 0)
    assert parse_version_tag("1.0") == (1, 0)
    assert parse_version_tag("v2.5.1.4") == (2, 5, 1, 4)
    assert parse_version_tag("") is None
    assert parse_version_tag(None) is None
    assert parse_version_tag("invalid-tag") is None


def test_is_newer_version():
    assert is_newer_version("v2.5.2", "v2.5.1") is True
    assert is_newer_version("2.6.0", "2.5.1") is True
    assert is_newer_version("3.0.0", "2.5.1") is True
    assert is_newer_version("v2.5.1.1", "2.5.1") is True

    # Same version
    assert is_newer_version("2.5.1", "2.5.1") is False
    assert is_newer_version("v2.5.1", "2.5.1") is False
    assert is_newer_version("2.5", "2.5.0") is False

    # Older version
    assert is_newer_version("2.5.0", "2.5.1") is False
    assert is_newer_version("1.9.9", "2.5.1") is False

    # Invalid / empty tags
    assert is_newer_version("", "2.5.1") is False
    assert is_newer_version("invalid", "2.5.1") is False
    assert is_newer_version("v2.5.2", "") is True


def test_public_methods_bridge_contract():
    assert "check_for_updates" in PUBLIC_METHODS
    assert "get_app_version" in PUBLIC_METHODS
    assert "open_release_page" in PUBLIC_METHODS


def test_app_updater_check_success():
    updater = AppUpdater(current_version="2.5.1")
    fake_release = {
        "tag_name": "v2.5.2",
        "name": "NeDotify v2.5.2",
        "body": "## Changes\n- Fixed audio glitch\n- Added top update notification",
        "html_url": "https://github.com/PoviceProgrammer/NeDotify/releases/tag/v2.5.2",
        "published_at": "2026-11-09T18:00:00Z",
        "assets": [
            {
                "name": "NeDotify_Setup.exe",
                "browser_download_url": "https://github.com/PoviceProgrammer/NeDotify/releases/download/v2.5.2/NeDotify_Setup.exe",
            },
            {
                "name": "NeDotify.exe",
                "browser_download_url": "https://github.com/PoviceProgrammer/NeDotify/releases/download/v2.5.2/NeDotify.exe",
            },
        ],
    }

    with patch("core.updater.fetch_latest_release", return_value=(fake_release, "")):
        res = updater.check_for_updates(manual=True)
        assert res["update_available"] is True
        assert res["current_version"] == "2.5.1"
        assert res["latest_version"] == "2.5.2"
        assert res["download_url"] == "https://github.com/PoviceProgrammer/NeDotify/releases/download/v2.5.2/NeDotify_Setup.exe"
        assert "Fixed audio glitch" in res["release_notes"]
        assert res["error"] == ""


def test_app_updater_no_update_when_same_version():
    updater = AppUpdater(current_version="2.5.1")
    fake_release = {
        "tag_name": "v2.5.1",
        "body": "Current release notes",
        "html_url": "https://github.com/PoviceProgrammer/NeDotify/releases/tag/v2.5.1",
        "assets": [],
    }

    with patch("core.updater.fetch_latest_release", return_value=(fake_release, "")):
        res = updater.check_for_updates(manual=True)
        assert res["update_available"] is False
        assert res["latest_version"] == "2.5.1"
        assert res["error"] == ""


def test_app_updater_network_error_handled():
    updater = AppUpdater(current_version="2.5.1")

    with patch("core.updater.fetch_latest_release", return_value=(None, "GitHub unreachable")):
        res = updater.check_for_updates(manual=True)
        assert res["update_available"] is False
        assert res["error"] == "GitHub unreachable"


def test_app_updater_caching():
    updater = AppUpdater(current_version="2.5.1")
    fake_release = {
        "tag_name": "v2.5.2",
        "html_url": "https://github.com/releases/2.5.2",
        "assets": [],
    }

    with patch("core.updater.fetch_latest_release", return_value=(fake_release, "")) as mock_fetch:
        res1 = updater.check_for_updates(manual=False)
        assert mock_fetch.call_count == 1
        assert res1["update_available"] is True

        # Second non-manual check uses cache
        res2 = updater.check_for_updates(manual=False)
        assert mock_fetch.call_count == 1
        assert res2["update_available"] is True

        # Manual check bypasses cache
        res3 = updater.check_for_updates(manual=True)
        assert mock_fetch.call_count == 2
        assert res3["update_available"] is True


def test_app_updater_open_url_safety():
    updater = AppUpdater(current_version="2.5.1")
    with patch("webbrowser.open") as mock_open:
        # Safe URL
        assert updater.open_release_url("https://github.com/PoviceProgrammer/NeDotify/releases") is True
        mock_open.assert_called_with("https://github.com/PoviceProgrammer/NeDotify/releases")

        # Unsafe protocol falls back to default releases URL
        updater.open_release_url("file:///C:/Windows/System32/cmd.exe")
        mock_open.assert_called_with("https://github.com/PoviceProgrammer/NeDotify/releases")


def test_api_updater_bridge_methods():
    from core.api import AppApi

    mock_core = MagicMock()
    mock_core.settings = MagicMock()
    mock_core.db = MagicMock()
    mock_core.engine = MagicMock()

    api = AppApi(mock_core)
    assert api.get_app_version() == APP_VERSION
    assert hasattr(api, "check_for_updates")
    assert hasattr(api, "open_release_page")
    assert hasattr(api, "_schedule_startup_update_check")
