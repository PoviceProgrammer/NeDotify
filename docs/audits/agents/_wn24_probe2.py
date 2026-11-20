import sys, os, json, tempfile, types
sys.path.insert(0, r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main")

from services.catalog_service import CatalogService
from services.itunes_gateway import ITunesGateway
from services.playlist_import_service import PlaylistImportService, PlaylistImportError

class FakeYT:
    def __init__(self):
        self.albums = {}
        self.hits = []
    def search(self, *a, **k): return self.hits
    def get_artist(self, sid): return {}
    def get_album(self, sid): return self.albums.get(sid, {})
    def get_playlist(self, sid, limit=1): return {'tracks': []}

ITunesGateway.get = classmethod(lambda cls, *a, **k: {'results': []})
yt = FakeYT()
svc = CatalogService(types.SimpleNamespace(_ytmusic=yt))

BAND = 'Earth, Wind & Fire'
yt.albums['MPRE-b'] = {
    'title': 'Rock the Boat',
    'artists': [{'name': BAND, 'id': 'UCband'}],
    'tracks': [{'videoId': 'v1', 'title': 'T1', 'duration_seconds': 100},
               {'videoId': 'v2', 'title': 'T2', 'duration_seconds': 120}],
}

album = {'source': 'youtube', 'source_id': 'MPRE-b', 'title': 'Rock the Boat',
         'artist': BAND, 'artists': [{'name': BAND, 'id': 'UCband'}],
         'artist_channel_id': 'UCband'}

res = svc.album_details(dict(album))
print("album_details for a band whose name contains ',' and '&':")
print("   status =", res.get('status'))
print("   error  =", res.get('error'))
print("   tracks =", res.get('tracks'))

# Same album but artist name without punctuation -> control
OK = 'Kyuss'
yt.albums['MPRE-ok'] = {'title': 'Wretch', 'artists': [{'name': OK, 'id': 'UCok'}],
                        'tracks': [{'videoId': 'v1', 'title': 'T1'}]}
res2 = svc.album_details({'source': 'youtube', 'source_id': 'MPRE-ok', 'title': 'Wretch',
                          'artist': OK, 'artists': [{'name': OK, 'id': 'UCok'}],
                          'artist_channel_id': 'UCok'})
print("control (plain name): status =", res2.get('status'), "tracks =", len(res2.get('tracks') or []))

print()
print("=== PlaylistImportService: JSON with one bad duration ===")
tmp = tempfile.mkdtemp()
p = os.path.join(tmp, "bad.json")
with open(p, 'w', encoding='utf-8') as f:
    json.dump({"name": "My list", "tracks": [
        {"title": "Good One", "artist": "A", "album": "B", "duration": 120.0, "source": "youtube", "source_id": "s1"},
        {"title": "Bad One", "artist": "C", "album": "D", "duration": "3:45", "source": "youtube", "source_id": "s2"},
    ]}, f)
imp = PlaylistImportService()
try:
    out = imp.resolve(p)
    print("resolved name:", out.get('name'))
    for t in out.get('tracks', []):
        print("   track:", {k: t.get(k) for k in ('title','artist','source','source_id')})
except PlaylistImportError as e:
    print("error:", e)

print()
print("=== PlaylistImportService: JSON duration=None ===")
p2 = os.path.join(tmp, "bad2.json")
with open(p2, 'w', encoding='utf-8') as f:
    json.dump({"name": "My list", "tracks": [
        {"title": "Good One", "artist": "A", "duration": 120.0, "source": "youtube", "source_id": "s1"},
        {"title": "Bad One", "artist": "C", "duration": None, "source": "youtube", "source_id": "s2"},
    ]}, f)
try:
    out = imp.resolve(p2)
    print("resolved name:", out.get('name'), "track count:", len(out.get('tracks') or []))
    for t in out.get('tracks', []):
        print("   track:", {k: t.get(k) for k in ('title','artist','source','source_id')})
except PlaylistImportError as e:
    print("error:", e)

print()
print("=== PlaylistImportService: dispatch table ===")
for t in ["https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
          "https://music.yandex.ru/playlist/123",
          "https://vk.com/music?z=1",
          "https://example.com/list.m3u8",
          "https://example.com/list.txt",
          "https://example.com/list.plist",
          "file:///C:/Windows/win.ini",
          "C:/Windows/win.ini",
          "https://soundcloud.com/x/sets/y",
          "https://www.youtube.com/playlist?list=PL1"]:
    try:
        r = imp.resolve(t)
        print(f"  {t[:55]:58s} -> resolved source={r.get('source')!r} name={r.get('name')!r} n={len(r.get('tracks') or [])}")
    except Exception as e:
        print(f"  {t[:55]:58s} -> {type(e).__name__}: {e}")
