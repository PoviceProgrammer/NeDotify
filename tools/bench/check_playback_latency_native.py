"""Live click-to-decoded-audio latency through both real Windows UIs.

Uses a separate profile, actual providers, AppApi, proxy and WebView audio.
No fabricated media, callback substitutes or provider requests in the parent.
"""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import subprocess
import sqlite3
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
TRACE = []
TRACKS = [
    {'source': 'soundcloud', 'source_id': '2215597907', 'title': 'пьяный дождь ( mylancore )', 'artist': 'v3lvet', 'duration': 126},
    {'source': 'soundcloud', 'source_id': '2104544877', 'title': 'G Sound - На душе', 'artist': '141', 'duration': 117},
    {'source': 'soundcloud', 'source_id': '2331544133', 'title': 'ZELENUYU (ultra slowed)', 'artist': 'HELLBLADE', 'duration': 170},
    {'source': 'soundcloud', 'source_id': '2289890927', 'title': 'face + xsonsss - rock star & dancing nihilist', 'artist': 'xsonsss', 'duration': 163},
    {'source': 'youtube', 'source_id': 'dQw4w9WgXcQ', 'title': 'Never Gonna Give You Up', 'artist': 'Rick Astley', 'duration': 213},
    {'source': 'spotify', 'source_id': 'ytsearch1: Rick Astley - Never Gonna Give You Up', 'title': 'Never Gonna Give You Up', 'artist': 'Rick Astley', 'duration': 213},
    {'source': 'deezer', 'source_id': '3135556', 'title': 'Harder, Better, Faster, Stronger', 'artist': 'Daft Punk', 'duration': 226},
]


def instrument():
    from services.soundcloud_service import SoundCloudService
    from services.deezer_service import DeezerService
    from yt_dlp import YoutubeDL
    from utils import url_safety

    def wrap(cls, name):
        original = getattr(cls, name)
        def timed(self, *args, **kwargs):
            start = time.monotonic()
            cpu_start = time.thread_time()
            record = {'stage': name, 'thread': threading.current_thread().name, 'started': start}
            if name == 'urlopen' and args:
                request = args[0]
                parsed = urlsplit(request if isinstance(request, str) else request.url)
                record['host'] = parsed.hostname
                record['path'] = parsed.path if parsed.path in ('/watch', '/youtubei/v1/player', '/iframe_api') else '<redacted>'
            try:
                result = original(self, *args, **kwargs)
                if isinstance(result, bool):
                    record['result'] = result
                elif hasattr(result, 'status_code'):
                    record['status'] = result.status_code
                return result
            except Exception as exc:
                record['exception_type'] = type(exc).__name__
                raise
            finally:
                record['ms'] = round((time.monotonic() - start) * 1000, 1)
                record['thread_cpu_ms'] = round((time.thread_time() - cpu_start) * 1000, 1)
                TRACE.append(record)
        setattr(cls, name, timed)

    for name in ('_get_client_id', '_api_get', '_public_json', '_media_url_is_servable'):
        wrap(SoundCloudService, name)
    wrap(YoutubeDL, 'extract_info')
    wrap(YoutubeDL, 'urlopen')
    wrap(url_safety._PublicHTTPSConnection, 'connect')
    wrap(DeezerService, '_get')
    original_open = url_safety._pooled_open
    def pooled_open(req, *args, **kwargs):
        started = time.monotonic()
        record = {'stage': 'pooled_response_headers', 'host': urlsplit(req.full_url).hostname,
                  'thread': threading.current_thread().name, 'started': started}
        try:
            return original_open(req, *args, **kwargs)
        except Exception as exc:
            record['exception_type'] = type(exc).__name__
            raise
        finally:
            record['ms'] = round((time.monotonic() - started) * 1000, 1)
            TRACE.append(record)
    url_safety._pooled_open = pooled_open


