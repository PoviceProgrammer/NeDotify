import os
import sys
sys.path.append(os.getcwd())
from core.api import NeDotifyCore

core = NeDotifyCore()
ytmusic = core.get_ytmusic()
try:
    print("Testing get_home(limit=5)...")
    res = ytmusic.get_home(limit=5)
    print("Success! Got", len(res), "sections.")
except Exception as e:
    print("Error:", repr(e))

try:
    print("\nTesting get_home() with no args...")
    res = ytmusic.get_home()
    print("Success! Got", len(res), "sections.")
except Exception as e:
    print("Error:", repr(e))
