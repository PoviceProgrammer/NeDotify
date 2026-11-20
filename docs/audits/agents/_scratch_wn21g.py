"""Scratch #7: Last.fm API-key resolution vs the module-global API_KEYS."""
import os
import sys

REPO = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main"
sys.path.insert(0, REPO)

import services.lastfm_service as lf  # noqa: E402
from services.lastfm_service import LastFMService, _split_keys, API_KEYS  # noqa: E402


class FakeSettings:
    def __init__(self, value=""):
        self.value = value

    def get(self, category, key, default=None):
        if (category, key) == ("auth", "lastfm_api_key"):
            return self.value
        return default


os.environ.pop("LASTFM_API_KEY", None)
lf.API_KEYS.clear()

print("=" * 78)
print("(a) service created with NO key, then the user adds one at runtime")
print("=" * 78)
s = FakeSettings("")
svc = LastFMService(settings=s)
print(f"  after construction: available={svc.available}  API_KEYS={lf.API_KEYS}")
s.value = "abc123"                     # user sets the key in Settings
print(f"  after user sets a key in settings:")
print(f"    recommendation_service._lastfm_enabled() -> {bool(svc._resolve_api_keys())}")
print(f"    LastFMService.available                  -> {svc.available}")
print(f"    API_KEYS (module global)                 -> {lf.API_KEYS}")
print(f"  -> _api_request() short-circuits on `not self.available`: "
      f"no network call is made.")

print()
print("=" * 78)
print("(b) service created WITH a key")
print("=" * 78)
lf.API_KEYS.clear()
s2 = FakeSettings("key-one")
svc2 = LastFMService(settings=s2)
print(f"  available={svc2.available}  API_KEYS={lf.API_KEYS}")

print()
print("=" * 78)
print("(c) LastFMService.API_KEYS is a CLASS attribute, not the module global")
print("=" * 78)
print(f"  'API_KEYS' in LastFMService.__dict__      -> {'API_KEYS' in LastFMService.__dict__}")
print(f"  getattr(LastFMService, 'API_KEYS', None)   -> {getattr(LastFMService, 'API_KEYS', None)}")
print(f"  module global lf.API_KEYS                  -> {lf.API_KEYS}")
print("  -> tools/bench/bench_child.py sets LastFMService.API_KEYS = [...] ; that")
print("     creates a NEW class attribute and does NOT touch the global the")
print("     service actually reads.")

print()
print("=" * 78)
print("(d) _split_keys")
print("=" * 78)
print(f"  'a,b;c'  -> {_split_keys('a,b;c')}")
print(f"  ' a , b '-> {_split_keys(' a , b ')}")
print(f"  ''       -> {_split_keys('')}")
print(f"  None     -> {_split_keys(None)}")
print(f"  set      -> {_split_keys({'k3', 'k1', 'k2'})}   (order is NOT deterministic)")
print(f"  list     -> {_split_keys(['k1', 'k2'])}")

print()
print("=" * 78)
print("(e) key rotation with 2 keys")
print("=" * 78)
lf.API_KEYS.clear()
s3 = FakeSettings("k1,k2")
svc3 = LastFMService(settings=s3)
print(f"  API_KEYS={lf.API_KEYS}")
print(f"  sequence: {[svc3._get_next_api_key() for _ in range(5)]}")
svc3._mark_bad_key("k1")
print(f"  after _mark_bad_key('k1'): {[svc3._get_next_api_key() for _ in range(4)]}")
print(f"  available={svc3.available}")