def scenario(ctx):
    results = []
    tracks = json.loads(os.environ.get('NEDOTIFY_LATENCY_TRACKS', 'null')) or TRACKS
    skins = os.environ.get('NEDOTIFY_LATENCY_SKINS', 'current,macos').split(',')
    for style in skins:
        ctx.js_async(r'''async style => {
            const api=window.pywebview.api;
            await api.save_setting('ui_style',style,'interface');
            const settings=await import(new URL('./js/settings.js',location.href));
            settings.applySettingsFromBackend(await api.get_settings());
            return true;
        }''', json.dumps(style))
        for track in tracks:
            started = time.monotonic()
            result = ctx.js_async(r'''async track => {
                const api=window.pywebview.api;
                const player=await import(new URL('./js/player.js',location.href));
                const start=performance.now();
                const response=await api.play_track(track,[track],0);
                const bridgeMs=performance.now()-start;
                if(!response?.success)throw Error('Actual play_track rejected');
                const deadline=start+20000;
                while(performance.now()<deadline){
                    const selected=player.getCurrentTrack();
                    const clock=player.getLyricsPlaybackClock();
                    if(String(selected?.source_id)===track.source_id &&
                       !clock.paused&&!clock.buffering&&clock.positionMs>100){
                        const firstMs=performance.now()-start;
                        await new Promise(r=>setTimeout(r,300));
                        const after=player.getLyricsPlaybackClock();
                        if(after.positionMs>clock.positionMs+100&&!after.paused&&!after.buffering){
                            await api.play_pause();
                            return {source:track.source,source_id:track.source_id,playing:true,
                                time_to_audio_ms:Math.round(firstMs),bridge_ms:Math.round(bridgeMs),
                                within_5s:firstMs<=5000,within_3s:firstMs<=3000};
                        }
                    }
                    await new Promise(r=>setTimeout(r,50));
                }
                const selected=player.getCurrentTrack();
                let host=null;
                try{host=new URL(new URL(selected?.stream_url||'',location.href).searchParams.get('url')).hostname}catch{}
                const result={source:track.source,source_id:track.source_id,playing:false,
                    within_5s:false,error:'No advancing decoded audio within 20 seconds',
                    bridge_ms:Math.round(bridgeMs),clock:player.getLyricsPlaybackClock(),host,
                    console_errors:(window.__bench?.consoleErrors||[]).slice(-5).map(v=>String(v).replace(/https?:\/\/\S+/g,'<url>'))};
                player.stopPlaybackForQueueEnd();
                return result;
            }''', json.dumps(track), timeout=30)
            result['style'] = style
            result['stages'] = [r for r in TRACE if r['started'] >= started]
            results.append(result)
            print('[latency] ' + json.dumps({k: v for k, v in result.items() if k not in ('stages', 'console_errors')}, ensure_ascii=True), flush=True)
    return {'actual_bridge': True, 'api_stubs': False, 'results': results,
            'all_within_5s': all(r.get('within_5s') for r in results),
            'note': 'First advancing decoded media clock, physical speaker output not assessed'}


def main():
    if '--child' in sys.argv:
        instrument()
        from tools.bench import bench_child
        bench_child.scenarios.scenario_startup = scenario
        bench_child.main()
        return 0
    from tools.bench import profile
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skin-order', choices=('current,macos', 'macos,current'), default='current,macos')
    parser.add_argument('--source', choices=('all', 'soundcloud', 'youtube', 'spotify', 'deezer'), default='all')
    parser.add_argument('--compact', action='store_true')
    parser.add_argument('--seed-user-cache', action='store_true',
                        help='Read only: copy relevant URL cache rows into the disposable profile')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='nedotify-latency-') as folder:
        scratch = Path(folder)
        out = ROOT / 'tools/bench/results' / ('playback-latency-' + time.strftime('%Y%m%d-%H%M%S'))
        out.mkdir(parents=True)
        profile.seed_db(scratch/'.nedotify/nedotify_storage.db', [], [], settings={'app': {'close_to_tray': False}})
        seeded_cache_rows = 0
        if args.seed_user_cache:
            user_db = Path.home()/'.nedotify/nedotify_storage.db'
            if user_db.is_file():
                with closing(sqlite3.connect(user_db.as_uri()+'?mode=ro', uri=True)) as reader:
                    rows = reader.execute("SELECT source, source_id, stream_url, cached_at, expires_at FROM stream_cache "
                                          "WHERE source='soundcloud' AND source_id IN (?,?,?,?)",
                                          [t['source_id'] for t in TRACKS if t['source']=='soundcloud']).fetchall()
                rows = [row for row in rows if str(row[2] or '').startswith('https://')]
                with closing(sqlite3.connect(scratch/'.nedotify/nedotify_storage.db')) as writer:
                    with writer:
                        writer.executemany('INSERT INTO stream_cache(source,source_id,stream_url,cached_at,expires_at) VALUES(?,?,?,?,?)', rows)
                seeded_cache_rows = len(rows)
        spec = scratch/'spec.json'
        spec.write_text(json.dumps({'scenario':'startup','profile_root':str(scratch),'settle_sec':.1}), encoding='utf-8')
        env = profile.child_env(scratch, extra={key:str(scratch) for key in ('HOME','APPDATA','LOCALAPPDATA')})
        env.update(NEDOTIFY_BENCH_SPEC=str(spec), NEDOTIFY_BENCH_RESULTS=str(out/'result.json'),
                   NEDOTIFY_BENCH_MODE='playback-latency', NEDOTIFY_BENCH_TRANSPORT='native',
                   NEDOTIFY_LATENCY_SKINS=args.skin_order,
                   NEDOTIFY_LATENCY_TRACKS=json.dumps([t for t in TRACKS if args.source == 'all' or t['source'] == args.source]))
        with (out/'child.log').open('w', encoding='utf-8') as log:
            child = subprocess.Popen([sys.executable,__file__,'--child'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                child.wait(timeout=300)
            except subprocess.TimeoutExpired:
                subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],capture_output=True)
                raise
        report = json.loads((out/'result.json').read_text(encoding='utf-8'))
        report['seeded_user_cache_rows'] = seeded_cache_rows
        (out/'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        data = report.get('data') or {}
        if args.compact:
            data = {'all_within_5s': data.get('all_within_5s'), 'results': [
                {k: v for k, v in row.items() if k not in ('stages', 'console_errors')}
                for row in data.get('results', [])]}
        print(json.dumps({'artifact':str(out/'result.json'),'ok':report['ok'],'data':data,
                          'seeded_user_cache_rows':seeded_cache_rows,'error':report.get('error')}, ensure_ascii=True))
        return 0 if report['ok'] and report.get('data',{}).get('all_within_5s') else 1


if __name__ == '__main__':
    raise SystemExit(main())
