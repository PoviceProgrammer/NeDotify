"""
NeDotify - Settings Manager
Centralized settings with default values, database storage, and convenient getters/setters.
"""

from typing import Any, Dict, Optional
import atexit
import logging
import platform
import os
import threading
import time

logger = logging.getLogger(__name__)








def get_system_region():
    """Detect system region/language code."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(10)
        ctypes.windll.kernel32.GetUserDefaultGeoName.restype = ctypes.c_int
        ctypes.windll.kernel32.GetUserDefaultGeoName.argtypes = [ctypes.c_wchar_p, ctypes.c_int]
        result = ctypes.windll.kernel32.GetUserDefaultGeoName(buf, 10)
        if result > 0:
            region = buf.value.strip().upper()
            if len(region) == 2:
                return region
    except Exception:
        pass

    try:
        import locale
        loc = locale.getdefaultlocale()[0]
        if loc and '_' in loc:
            region = loc.split('_')[-1].upper()
            if len(region) == 2:
                return region
    except:
        pass

    return "US"


DEFAULT_SETTINGS = {
    "general": {
        "language": "ru",
        "region": get_system_region(),
        "minimize_to_tray": True,
        "start_minimized": False,
        "check_updates": True,
        "show_notifications": True,
        "autostart": False,
        "first_launch_done": False,
        "gpu_acceleration": True,
    },
    "audio": {
        "autoplay": False,
        "queue_autopilot": True,
        "flow_enabled": True,
        "quality": "high",
        "gapless_playback": False,
        "crossfade_enabled": False,
        "crossfade_duration": 3,
        "crossfade_duration_sec": 3,
        "volume_normalization": False,
        "target_loudness": -14.0,
        "output_device": "default",
        "volume": 70,
        "muted": False,
    },
    "overlay": {
        "mode": "disabled",
        "position": "top_center",
        "opacity": 0.9,
        "scale": 1.0,
        "width": 300,
        "height": 80,
        "offset_x": 0,
        "offset_y": 20,
        "show_cover": True,
        "show_controls": True,
    },
    "efficiency": {
        "unfocus_enabled": False,
        "unfocus_fps_limit": 15,
        "unfocus_blur_reduction": True,
        "unfocus_disable_visualizations": True,
        "unfocus_disable_animations": False,
    },
    "optimization": {
        "performance_preset": "balanced",
        "limit_state": "minimize",
        "blur_quality": "hq",
        "glow_quality": "full",
        "fps_particles": 60,
        "fps_visualizer": 60,
        "fps_ui": 60,
        "resource_bg": True,
        "resource_particles": True,
        "resource_covers": True,
        "resource_visualizers": True,
        "resource_blur": True,
    },
    "hotkeys": {
        "play_pause": "Space",
        "next_track": "Ctrl+Right",
        "prev_track": "Ctrl+Left",
        "volume_up": "Ctrl+Up",
        "volume_down": "Ctrl+Down",
        "mute": "Ctrl+M",
        "like": "Ctrl+L",
        "search": "Ctrl+F",
        "toggle_overlay": "Ctrl+O",
    },
    "storage": {
        "cache_size_mb": 500,
        "auto_cache_streams": True,
        "cache_covers": True,
        "scan_folders": [],
    },
    "player_appearance": {
        "show_spectrum": True,
        "spectrum_style": "bars",
        "show_progress_bar": True,
        "show_time": True,
        "cover_animation": True,
        "adaptive_accent": True,
        "cover_blur_bg": True,
        "cover_size": "medium",
    },
    "personalization": {
        "favorite_genres": [],
        "explicit_artists": [],
        "preferred_moods": [],
        "onboarding_completed": False,
    },
    "theme": {
        "theme": "dark",
        "name": "Dark",
        "mode": "dark",
        "accent_color": "#a855f7",
        "transparency_enabled": False,
        "transparency_level": 0.8,
        "glass_blur": 15,
        "glass_color_intensity": 0.5,
        "custom_themes": [],
    },
    "interface": {
        "border_radius": 12,
        "fullscreen_scale": 1.0,
        "window_scale": 1.0,
        "font_family": "system",
        "font_name": "Roboto",
        "tabs": {
            "show_home": True,
            "show_library": True,
            "show_search": True,
            "tab_position": "top",
        },
        "background": {
            "type": "solid",
            "color": "#0d1117",
            "image_path": None,
            "blur_strength": 10,
        },
        "theme": "dark",
        "name": "Dark",
        "transparency_enabled": False,
        "transparency_level": 0.8,
        "glass_blur": 15,
        "glass_color_intensity": 0.5,
        "accent_color": "#a855f7",
        "custom_themes": [],
    },
    "ui": {
        "particles_enabled": True,
        "particles_count": 30,
        "particles_speed": 1.0,
        "particles_size": 2.0,
        "particles_shape": "circle",
        "cover_visualizer": False,
    },
    "equalizer": {
        "preamp": 0.0,
        "bands": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    },
    "auth": {
        "cookies_file_path": "",
        "browser_cookies": "none",
        "yandex_token": "",
        "proxy_url": "",
        "oauth_client_id": "",
        "oauth_client_secret": "",
        "oauth_completed": False,
    },
    "services": {
        "youtube_enabled": True,
        "soundcloud_enabled": True,
        "vk_enabled": True,
    },
    "session": {
        "last_track_id": None,
        "last_position": 0,
        "last_volume": 70,
        "last_queue": [],
        "last_queue_index": 0,
        "shuffle": False,
        "repeat": "off",
    },
    "subscription": {
        "key": "",
        "valid_until": None,
        "last_validated": None,
        "is_valid": False,
        "signature": "",
    },
    "zapret": {
        "enabled": False,
        "auto_start": False,
        "mode": "youtube_discord",
        "custom_args": "",
        "binary_path": "",
        "autoupdate": False,
    },
}


class SettingsManager:
    """Manages application settings with defaults, persistence, and signals."""

    # Write-behind batching window. Dirty keys reach SQLite at most once per
    # interval instead of one COMMIT per set() call (a volume slider drag emits
    # roughly ten set() calls per second).
    FLUSH_INTERVAL_SECONDS = 0.5

    def __init__(self, db: Any) -> None:
        self.db = db
        self._cache: Dict[str, Dict[str, Any]] = {}
        # _cache and _dirty are touched by the JS bridge thread, background
        # service threads and the zapret thread. Reentrant because get()/set()
        # call themselves for the dotted-key overload.
        self._lock = threading.RLock()
        self._dirty = set()
        # Serialises database writes so two flushes can never interleave.
        self._flush_lock = threading.Lock()
        self._writer_wake = threading.Event()
        self._writer_thread: Optional[threading.Thread] = None
        self._load_all()
        # Session state (the playback queue) is persisted through this class on
        # shutdown, so a dropped flush would lose user data.
        atexit.register(self.flush)

    def _load_all(self):
        """Load settings from database, populating missing values from default schema."""
        stored_all = getattr(self.db, 'get_all_settings', lambda: {})()

        with self._lock:
            for category, defaults in DEFAULT_SETTINGS.items():
                stored = self.db.get_settings_by_category(category)
                self._cache[category] = {}
                for key, default_value in defaults.items():
                    full_key = f"{category}.{key}"
                    if full_key in stored:
                        self._cache[category][key] = stored[full_key]
                    elif key in stored:
                        self._cache[category][key] = stored[key]
                    elif full_key in stored_all:
                        self._cache[category][key] = stored_all[full_key]
                    else:
                        self._cache[category][key] = default_value

            for full_key, value in stored_all.items():
                if not '.' in full_key:
                    continue
                cat, k = full_key.split('.', 1)
                if cat not in self._cache:
                    self._cache[cat] = {}
                self._cache[cat][k] = value

    def _is_known_category(self, category: str) -> bool:
        """True when `category` names a real settings category."""
        if category in DEFAULT_SETTINGS:
            return True
        with self._lock:
            return category in self._cache

    def get(self, category: str, key: Optional[Any] = None, default: Optional[Any] = None) -> Any:
        """Get a setting value.

        Four call conventions are supported:
            get("zapret", "mode", "youtube_discord")
            get("zapret", "mode")
            get("zapret.mode", "youtube_discord")
            get("zapret.mode")
        """
        if "." in category and not self._is_known_category(category):
            # Dotted key: the second positional argument is the default value.
            cat, k = category.split(".", 1)
            if default is None:
                default = key
            return self.get(cat, k, default)

        val = default
        with self._lock:
            if category in self._cache and key in self._cache[category]:
                val = self._cache[category][key]
            elif category in DEFAULT_SETTINGS and key in DEFAULT_SETTINGS[category]:
                val = DEFAULT_SETTINGS[category][key]
            elif key == "queue_autopilot":
                if category in self._cache and "flow_enabled" in self._cache[category]:
                    val = self._cache[category]["flow_enabled"]
                elif category in DEFAULT_SETTINGS and "flow_enabled" in DEFAULT_SETTINGS[category]:
                    val = DEFAULT_SETTINGS[category]["flow_enabled"]
            elif key == "flow_enabled":
                if category in self._cache and "queue_autopilot" in self._cache[category]:
                    val = self._cache[category]["queue_autopilot"]
                elif category in DEFAULT_SETTINGS and "queue_autopilot" in DEFAULT_SETTINGS[category]:
                    val = DEFAULT_SETTINGS[category]["queue_autopilot"]
            elif key == "crossfade_duration_sec":
                if category in self._cache and "crossfade_duration" in self._cache[category]:
                    val = self._cache[category]["crossfade_duration"]
                elif category in DEFAULT_SETTINGS and "crossfade_duration" in DEFAULT_SETTINGS[category]:
                    val = DEFAULT_SETTINGS[category]["crossfade_duration"]
            elif key == "crossfade_duration":
                if category in self._cache and "crossfade_duration_sec" in self._cache[category]:
                    val = self._cache[category]["crossfade_duration_sec"]
                elif category in DEFAULT_SETTINGS and "crossfade_duration_sec" in DEFAULT_SETTINGS[category]:
                    val = DEFAULT_SETTINGS[category]["crossfade_duration_sec"]

        if isinstance(val, str):
            if val.lower() == "true":
                return True
            elif val.lower() == "false":
                return False
        return val

    def set(self, category: str, key: Any = None, value: Any = None) -> None:
        """Set a setting value and schedule it for persistence.

        Supports set('zapret', 'auto_start', True) and set('zapret.auto_start', True).
        The in-memory cache is updated synchronously so readers see the new
        value at once; the database write is batched (see flush()).
        """
        if "." in category and value is None and key is not None:
            cat, k = category.split(".", 1)
            val = key
            return self.set(cat, k, val)

        with self._lock:
            if category not in self._cache:
                self._cache[category] = {}
            self._cache[category][key] = value
            self._dirty.add((category, key))
        self._wake_writer()

    def flush(self) -> None:
        """Persist every pending setting to the database right now.

        Idempotent: with nothing pending it is a no-op, so it is safe to call
        repeatedly and from atexit. Keys whose write fails stay pending so the
        next flush retries them.
        """
        with self._flush_lock:
            with self._lock:
                if not self._dirty:
                    return
                pending = list(self._dirty)
                self._dirty.clear()
                payload = [
                    (f"{cat}.{k}", self._cache.get(cat, {}).get(k), cat)
                    for cat, k in pending
                ]

            try:
                self._write_batch(payload)
            except Exception as e:
                with self._lock:
                    self._dirty.update(pending)
                logger.error(f"Settings flush failed, {len(pending)} keys still pending: {e}")

    def _write_batch(self, payload) -> None:
        """Write a batch of (full_key, value, category) rows in one transaction."""
        batch_writer = getattr(self.db, "set_settings_batch", None)
        if callable(batch_writer):
            batch_writer(payload)
            return
        for full_key, value, category in payload:
            self.db.set_setting(full_key, value, category)

    def _wake_writer(self) -> None:
        """Start the single daemon writer thread if needed, then wake it."""
        with self._lock:
            if self._writer_thread is None or not self._writer_thread.is_alive():
                self._writer_thread = threading.Thread(
                    target=self._writer_loop,
                    name="SettingsWriter",
                    daemon=True,
                )
                self._writer_thread.start()
        self._writer_wake.set()

    def _writer_loop(self) -> None:
        while True:
            self._writer_wake.wait()
            self._writer_wake.clear()
            # Coalesce the burst that follows the first dirty key into a single
            # transaction, and cap the write rate at one batch per interval.
            time.sleep(self.FLUSH_INTERVAL_SECONDS)
            try:
                self.flush()
            except Exception as e:
                logger.error(f"Settings writer thread error: {e}")

    def get_category(self, category: str) -> Dict[str, Any]:
        """Get all settings in a category."""
        with self._lock:
            return self._cache.get(category, DEFAULT_SETTINGS.get(category, {})).copy()

    def reset_category(self, category: str) -> None:
        """Reset a category to defaults."""
        if category in DEFAULT_SETTINGS:
            for key, value in DEFAULT_SETTINGS[category].items():
                self.set(category, key, value)

    def reset_all(self):
        """Reset all settings to defaults."""
        for category in DEFAULT_SETTINGS:
            self.reset_category(category)

    @property
    def theme_name(self) -> str:
        return self.get("theme", "name", "Dark")

    @property
    def theme_mode(self) -> str:
        return self.get("theme", "mode", "dark")

    @property
    def accent_color(self) -> str:
        return self.get("theme", "accent_color", "#6366f1")
    @property
    def volume(self) -> int:
        return self.get("audio", "volume", 70)

    @property
    def border_radius(self) -> int:
        return self.get("interface", "border_radius", "medium")
    @property
    def crossfade_enabled(self) -> bool:
        return self.get("audio", "crossfade_enabled", False)

    @property
    def crossfade_duration(self) -> int:
        return self.get("audio", "crossfade_duration", 3)

    @property
    def gapless(self) -> bool:
        return self.get("audio", "gapless_playback", True)

    @property
    def overlay_mode(self) -> str:
        return self.get("overlay", "mode", "disabled")

    @property
    def font_family(self) -> str:
        return self.get("interface", "font_family", "system")
