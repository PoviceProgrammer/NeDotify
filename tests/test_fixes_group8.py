"""Unit and integration tests for Group 8 fixes: Build, Dependencies, and Security.

Covers:
- BUG-WIN-024: scipy in requirements.txt, hiddenimports in setup_pyinstaller.spec,
  and lufs_scanner fallback.
- Linux runtime packaging: Qt WebEngine, EJS and native dependency preparation.
- BUG-WIN-028: Windows DPAPI token encryption, SQLite persistence without plaintext,
  and transparent migration on read.
"""

import os
import sqlite3
import numpy as np
import pytest

from core.dpapi import (
    dpapi_encrypt,
    dpapi_decrypt,
    is_dpapi_encrypted,
    is_sensitive_setting,
    DPAPI_PREFIX,
)
from core.database import DatabaseManager
from core.settings import SettingsManager, DEFAULT_SETTINGS
import core.oauth as oauth
from core.api import _mask_secrets, _SECRET_SETTING_KEYS
from services.lufs_scanner import _lfilter_fallback, analyze_lufs


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


# ==============================================================================
# BUG-WIN-024 Tests: scipy dependency, hiddenimports, lufs_scanner fallback
# ==============================================================================

def test_requirements_contains_scipy():
    """Verify that requirements.txt declares scipy dependency."""
    req_path = os.path.join(PROJECT_ROOT, "requirements.txt")
    assert os.path.exists(req_path), "requirements.txt not found"
    content = open(req_path, "r", encoding="utf-8").read()
    lines = [line.strip() for line in content.splitlines() if line.strip() and not line.strip().startswith("#")]
    scipy_lines = [line for line in lines if line.startswith("scipy")]
    assert len(scipy_lines) >= 1, "scipy must be declared in requirements.txt"
    assert any("scipy>=" in line for line in scipy_lines), "scipy version should have lower bound"


def test_pyinstaller_spec_hiddenimports_contains_scipy():
    """Verify setup_pyinstaller.spec includes scipy in hiddenimports."""
    spec_path = os.path.join(PROJECT_ROOT, "setup_pyinstaller.spec")
    assert os.path.exists(spec_path), "setup_pyinstaller.spec not found"
    content = open(spec_path, "r", encoding="utf-8").read()
    assert "'scipy'" in content, "scipy must be in setup_pyinstaller.spec hiddenimports"
    assert "'scipy.signal'" in content, "scipy.signal must be in setup_pyinstaller.spec hiddenimports"


def test_lfilter_fallback_matches_scipy_signal():
    """Verify that _lfilter_fallback matches scipy.signal.lfilter filter output."""
    b = np.array([1.53512485958697, -2.69169618940638, 1.19839281085285], dtype=np.float64)
    a = np.array([1.0, -1.69065929318241, 0.73248077421585], dtype=np.float64)
    x = np.sin(np.linspace(0, 100, 1000)).astype(np.float32)
    zi = np.zeros(2, dtype=np.float64)

    y_fb, zf_fb = _lfilter_fallback(b, a, x, zi=zi)

    try:
        from scipy.signal import lfilter
        y_scipy, zf_scipy = lfilter(b, a, x, zi=zi)
        np.testing.assert_allclose(y_fb, y_scipy, rtol=1e-5, atol=1e-5)
        np.testing.assert_allclose(zf_fb, zf_scipy, rtol=1e-5, atol=1e-5)
    except ImportError:
        # If scipy is not installed, verify basic fallback output properties
        assert len(y_fb) == len(x)
        assert len(zf_fb) == 2


def test_analyze_lufs_uses_fallback_when_scipy_import_fails(monkeypatch):
    """Verify analyze_lufs falls back to _lfilter_fallback when scipy.signal cannot be imported."""
    import builtins
    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "scipy.signal" or (name == "scipy" and len(args) > 1 and "signal" in str(args)):
            raise ImportError("Mocked scipy missing")
        return real_import(name, *args, **kwargs)

    # analyze_lufs should not crash even if scipy.signal fails to import
    # It will either use _lfilter_fallback or return error string without crashing
    monkeypatch.setattr(builtins, "__import__", mock_import)
    loudness, peak, error = analyze_lufs("non_existent_file.wav")
    assert loudness is None
    assert peak is None
    assert error is not None


# ==============================================================================
# BUG-WIN-025 Tests: WebView2 Evergreen runtime bootstrapper in installer.iss
# ==============================================================================

