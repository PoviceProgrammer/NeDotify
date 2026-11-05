"""Prepare reproducible music (not speech-only) ASR fixtures in a scratch profile."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import requests

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, default=ROOT / '.audit/lyrics-asr/corpus')
    args = parser.parse_args()
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        raise RuntimeError('Prototype preparation requires FFmpeg and ffprobe')
    sys.path.insert(0, str(ROOT))
    files = []
    def convert(name, source=None, offset=0, seconds=None, filters=None):
        output = directory / (name + '.wav')
        if not output.exists():
            options = ['-ss', str(offset), '-i', str(source)] if source else ['-f', 'lavfi', '-i', 'anullsrc=r=16000:cl=mono']
            if seconds is not None:
                options += ['-t', str(seconds)]
            if filters:
                options += ['-af', filters]
            subprocess.run([ffmpeg, '-v', 'error', '-nostdin', '-y', *options, '-ac', '1', '-ar', '16000',
                            '-c:a', 'pcm_s16le', str(output)], check=True, timeout=120,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        import wave
        with wave.open(str(output)) as audio:
            duration = audio.getnframes() / audio.getframerate()
        files.append({'name': name, 'path': output.name, 'duration_sec': duration,
                      'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
                      'offset_sec': offset, 'filters': filters})
    with tempfile.TemporaryDirectory(prefix='nedotify-asr-fixtures-') as profile:
        for key in ('HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA'):
            os.environ[key] = profile
        from services.youtube_service import YouTubeService
        service = YouTubeService()
        for name, target in [('english', 'dQw4w9WgXcQ'),
                             ('russian', 'ytsearch1:Кино Группа крови оригинал'),
                             ('rap', 'ytsearch1:Eminem Lose Yourself official audio')]:
            candidates = list(directory.glob(name + '-source.*'))
            candidates = [p for p in candidates if not p.name.endswith(('.part', '.json'))]
            if candidates:
                path = candidates[0]
            else:
                print(f'Downloading public fixture: {name}', flush=True)
                path = Path(service.download_audio_sync(target, str(directory)))
                destination = directory / (name + '-source' + path.suffix)
                path.replace(destination)
                path = destination
            convert(name + '_full', path)
            convert(name + '_clip', path, offset=35, seconds=30)
            if name == 'english':
                convert('distorted_clip', path, offset=35, seconds=30,
                        filters='aecho=0.8:0.8:60:0.35,lowpass=f=2600,volume=1.8,alimiter=limit=0.65')
    instrumental = directory / 'instrumental-source.mp3'
    if not instrumental.exists():
        response = requests.get('https://incompetech.com/music/royalty-free/mp3-royaltyfree/Carefree.mp3', timeout=30)
        response.raise_for_status()
        instrumental.write_bytes(response.content)
    convert('instrumental_clip', instrumental, seconds=30)
    convert('silence', seconds=15)
    manifest = {'schema': 1, 'description': 'Public music recordings; transformed excerpt is explicitly labeled.',
                'files': files, 'instrumental_source': 'https://incompetech.com/music/royalty-free/index.html?isrc=USUAN1400037'}
    (directory / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Corpus ready: ' + str(directory / 'manifest.json'), flush=True)


if __name__ == '__main__':
    main()
