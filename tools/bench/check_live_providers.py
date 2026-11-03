"""Probe real provider search, resolution and first audio bytes without a library.

Run with the project interpreter. Uses anonymous/direct access and an isolated
profile; does not start the UI or prove that WebView decoded/played the audio.
"""
import argparse
import json
import os
import shutil
import subprocess
import re
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from urllib.parse import urlencode, urljoin

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="Rick Astley Never Gonna Give You Up")
    parser.add_argument("--provider", choices=("youtube", "soundcloud", "spotify"))
    parser.add_argument("--decode", action="store_true", help="Decode one second with installed ffmpeg")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="nedotify-provider-check-") as scratch:
        os.environ["USERPROFILE"] = scratch
        os.environ["HOME"] = scratch
        import urllib.request
        from core.proxy import LocalProxyManager
        from services.youtube_service import YouTubeService
        from services.soundcloud_service import SoundCloudService
        from services.spotify_service import SpotifyService

        services = {
            "youtube": YouTubeService(),
            "soundcloud": SoundCloudService(),
            "spotify": SpotifyService(),
        }
        proxy = LocalProxyManager(SimpleNamespace(**services, settings=None))
        proxy.start()
        try:
            for name, service in services.items():
                if args.provider and name != args.provider:
                    continue
                start = time.monotonic()
                done = threading.Event()
                results, errors = [], []

                def success(tracks, results=results, done=done):
                    results.extend(tracks)
                    done.set()

                def failure(error, errors=errors, done=done):
                    errors.append(str(error))
                    done.set()

                limit = {"limit": 3} if name == "spotify" else {"max_results": 3}
                service.search(args.query, callback=success, error_callback=failure, **limit)
                done.wait(25)
                report = {"provider": name, "search_seconds": round(time.monotonic() - start, 3),
                          "results": len(results), "errors": errors}
                print(json.dumps(report, ensure_ascii=False), flush=True)
                if not results:
                    continue
                track = results[0]
                start = time.monotonic()
                # Match AppCore's interactive route (Spotify uses ytsearch1).
                resolved = []
                ready = threading.Event()
                provider = services["youtube"] if name == "spotify" else service
                provider.get_stream_url(
                    track["source_id"],
                    callback=lambda url, meta, out=resolved, event=ready: (out.append(url), event.set()),
                    error_callback=lambda error, out=errors, event=ready: (out.append(str(error)), event.set()))
                ready.wait(40)
                url = resolved[0] if resolved else None
                report.update(title=track.get("title"), source=track.get("source"),
                              resolve_seconds=round(time.monotonic() - start, 3),
                              resolved=bool(url))
                if url:
                    start = time.monotonic()
                    try:
                        media_url = f"http://127.0.0.1:{proxy.port}/?" + urlencode(
                            {"url": url, "source": name, "k": proxy.token})
                        playback_url = media_url
                        for _ in range(4):
                            with urllib.request.urlopen(media_url, timeout=55) as response:
                                content_type = response.headers.get("Content-Type", "")
                                if 'mpegurl' in content_type:
                                    playlist = response.read(2 * 1024 * 1024).decode()
                                    paths = [line for line in playlist.splitlines()
                                             if line and not line.startswith('#')]
                                    if not paths:
                                        raise ValueError("Empty HLS playlist")
                                    media_url = urljoin(media_url, paths[0])
                                    report["hls"] = True
                                    report["player_recognizes_hls"] = '.m3u8' in url or '/playlist' in url
                                    continue
                                chunk = response.read(4096)
                                report.update(status=response.status,
                                              content_type=content_type,
                                              first_bytes=len(chunk),
                                              first_bytes_seconds=round(time.monotonic() - start, 3))
                                break
                        if args.decode:
                            ffmpeg = shutil.which("ffmpeg")
                            if not ffmpeg:
                                report["decode_error"] = "ffmpeg unavailable"
                            else:
                                decoded = subprocess.run(
                                    [ffmpeg, "-v", "error",
                                     *(["-allowed_extensions", "ALL",
                                        "-allowed_segment_extensions", "ALL",
                                        "-extension_picky", "0"] if report.get("hls") else []),
                                     "-i", playback_url, "-map", "0:a:0",
                                     "-t", "1", "-f", "null", "-"],
                                    capture_output=True, timeout=50,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                                report["decoded_one_second"] = decoded.returncode == 0
                                if decoded.returncode:
                                    report["decode_error"] = re.sub(
                                        r'https?://\S+', '<media-url>',
                                        decoded.stderr.decode(errors='replace'))[:1000]
                    except Exception as exc:
                        # Signed CDN URLs contain tokens; do not print exceptions' URLs.
                        report["media_error"] = type(exc).__name__
                    start = time.monotonic()
                    warm = []
                    ready = threading.Event()
                    provider.get_stream_url(
                        track["source_id"],
                        callback=lambda url, meta, out=warm, event=ready: (out.append(url), event.set()),
                        error_callback=lambda error, event=ready: event.set())
                    ready.wait(15)
                    report["warm_resolved"] = bool(warm)
                    report["warm_resolve_seconds"] = round(time.monotonic() - start, 3)
                print(json.dumps(report, ensure_ascii=False), flush=True)
        finally:
            proxy.stop()
            for service in services.values():
                service._executor.shutdown(wait=True, cancel_futures=True)


if __name__ == "__main__":
    main()
