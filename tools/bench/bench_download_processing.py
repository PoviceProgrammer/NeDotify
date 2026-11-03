"""Measure artwork/conversion overlap using real FFmpeg and a disposable profile.

Artwork IO has a fixed synthetic delay. This measures pipeline latency, not CDN
bandwidth. The resulting MP3s must have identical encoded audio, tags and cover.
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise RuntimeError('Actual FFmpeg is required for this benchmark')
    with tempfile.TemporaryDirectory(prefix='nedotify-processing-bench-') as directory:
        for key in ('USERPROFILE', 'HOME', 'LOCALAPPDATA', 'APPDATA'):
            os.environ[key] = directory
        from core.download_transfer import DownloadContext
        from core.download_processing import OutputPolicy, process_download
        from mutagen.mp3 import MP3
        cover = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aOZkAAAAASUVORK5CYII=')
        fixture = Path(directory) / 'fixture.wav'
        with wave.open(str(fixture), 'wb') as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(44100)
            # Deterministic quiet square wave, never rendered to an audio device.
            audio.writeframes((b'\x10\x00' * 50 + b'\xf0\xff' * 50) * (44100 * 30 // 100))
        result, hashes = {}, set()
        with ThreadPoolExecutor(max_workers=1) as pool:
            for mode in ('serial_artwork', 'overlapped_artwork'):
                samples, bitrates = [], []
                for rep in range(5):
                    folder = Path(directory) / f'{mode}-{rep}'
                    folder.mkdir()
                    ctx = DownloadContext(rep, 'fixture', 'song', lambda: None, lambda *args: None)
                    ctx.tools = {'ffmpeg_path': ffmpeg}
                    source = folder / (ctx.stem + '.wav')
                    shutil.copyfile(fixture, source)
                    def artwork():
                        time.sleep(.3)
                        return cover, 'image/png'
                    start = time.perf_counter()
                    future = pool.submit(artwork)
                    image = future.result() if mode == 'serial_artwork' else lambda: future.result(timeout=7)
                    final, warnings = process_download(str(source), {'id': rep, 'title': 'Fixture', 'artist': 'NeDotify'},
                        OutputPolicy(format='mp3'), ctx, str(folder), image)
                    samples.append((time.perf_counter() - start) * 1000)
                    audio = MP3(final)
                    assert audio.info.length >= 29.9 and audio.tags['TIT2'].text == ['Fixture']
                    assert audio.tags.getall('APIC')[0].data == cover and not warnings
                    bitrates.append(audio.info.bitrate)
                    digest = subprocess.run([ffmpeg, '-v', 'error', '-i', final, '-map', '0:a:0', '-c:a', 'copy',
                        '-f', 'hash', '-hash', 'sha256', '-'], check=True, capture_output=True,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout.strip().decode()
                    hashes.add(digest)
                result[mode] = {'repetitions': 5, 'median_ms': round(statistics.median(samples), 3),
                                'samples_ms': samples, 'bitrates': bitrates}
        assert len(hashes) == 1, 'Optimization changed encoded audio'
        result.update(workload='30s real WAV to 320kbps MP3; 300ms optional artwork latency',
                      identical_encoded_audio=True, cover_embedded=True, tags_verified=True)
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result))


if __name__ == '__main__':
    main()
