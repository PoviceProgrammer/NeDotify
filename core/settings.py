"""
NeDotify - Settings Manager
Centralized settings with default values, database storage, and convenient getters/setters.
"""

from typing import Any, Dict, Optional
import platform
import os








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
        "quality": "high",
        "gapless_playback": False,
        "crossfade_enabled": False,
        "crossfade_duration": 3,
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

    def __init__(self, db: Any) -> None:
        self.db = db
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._load_all()

    def _load_all(self):
        """Load settings from database, populating missing values from default schema."""
        stored_all = getattr(self.db, 'get_all_settings', lambda: {})()

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

    def get(self, category: str, key: Optional[Any] = None, default: Optional[Any] = None) -> Any:
        """Get a setting value, supporting both (category, key, default) and ('category.key', default)."""
        if "." in category and key is not None and default is None and not isinstance(key, str):
            default = key
            cat, k = category.split(".", 1)
            return self.get(cat, k, default)
        elif "." in category and key is None:
            cat, k = category.split(".", 1)
            return self.get(cat, k, default)

        if category in self._cache and key in self._cache[category]:
            return self._cache[category][key]
        if category in DEFAULT_SETTINGS and key in DEFAULT_SETTINGS[category]:
            return DEFAULT_SETTINGS[category][key]
        return default

    def set(self, category: str, key: Any = None, value: Any = None) -> None:
        """Set a setting value and persist it. Supports set('zapret', 'auto_start', True) and set('zapret.auto_start', True)."""
        if "." in category and value is None and key is not None:
            cat, k = category.split(".", 1)
            val = key
            return self.set(cat, k, val)

        if category not in self._cache:
            self._cache[category] = {}
        self._cache[category][key] = value
        self.db.set_setting(f"{category}.{key}", value, category)

    def get_category(self, category: str) -> Dict[str, Any]:
        """Get all settings in a category."""
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
