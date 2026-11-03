"""Read-only live avatar audit. Does not create AppCore or open a window."""
import json
from pathlib import Path
import sqlite3
import sys
import io
import requests
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.artist_service import ArtistService
from services.youtube_service import YouTubeService
from services.soundcloud_service import SoundCloudService
from core.api import AppApi
from core.database import DatabaseManager
from types import SimpleNamespace


def main():
    path = Path.home() / '.nedotify' / 'nedotify_storage.db'
    database = DatabaseManager(':memory:')
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        db.backup(database.conn)
    names = [row['artist'] for row in database.get_top_artists(10)]
    service = ArtistService(YouTubeService())
    service.submit = lambda task: (task(), True)[1]
    results = {}
    def receive(mapping):
        results.update(mapping)
        print(json.dumps({'resolved': mapping}, ensure_ascii=True), flush=True)
    sc = SoundCloudService()
    api = AppApi.__new__(AppApi)
    api._closed = False
    api._core = SimpleNamespace(db=database, artists=service, youtube=service.youtube, soundcloud=sc)
    api._emit = lambda event, payload: receive(payload['avatars']) if event == 'artists_avatars_ready' else None
    print(json.dumps(api.get_artists_avatars(names)), flush=True)
    print(json.dumps({'requested': names, 'missing': [n for n in names if not results.get(n)]}, ensure_ascii=True), flush=True)
    report = Path(__file__).parent / 'results' / 'artist-avatars-live.json'
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(results, ensure_ascii=True, indent=2), encoding='utf-8')
    for name, url in results.items():
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        with Image.open(io.BytesIO(response.content)) as image:
            image.load()
            print(json.dumps({'decoded_image': name, 'size': image.size}), flush=True)
    for name in names:
        if not results.get(name):
            print(json.dumps({'missing_artist': name}, ensure_ascii=True), flush=True)


if __name__ == '__main__':
    main()