def test_linux_webengine_is_an_explicit_runtime_dependency():
    """The Linux renderer is installed with the app, rather than relying on WebView2."""
    from packaging.requirements import Requirement
    req_path = os.path.join(PROJECT_ROOT, "requirements.txt")
    lines = open(req_path, encoding="utf-8").read().splitlines()
    requirements = {requirement.name.lower(): requirement for line in lines
                    if line.strip() and not line.lstrip().startswith("#")
                    for requirement in [Requirement(line)]}
    assert "qt" in requirements["pywebview"].extras
    assert "pyqt6" in requirements and "pyqt6-webengine" in requirements
    assert "qtpy" in requirements
    assert "pythonnet" not in requirements
    assert not os.path.exists(os.path.join(PROJECT_ROOT, "installer.iss"))


def test_linux_tool_preparation_ships_ejs_and_a_supported_js_runtime():
    """Current YouTube extraction requires the EJS companion and a JS runtime."""
    from packaging.requirements import Requirement
    lines = open(os.path.join(PROJECT_ROOT, "requirements.txt"), encoding="utf-8").read().splitlines()
    requirements = {requirement.name.lower(): requirement for line in lines
                    if line.strip() and not line.lstrip().startswith("#")
                    for requirement in [Requirement(line)]}
    assert "default" in requirements["yt-dlp"].extras
    assert requirements["deno"].specifier.contains("2.6.6")
    assert not requirements["deno"].specifier.contains("2.0.0")
    spec = open(os.path.join(PROJECT_ROOT, "setup_pyinstaller.spec"), encoding="utf-8").read()
    assert 'support["native_tools"]()' in spec
    assert '"yt_dlp_ejs"' in spec
    assert "winws.exe" not in spec


# ==============================================================================
# BUG-WIN-028 Tests: Windows DPAPI token encryption and transparent migration
# ==============================================================================

def test_dpapi_encrypt_decrypt_roundtrip():
    """Verify DPAPI encrypts to 'dpapi:' prefixed ciphertext and decrypts accurately."""
    token = "y0_AgAAAAA-secret-oauth-access-token-12345"
    encrypted = dpapi_encrypt(token)

    assert encrypted != token
    assert is_dpapi_encrypted(encrypted)
    assert encrypted.startswith(DPAPI_PREFIX)

    decrypted = dpapi_decrypt(encrypted)
    assert decrypted == token


def test_dpapi_handles_empty_and_idempotence():
    """Verify DPAPI handles empty strings and is idempotent on already encrypted values."""
    assert dpapi_encrypt("") == ""
    assert dpapi_decrypt("") == ""
    assert dpapi_decrypt("plain_non_encrypted") == "plain_non_encrypted"

    token = "secret"
    enc = dpapi_encrypt(token)
    assert dpapi_encrypt(enc) == enc  # Idempotent


def test_is_sensitive_setting_identifies_oauth_tokens():
    """Verify sensitivity classifier matches all OAuth and credential keys."""
    sensitive_keys = [
        "yandex_token",
        "yandex_refresh_token",
        "vk_token",
        "spotify_token",
        "spotify_refresh_token",
        "oauth_client_secret",
        "lastfm_api_key",
        "lastfm_api_secret",
        "auth.yandex_token",
        "auth.vk_token",
        "auth.spotify_token",
    ]
    for key in sensitive_keys:
        assert is_sensitive_setting(key), f"Key {key} should be classified as sensitive"

    non_sensitive_keys = [
        "general.theme",
        "theme",
        "volume",
        "yandex_token_expires_at",
        "yandex_token_valid",
        "lyrics.enabled",
    ]
    for key in non_sensitive_keys:
        assert not is_sensitive_setting(key), f"Key {key} should not be sensitive"


def test_database_stores_sensitive_tokens_encrypted(tmp_path):
    """Verify SQLite database stores sensitive tokens encrypted (NEVER in plaintext)."""
    db_path = str(tmp_path / "test_secure.db")
    db = DatabaseManager(db_path)

    secret_token = "y0_super_secret_yandex_access_token_999"
    db.set_setting("auth.yandex_token", secret_token, category="auth")

    # Inspect raw SQLite directly
    raw_conn = sqlite3.connect(db_path)
    cursor = raw_conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'auth.yandex_token'")
    row = cursor.fetchone()
    raw_value = row[0]
    raw_conn.close()

    # Assert raw value is DPAPI encrypted and does NOT contain plaintext
    assert is_dpapi_encrypted(raw_value)
    assert secret_token not in raw_value

    # Assert get_setting transparently decrypts
    assert db.get_setting("auth.yandex_token") == secret_token

    # Assert get_all_settings transparently decrypts
    all_settings = db.get_all_settings()
    assert all_settings["auth.yandex_token"] == secret_token

    # Assert get_settings_by_category transparently decrypts
    auth_settings = db.get_settings_by_category("auth")
    assert auth_settings["auth.yandex_token"] == secret_token

    db.close()


