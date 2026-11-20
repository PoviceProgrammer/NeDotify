"""WN-08 (Role A) verification harness. Read-only w.r.t. the repo."""
import os
import sys
import types

PROJECT_ROOT = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main"
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from core.api import AppApi
from core.settings import SettingsManager, DEFAULT_SETTINGS


class FakeDB:
    def get_all_settings(self):
        return {}

    def set_settings_batch(self, items):
        return len(items)

    def set_setting(self, key, value, category="general"):
        pass


class FakeScanner:
    _covers_dir = os.path.join(os.path.expanduser("~"), ".nedotify", "covers")


def build():
    settings = SettingsManager(FakeDB())
    core = types.SimpleNamespace(
        db=FakeDB(),
        settings=settings,
        cache=None,
        scanner=FakeScanner(),
    )
    api = AppApi(core)
    api._emit = lambda *a, **k: None
    return api, settings


print("=" * 78)
print("1) get_settings() omits DEFAULT_SETTINGS categories")
api, settings = build()
full = api.get_settings()
missing = sorted(set(DEFAULT_SETTINGS) - set(full))
print("   categories returned :", len(full))
print("   MISSING from bridge :", missing)
print("   'network' in result :", "network" in full)
print("   settings layer still has it:",
      settings.get_category("network"))

print()
print("=" * 78)
print("2) save_setting('autostart', ...) ignores update_autostart() failure")
api, settings = build()
calls = []


def boom(enabled):
    calls.append(enabled)
    return False


api.update_autostart = boom
res = api.save_setting("autostart", True, "app")   # category is NOT 'general'
print("   save_setting returned      :", res)
print("   update_autostart called    :", calls)
print("   stored general.autostart   :", settings.get("general", "autostart"))
print("   stored app.autostart       :", settings.get("app", "autostart"))
print("   -> bridge reports success while the registry was never touched")

print()
print("=" * 78)
print("3) complete_onboarding stores None for accent_color / audio_device")
api, settings = build()
res = api.complete_onboarding({"accent_color": None, "audio_device": None})
print("   result                :", res)
print("   theme.accent_color    :", repr(settings.get("theme", "accent_color")))
print("   audio.output_device   :", repr(settings.get("audio", "output_device")))
print("   theme.theme untouched :", repr(settings.get("theme", "theme")))

print()
print("=" * 78)
print("4) set_equalizer([]) does not clear the stored bands")
api, settings = build()
api.set_equalizer(3.0, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
print("   after set  :", settings.get("equalizer", "bands"))
api.set_equalizer(0.0, [])
print("   after []   :", settings.get("equalizer", "bands"))
print("   get_equalizer ->", api.get_equalizer())

print()
print("=" * 78)
print("5) set_cache_quota(100) (bare positional > 64) -> MB heuristic")
api, settings = build()
res = api.set_cache_quota(100)
print("   result            :", res)
print("   cache_quota_gb    :", settings.get("storage", "cache_quota_gb"))
print("   cache_size_mb     :", settings.get("storage", "cache_size_mb"))
print("   -> asked for 100 GB, stored as", settings.get("storage", "cache_quota_gb"), "GB")

print()
print("=" * 78)
print("6) set_cache_quota(5) (the value the UI select sends)")
api, settings = build()
res = api.set_cache_quota(5)
print("   cache_quota_gb    :", settings.get("storage", "cache_quota_gb"))
print("   cache_size_mb     :", settings.get("storage", "cache_size_mb"))
