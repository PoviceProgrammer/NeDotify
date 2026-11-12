"""Application update checker for NeDotify Windows.

Queries the public GitHub Releases API directly without requiring any dedicated
backend servers. Compares release semver tags, respects GitHub API rate limits,
and caches results.
"""

import json
import logging
import re
import sys
import threading
import time
import urllib.request
import webbrowser
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

APP_VERSION = "2.5.7"
GITHUB_REPO = "PoviceProgrammer/NeDotify"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"

# Numeric version tag pattern: optional 'v' followed by numeric components (e.g., 'v2.5.6', '2.5.0')
_VERSION_TAG_RE = re.compile(r'^[vV]?(\d+(?:\.\d+)*)$')

# Auto-check interval: 6 hours (in seconds) to avoid GitHub API rate limits (60 requests/hr per IP)
AUTO_CHECK_INTERVAL_SEC = 6 * 3600


def parse_version_tag(tag: str) -> Optional[Tuple[int, ...]]:
    """Parse a version tag into a comparable numeric tuple.

    Examples:
        'v2.5.6' -> (2, 5, 1)
        '2.5.0'  -> (2, 5, 0)
        'v3.0'   -> (3, 0)
    """
    if not tag:
        return None
    match = _VERSION_TAG_RE.match(tag.strip())
    if not match:
        return None
    try:
        return tuple(int(part) for part in match.group(1).split('.'))
    except (ValueError, TypeError):
        return None


def is_newer_version(latest_tag: str, current_tag: str) -> bool:
    """Return True if latest_tag is strictly newer than current_tag.

    Tuple comparison: (2, 5, 2) > (2, 5, 1). If lengths differ, pads with zeros:
    (2, 5) is equal to (2, 5, 0), and (2, 5, 1) > (2, 5).
    """
    latest = parse_version_tag(latest_tag)
    current = parse_version_tag(current_tag)

    if not latest:
        return False
    if not current:
        return True

    max_len = max(len(latest), len(current))
    p1 = latest + (0,) * (max_len - len(latest))
    p2 = current + (0,) * (max_len - len(current))
    return p1 > p2


def fetch_latest_release(timeout: float = 6.0) -> Tuple[Optional[Dict[str, Any]], str]:
    """Fetch latest release metadata directly from GitHub Releases API.

    Returns:
        (release_dict, error_string)
    """
    headers = {
        "User-Agent": f"NeDotify-Desktop/{APP_VERSION} (Windows)",
        "Accept": "application/vnd.github.v3+json",
    }
    req = urllib.request.Request(GITHUB_API_URL, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if not isinstance(data, dict):
                return None, "Некорректный ответ от GitHub API"
            return data, ""
    except urllib.error.HTTPError as e:
        logger.warning("GitHub releases API HTTP error: %s", e)
        if e.code == 403:
            return None, "Превышен лимит запросов к GitHub API. Попробуйте позже."
        elif e.code == 404:
            return None, "Релизы не найдены в репозитории."
        return None, f"Ошибка GitHub API: HTTP {e.code}"
    except Exception as e:
        logger.warning("GitHub releases API request failed: %s", e)
        return None, f"Не удалось связаться с GitHub: {e}"


class AppUpdater:
    """Manages update checks and release links for the application."""

    def __init__(self, current_version: str = APP_VERSION):
        self.current_version = current_version
        self._lock = threading.Lock()
        self._last_check_time: float = 0.0
        self._cached_result: Optional[Dict[str, Any]] = None

    def get_app_version(self) -> str:
        """Return current app version string."""
        return self.current_version

    def check_for_updates(self, manual: bool = False) -> Dict[str, Any]:
        """Check whether a newer version of NeDotify is available.

        If manual is False and a check was performed recently, returns cached result.
        """
        now = time.time()
        with self._lock:
            if not manual and self._cached_result is not None:
                if (now - self._last_check_time) < AUTO_CHECK_INTERVAL_SEC:
                    return dict(self._cached_result)

        data, error = fetch_latest_release()

        result: Dict[str, Any] = {
            "current_version": self.current_version,
            "latest_version": self.current_version,
            "update_available": False,
            "release_notes": "",
            "release_url": GITHUB_RELEASES_URL,
            "published_at": "",
            "download_url": "",
            "error": error,
        }

        if error or not data:
            result["error"] = error or "Не удалось получить информацию о релизе"
            return result

        tag_name = data.get("tag_name") or ""
        clean_version = tag_name.lstrip("vV")
        result["latest_version"] = clean_version or tag_name
        result["release_notes"] = data.get("body") or ""
        result["release_url"] = data.get("html_url") or f"{GITHUB_RELEASES_URL}/tag/{tag_name}"
        result["published_at"] = data.get("published_at") or ""

        # Find Windows setup asset (.exe)
        assets = data.get("assets", [])
        if isinstance(assets, list):
            for asset in assets:
                name = (asset.get("name") or "").lower()
                if name.endswith(".exe") and "setup" in name:
                    result["download_url"] = asset.get("browser_download_url") or ""
                    break
            if not result["download_url"]:
                for asset in assets:
                    name = (asset.get("name") or "").lower()
                    if name.endswith(".exe"):
                        result["download_url"] = asset.get("browser_download_url") or ""
                        break

        result["update_available"] = is_newer_version(clean_version, self.current_version)

        with self._lock:
            self._last_check_time = now
            self._cached_result = dict(result)

        return result

    def open_release_url(self, url: Optional[str] = None) -> bool:
        """Open the release or download URL in the user's default web browser."""
        target = url or GITHUB_RELEASES_URL
        if not target.startswith(("https://", "http://")):
            target = GITHUB_RELEASES_URL
        try:
            webbrowser.open(target)
            return True
        except Exception as e:
            logger.warning("Failed to open browser URL %s: %s", target, e)
            return False