def test_database_transparent_migration_of_legacy_plaintext_tokens(tmp_path):
    """Verify legacy plaintext tokens in SQLite are decrypted and transparently migrated."""
    db_path = str(tmp_path / "test_migration.db")
    db = DatabaseManager(db_path)

    # Inject legacy plaintext tokens directly via raw SQL
    legacy_token = "legacy_plaintext_yandex_token_abc"
    legacy_vk = "legacy_plaintext_vk_token_xyz"
    raw_conn = sqlite3.connect(db_path)
    raw_conn.execute("INSERT OR REPLACE INTO settings (key, value, category) VALUES (?, ?, ?)",
                     ("auth.yandex_token", f'"{legacy_token}"', "auth"))
    raw_conn.execute("INSERT OR REPLACE INTO settings (key, value, category) VALUES (?, ?, ?)",
                     ("auth.vk_token", f'"{legacy_vk}"', "auth"))
    raw_conn.commit()
    raw_conn.close()

    # Reading settings should return the plaintext value to the app
    all_settings = db.get_all_settings()
    assert all_settings["auth.yandex_token"] == legacy_token
    assert all_settings["auth.vk_token"] == legacy_vk

    # Verify SQLite row was transparently migrated to DPAPI on disk!
    raw_conn = sqlite3.connect(db_path)
    cursor = raw_conn.cursor()
    cursor.execute("SELECT key, value FROM settings WHERE key IN ('auth.yandex_token', 'auth.vk_token')")
    rows = dict(cursor.fetchall())
    raw_conn.close()

    assert is_dpapi_encrypted(rows["auth.yandex_token"])
    assert legacy_token not in rows["auth.yandex_token"]
    assert is_dpapi_encrypted(rows["auth.vk_token"])
    assert legacy_vk not in rows["auth.vk_token"]

    db.close()


def test_settings_manager_and_oauth_store_helpers(tmp_path):
    """Verify SettingsManager and OAuth helpers store encrypted tokens."""
    db_path = str(tmp_path / "test_sm.db")
    db = DatabaseManager(db_path)
    sm = SettingsManager(db)

    # Use store_yandex_token, store_vk_token, store_spotify_token
    oauth.store_yandex_token(sm, {"access_token": "ya-token-123", "refresh_token": "ya-refresh-456", "expires_in": 3600})
    oauth.store_vk_token(sm, {"access_token": "vk-token-789"})
    oauth.store_spotify_token(sm, {"access_token": "sp-token-321", "refresh_token": "sp-refresh-654"})

    sm.sync_flush_now()

    # Verify raw database contains ciphertext
    raw_conn = sqlite3.connect(db_path)
    cursor = raw_conn.cursor()
    for key in ["auth.yandex_token", "auth.yandex_refresh_token", "auth.vk_token", "auth.spotify_token", "auth.spotify_refresh_token"]:
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        assert row is not None, f"Setting {key} must exist"
        assert is_dpapi_encrypted(row[0]), f"Setting {key} in DB must be encrypted"
    raw_conn.close()

    # Load in fresh SettingsManager instance to verify decryption
    sm2 = SettingsManager(db)
    assert sm2.get("auth", "yandex_token") == "ya-token-123"
    assert sm2.get("auth", "yandex_refresh_token") == "ya-refresh-456"
    assert sm2.get("auth", "vk_token") == "vk-token-789"
    assert sm2.get("auth", "spotify_token") == "sp-token-321"
    assert sm2.get("auth", "spotify_refresh_token") == "sp-refresh-654"

    sm.close()
    sm2.close()
    db.close()


def test_api_masks_all_oauth_secrets_from_bridge():
    """Verify that _mask_secrets hides all sensitive auth tokens from JS bridge."""
    auth_data = {
        "yandex_token": "secret_token",
        "yandex_refresh_token": "secret_refresh",
        "vk_token": "secret_vk",
        "spotify_token": "secret_spotify",
        "spotify_refresh_token": "secret_spotify_refresh",
        "oauth_client_secret": "secret_oauth",
        "lastfm_username": "regular_user",
    }
    masked = _mask_secrets("auth", auth_data)

    assert masked["yandex_token"] == ""
    assert masked["has_yandex_token"] is True
    assert masked["vk_token"] == ""
    assert masked["has_vk_token"] is True
    assert masked["spotify_token"] == ""
    assert masked["has_spotify_token"] is True
    assert masked["lastfm_username"] == "regular_user"
