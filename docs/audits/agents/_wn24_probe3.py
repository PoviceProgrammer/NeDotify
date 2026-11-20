import sys, os, json, types, time
sys.path.insert(0, r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main")

from services.catalog_service import CatalogService, credited_to
from services.itunes_gateway import ITunesGateway
from services.music_matching import artist_matches, similarity

ITunesGateway.get = classmethod(lambda cls, *a, **k: {'results': []})

class FakeYT:
    def __init__(self): self.albums = {}; self.hits = []
    def search(self, *a, **k): return self.hits
    def get_artist(self, sid): return {}
    def get_album(self, sid): return self.albums.get(sid, {})
    def get_playlist(self, sid, limit=1): return {'tracks': []}

yt = FakeYT()
svc = CatalogService(types.SimpleNamespace(_ytmusic=yt))

print("=== FALSE POSITIVE: album by 'Fire' accepted for artist 'Earth, Wind & Fire' ===")
# album dict WITHOUT artist ids (as it can arrive from JS / DB rows)
yt.albums['MPRE-f'] = {'title': 'Single', 'artists': [{'name': 'Fire', 'id': 'UCfire'}],
                       'tracks': [{'videoId': 'vf', 'title': 'Track F'}]}
album = {'source': 'youtube', 'source_id': 'MPRE-f', 'title': 'Single',
         'artist': 'Earth, Wind & Fire'}          # no artists[] / no artist_channel_id
res = svc.album_details(dict(album))
print("  status =", res.get('status'), " tracks =", [t.get('title') for t in (res.get('tracks') or [])])

print()
print("=== similarity() short-name floor ===")
for a, b in (('ABBA','ABBA'), ('ABBA','ABBA Band'), ('U2','U2'), ('U2','U2 Live'), ('BTS','BTS')):
    print(f"  similarity({a!r},{b!r}) = {similarity(a,b)}")

print()
print("=== smart playlist: corrupt stored rule ===")
from services.smart_playlists import SmartPlaylistService
class FakeDB:
    def __init__(self):
        import sqlite3
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("CREATE TABLE smart_playlists (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, rule_json TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        self.conn.execute("CREATE TABLE tracks (id INTEGER PRIMARY KEY, title TEXT, artist TEXT, album TEXT, duration REAL, added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, last_played TIMESTAMP, play_count INTEGER DEFAULT 0, is_favorite INTEGER DEFAULT 0, is_downloaded INTEGER DEFAULT 0, file_path TEXT, source TEXT, source_id TEXT)")
        self.conn.execute("INSERT INTO smart_playlists(name, rule_json) VALUES ('Broken','{bad')")
        self.conn.execute("INSERT INTO smart_playlists(name, rule_json) VALUES ('OldSchema','{\"days\": 30}')")
        self.conn.commit()
        import threading
        self._write_lock = threading.Lock()
db = FakeDB()
sp = SmartPlaylistService(db)
print("  list() ->", [d['name'] for d in sp.list()])
for pid in (1, 2):
    try:
        sp.tracks(pid)
        print(f"  tracks({pid}) -> ok")
    except Exception as e:
        print(f"  tracks({pid}) -> {type(e).__name__}: {e}")

print()
print("=== smart playlist: artist LIKE wildcard escaping ===")
db.conn.execute("INSERT INTO tracks(title, artist) VALUES ('A','100%_band')")
db.conn.execute("INSERT INTO tracks(title, artist) VALUES ('B','100xxband')")
db.conn.commit()
pl = sp.create("Pct", {"artist": "%_"})
print("  artist='%_' ->", [t['title'] for t in sp.tracks(pl['id'])])
pl2 = sp.create("Inj", {"artist": "' OR 1=1 --"})
print("  artist=injection ->", [t['title'] for t in sp.tracks(pl2['id'])], " total tracks:", db.conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0])
pl3 = sp.create("Back", {"artist": "a\\b"})
print("  artist='a\\b' ->", [t['title'] for t in sp.tracks(pl3['id'])])

print()
print("=== credited_to: name fallback when ids are absent ===")
print("  credited_to({'artists':[{'name':'Fire'}]}, 'Earth, Wind & Fire') =",
      credited_to({'artists':[{'name':'Fire'}]}, 'Earth, Wind & Fire'))
print("  credited_to({'artists':[{'name':'Earth, Wind & Fire'}]}, 'Earth, Wind & Fire') =",
      credited_to({'artists':[{'name':'Earth, Wind & Fire'}]}, 'Earth, Wind & Fire'))
print("  credited_to({'artists':[{'name':'Fire'}]}, 'Earth, Wind & Fire', 'UCewf') =",
      credited_to({'artists':[{'name':'Fire'}]}, 'Earth, Wind & Fire', 'UCewf'))
