"""Live public artist search/profile/image checks in a disposable profile."""
import concurrent.futures
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    with tempfile.TemporaryDirectory(prefix='nedotify-artist-audit-') as folder:
        for key in ('HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA'):
            os.environ[key] = folder
        from services.youtube_service import YouTubeService
        from services.artist_service import ArtistService
        from services.music_matching import normalize
        import requests
        from PIL import Image

        youtube = YouTubeService()
        artists = ArtistService(youtube)

        def check(name):
            started = time.monotonic()
            result = {'query': name}
            rows = youtube.search_sync(name, limit=8, result_type='artists', timeout=12)
            result['searchResults'] = len(rows)
            # Open an explicit exact-name result as a user clicking its card would.
            exact = [r for r in rows if normalize(r.get('name') or r.get('artist') or r.get('title')) == normalize(name)]
            result['exactMatches'] = len(exact)
            if not exact:
                result['resultNames'] = [r.get('name') or r.get('artist') or r.get('title') for r in rows]
                return result
            ref = exact[0]
            done = threading.Event()
            profiles, errors = [], []
            artists.get_profile(name, artist_ref=ref,
                callback=lambda p: (profiles.append(p), done.set()),
                error_callback=lambda e: (errors.append(e.get('status') if isinstance(e, dict) else type(e).__name__), done.set()))
            result['profileCompleted'] = done.wait(18)
            result['errors'] = errors
            if profiles:
                profile = profiles[0]
                result.update(status=profile.get('status'), resolvedName=profile.get('name'),
                              source=profile.get('source'), sourceId=profile.get('source_id'),
                              bioCharacters=len(profile.get('bio') or ''),
                              tracks=len(profile.get('tracks') or []), albums=len(profile.get('albums') or []),
                              hasMore=profile.get('tracks_has_more'))
                avatar = profile.get('avatar_url')
                result['avatarPresent'] = bool(avatar)
                if avatar:
                    try:
                        with requests.get(avatar, timeout=8, stream=True) as response:
                            response.raise_for_status()
                            data = response.raw.read(5 * 1024 * 1024)
                            with Image.open(io.BytesIO(data)) as image:
                                image.load()
                                result['imageSize'] = list(image.size)
                    except Exception as exc:
                        result['imageError'] = type(exc).__name__
                if profile.get('source_id'):
                    page = artists.get_tracks_page(profile)
                    result['nextPageTracks'] = len(page.get('tracks') or [])
            result['seconds'] = round(time.monotonic() - started, 2)
            print(json.dumps(result, ensure_ascii=True), flush=True)
            return result

        try:
            names = ['королевский XVII', 'madk1d', '9mice', 'LOVV66', 'PHARAOH', 'Radiohead']
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(check, names))
            out = ROOT / 'tools/bench/results/artist-search-audit-20261110.json'
            out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        finally:
            youtube.shutdown_executor()


if __name__ == '__main__':
    main()
