"""Live public lyric adapters and the user's public SoundCloud reupload.

Creates a disposable profile; reports identity/timings/lengths, never lyric text
or signed URLs. This is an opt-in diagnostic, not an offline regression test.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    with tempfile.TemporaryDirectory(prefix='nedotify-lyrics-coverage-') as folder:
        for name in ('USERPROFILE', 'HOME', 'APPDATA', 'LOCALAPPDATA'):
            os.environ[name] = folder
        from services.lyrics_service import LyricsService
        from services.lyrics_metadata import lyrics_metadata
        service = LyricsService(cache_path=Path(folder) / 'lyrics.db')
        engine = service._lookup
        results = []

        def measure(label, action):
            start, cpu = time.monotonic(), time.process_time()
            try:
                data = action() or {}
                result = {k: data.get(k) for k in ('status', 'source', 'matched_title', 'matched_artist',
                    'matched_duration', 'match_type', 'syncType', 'identity_recovered', 'identity_evidence') if k in data}
                result.update(found=data.get('status') == 'found', characters=len(data.get('plainLyrics') or ''),
                              synced=bool(data.get('syncedLyrics')))
            except Exception as exc:
                result = {'found': False, 'error': type(exc).__name__, 'http_status': getattr(exc, 'code', None)}
            result.update(case=label, ms=round((time.monotonic() - start) * 1000),
                          process_cpu_ms=round((time.process_time() - cpu) * 1000))
            results.append(result)
            print(json.dumps(result, ensure_ascii=True), flush=True)

        for name, title, artist, duration in (
                ('ovh', 'Never Gonna Give You Up', 'Rick Astley', 213),
                ('better_qq', 'Never Gonna Give You Up', 'Rick Astley', 213),
                ('kugou', '晴天', '周杰伦', 265.072)):
            form = {'metadata': lyrics_metadata(title, artist), 'query_title': title,
                    'query_artist': artist, 'duration': duration, 'album': '', 'fallback': False}
            measure(name, lambda name=name, form=form: getattr(engine.public, name)(
                form, time.monotonic() + engine.BUDGET, lambda result: None))
        # The public SoundCloud id and its duration were read from the existing
        # library without changing it. The screenshot's uploader is not an artist.
        for label in ('upload-cold', 'upload-memory-cache'):
            measure(label, lambda: service.get_lyrics('Сукины дети', 'Danzal_Parkour', 219057,
                source='soundcloud', source_id='303974832'))
        report = {'actual_network': True, 'profile': 'disposable', 'models': False, 'results': results}
        out = ROOT / 'tools/bench/results' / ('lyrics-coverage-' + time.strftime('%Y%m%d-%H%M%S') + '.json')
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'artifact': str(out), 'all_found': all(r['found'] for r in results)}, ensure_ascii=True))
        service.shutdown_executor(wait=True)
        return 0 if all(r['found'] for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
