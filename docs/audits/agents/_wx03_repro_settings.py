"""WX-03 reproduction: which DEFAULT_SETTINGS categories survive AppApi.get_settings().

Uses the REAL core/settings.py (SettingsManager + DEFAULT_SETTINGS) and the REAL
core/api.py AppApi.get_settings / get_settings_by_category (called unbound with a
stub core, because AppApi.__init__ spins up thread pools).
"""
import sys, types, json
sys.stdout.reconfigure(encoding='utf-8')
ROOT = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main"
sys.path.insert(0, ROOT)

from core.settings import SettingsManager, DEFAULT_SETTINGS
from core.api import AppApi


class FakeDb:
    def __init__(self):
        self.rows = {}
    def get_all_settings(self):
        return dict(self.rows)
    def set_settings_batch(self, items):
        for k, v, c in items:
            self.rows[k] = v
        return len(items)


class StubCore:
    def __init__(self, settings):
        self.settings = settings


db = FakeDb()
sm = SettingsManager(db)
api_stub = types.SimpleNamespace(_core=StubCore(sm))

# Simulate a user who turned offline mode ON and saved a custom hotkey.
sm.set("network", "offline_mode", True)
sm.set("hotkeys", "like", "KeyJ")
sm.set("player", "queue_autopilot", False)
sm.sync_flush_now()

full = AppApi.get_settings(api_stub)
print("AppApi.get_settings() -> categories:", sorted(full.keys()))
print()
print("DEFAULT_SETTINGS categories          :", sorted(DEFAULT_SETTINGS.keys()))
print()
missing = sorted(set(DEFAULT_SETTINGS) - set(full))
extra = sorted(set(full) - set(DEFAULT_SETTINGS))
print("IN DEFAULT_SETTINGS BUT MISSING FROM get_settings():", missing)
print("IN get_settings() BUT NOT IN DEFAULT_SETTINGS     :", extra)
print()
print("network in get_settings()      :", "network" in full, "->", full.get("network"))
print("network via get_settings_by_category('network'):",
      AppApi.get_settings_by_category(api_stub, "network"))
print()
print("hotkeys from get_settings()    :", full.get("hotkeys"))
print("hotkeys via get_settings_by_category:", AppApi.get_settings_by_category(api_stub, "hotkeys"))
print()
print("session.shuffle / session.repeat in get_settings():",
      full.get("session", {}).get("shuffle"), "/", full.get("session", {}).get("repeat"))
print("top-level 'shuffle'/'repeat' in get_settings():",
      full.get("shuffle"), "/", full.get("repeat"))
print("top-level 'volume' in get_settings():", full.get("volume"),
      "| audio.volume =", full.get("audio", {}).get("volume"))
print()
print("player category present:", "player" in full, "->", full.get("player"))
print()
# --- the alias fallbacks in SettingsManager.get() are unreachable -------------
print("--- alias fallback reachability ---")
print("cache has audio.crossfade_duration   :", "crossfade_duration" in sm._cache["audio"])
print("cache has audio.crossfade_duration_sec:", "crossfade_duration_sec" in sm._cache["audio"])
sm.set("audio", "crossfade_duration_sec", 12)
print("get('audio','crossfade_duration')     :", sm.get("audio", "crossfade_duration", 3),
      "(the alias to crossfade_duration_sec never fires)")
print("get('audio','crossfade_duration_sec') :", sm.get("audio", "crossfade_duration_sec", 3))
print()
sm.set("audio", "flow_enabled", False)
print("get('audio','queue_autopilot')        :", sm.get("audio", "queue_autopilot", True),
      "(alias to flow_enabled never fires)")
