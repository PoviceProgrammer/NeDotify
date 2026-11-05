"""Windows Data Protection API (DPAPI) helper for protecting sensitive tokens."""
import base64
import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)

DPAPI_PREFIX = "dpapi:"
_IS_WINDOWS = sys.platform == "win32"

_CryptProtectData = None
_CryptUnprotectData = None
_LocalFree = None

if _IS_WINDOWS:
    try:
        import ctypes
        from ctypes import wintypes

        class _DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_byte)),
            ]

        _CryptProtectData = ctypes.windll.crypt32.CryptProtectData
        _CryptProtectData.argtypes = [
            ctypes.POINTER(_DATA_BLOB),
            wintypes.LPCWSTR,
            ctypes.POINTER(_DATA_BLOB),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DATA_BLOB),
        ]
        _CryptProtectData.restype = wintypes.BOOL

        _CryptUnprotectData = ctypes.windll.crypt32.CryptUnprotectData
        _CryptUnprotectData.argtypes = [
            ctypes.POINTER(_DATA_BLOB),
            ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(_DATA_BLOB),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DATA_BLOB),
        ]
        _CryptUnprotectData.restype = wintypes.BOOL

        _LocalFree = ctypes.windll.kernel32.LocalFree
        _LocalFree.argtypes = [ctypes.c_void_p]
        _LocalFree.restype = ctypes.c_void_p
    except Exception as exc:
        logger.warning("Windows DPAPI initialization failed: %s", exc)
        _CryptProtectData = None
        _CryptUnprotectData = None
        _LocalFree = None


SENSITIVE_SETTING_KEYS = {
    "yandex_token",
    "yandex_refresh_token",
    "vk_token",
    "spotify_token",
    "spotify_refresh_token",
    "oauth_client_secret",
    "lastfm_api_key",
    "lastfm_api_secret",
    "access_token",
    "refresh_token",
}


def is_sensitive_setting(key: str, category: str = "") -> bool:
    """Return True if the key represents a sensitive token or credential."""
    if not isinstance(key, str):
        return False
    short_key = key.split(".", 1)[-1] if "." in key else key
    if short_key in SENSITIVE_SETTING_KEYS or key in SENSITIVE_SETTING_KEYS:
        return True
    if category == "auth" and any(k in short_key.lower() for k in ("token", "secret", "password")):
        return True
    if any(short_key.lower().endswith(suffix) for suffix in ("_token", "_secret", "_password")):
        return True
    return False


def is_dpapi_encrypted(value: Any) -> bool:
    """Return True if value is an encrypted DPAPI string."""
    return isinstance(value, str) and value.startswith(DPAPI_PREFIX)


def dpapi_encrypt(text: str) -> str:
    """Encrypt a plaintext string using Windows DPAPI.

    Returns 'dpapi:<base64>' ciphertext.
    If text is empty or already encrypted, returns text as-is.
    On Linux uses Secret Service or private authenticated file encryption.
    """
    if not isinstance(text, str) or not text:
        return text
    if text.startswith(DPAPI_PREFIX):
        return text
    if not _IS_WINDOWS:
        from core.secret_store import encrypt
        return encrypt(text)
    if _CryptProtectData is None:
        raise RuntimeError("Secure credential storage is unavailable")

    try:
        raw = text.encode("utf-8")
        in_blob = _DATA_BLOB(
            len(raw),
            ctypes.cast(ctypes.create_string_buffer(raw), ctypes.POINTER(ctypes.c_byte)),
        )
        out_blob = _DATA_BLOB()
        # CRYPTPROTECT_UI_FORBIDDEN = 0x1
        if not _CryptProtectData(
            ctypes.byref(in_blob),
            "NeDotify Token",
            None,
            None,
            None,
            1,
            ctypes.byref(out_blob),
        ):
            raise ctypes.WinError()
        try:
            encrypted_bytes = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            return DPAPI_PREFIX + base64.b64encode(encrypted_bytes).decode("ascii")
        finally:
            _LocalFree(out_blob.pbData)
    except Exception as exc:
        logger.error("DPAPI encryption failed: %s", exc)
        raise RuntimeError("Secure credential storage failed") from exc


def dpapi_decrypt(cipher_text: str) -> str:
    """Decrypt a DPAPI-encrypted string prefixed with 'dpapi:'.

    If not encrypted, returns cipher_text as-is.
    If decryption fails, returns empty string.
    """
    if not isinstance(cipher_text, str) or not cipher_text.startswith(DPAPI_PREFIX):
        return cipher_text
    if cipher_text.startswith(("dpapi:keyring:", "dpapi:fernet:")):
        from core.secret_store import decrypt
        return decrypt(cipher_text)
    payload = cipher_text[len(DPAPI_PREFIX):]
    if payload.startswith("mock:"):
        try:
            return base64.b64decode(payload[5:].encode("ascii")).decode("utf-8")
        except Exception:
            return ""
    if _CryptUnprotectData is None:
        logger.warning("DPAPI decryption requested but crypt32 is unavailable")
        return ""

    try:
        raw = base64.b64decode(payload.encode("ascii"))
        in_blob = _DATA_BLOB(
            len(raw),
            ctypes.cast(ctypes.create_string_buffer(raw), ctypes.POINTER(ctypes.c_byte)),
        )
        out_blob = _DATA_BLOB()
        if not _CryptUnprotectData(
            ctypes.byref(in_blob),
            None,
            None,
            None,
            None,
            1,
            ctypes.byref(out_blob),
        ):
            raise ctypes.WinError()
        try:
            decrypted_bytes = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            return decrypted_bytes.decode("utf-8")
        finally:
            _LocalFree(out_blob.pbData)
    except Exception as exc:
        logger.error("DPAPI decryption failed: %s", exc)
        return ""
