"""Real search -> bridge -> proxy -> WebView2 playback, disposable profile.

No API/provider fixtures. The existing analyser is disconnected only from the
speaker destination, keeping real decoding and signal measurement running.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
RESOLUTIONS = []


def observe_resolver():
    from audio.engine import AudioEngine
    original = AudioEngine.resolve_stream_url

    def observed(self, track, *args, **kwargs):
        url = original(self, track, *args, **kwargs)
        RESOLUTIONS.append({'source': track.get('source'), 'source_id': track.get('source_id'),
                            'host': urlsplit(url).hostname if url else None})
        return url
    AudioEngine.resolve_stream_url = observed


def scenario(ctx):
    results = []
    ctx.js_async(r'''async()=>{
        const player=await import(new URL('./js/player.js',location.href));
        player.getAudioFrequencyData(new Uint8Array(128));
        const audio=player.getAtmosphereAudioSource();
        if(!audio.analyser||!audio.context)throw Error('Real audio graph missing');
        audio.analyser.disconnect(audio.context.destination);
        player.applyMuteState(false);
        await window.pywebview.api.set_volume(.5);
        return true;
    }''')
    for style in os.environ.get('NEDOTIFY_PLAYBACK_STYLES', 'current,macos').split(','):
        ctx.js_async(r'''async style=>{
            const api=window.pywebview.api;
            await api.save_setting('ui_style',style,'interface');
            const settings=await import(new URL('./js/settings.js',location.href));
            settings.applySettingsFromBackend(await api.get_settings());
            return true;
        }''', json.dumps(style))
        for source, query in [('youtube', 'Rick Astley'), ('soundcloud', 'v3lvet'), ('spotify', 'Radiohead Creep')]:
            if source not in os.environ.get('NEDOTIFY_PLAYBACK_SOURCES', 'youtube,soundcloud,spotify').split(','):
                continue
            row = ctx.js_async(r'''async ({source,query})=>{
                const api=window.pywebview.api;
                const player=await import(new URL('./js/player.js',location.href));
                const wait=async(test,label,ms=35000)=>{
                    const end=performance.now()+ms;
                    while(performance.now()<end){if(await test())return;await new Promise(r=>setTimeout(r,100));}
                    throw Error(label+' timeout');
                };
                const rid='live-'+source+'-'+Date.now();
                const found=[];let complete=false;
                const original=window.onPythonEvent;
                window.onPythonEvent=function(name,payload){
                    if(payload?.request_id===rid){
                        if(name==='search_results')found.push(...(payload.tracks||[]));
                        if(name==='search_completed')complete=true;
                    }
                    return original.apply(this,arguments);
                };
                try{await api.search(query,source,null,rid);await wait(()=>complete,'real search',25000);}
                finally{window.onPythonEvent=original;}
                const unique=new Map(found.filter(t=>t.source===source&&t.source_id&&Number(t.duration)>60)
                    .map(t=>[t.source_id,t]));
                const tracks=[...unique.values()].slice(0,2);
                if(tracks.length<2)throw Error(source+' search did not return two full-length tracks');
                const r={source,query,searchResults:found.length,tracks:tracks.map(t=>({source_id:t.source_id,title:t.title,artist:t.artist})),
                    firstPlaying:false,pause:false,resume:false,seek:false,nextPlaying:false};
                const advancing=async expected=>{
                    await wait(()=>{const c=player.getLyricsPlaybackClock();return String(player.getCurrentTrack()?.source_id)===String(expected.source_id)
                        &&!c.paused&&!c.buffering&&c.positionMs>400;},'decoded playback');
                    const before=player.getLyricsPlaybackClock();
                    let peak=0;
                    for(let n=0;n<15;n++){
                        const audio=player.getAtmosphereAudioSource();
                        const samples=new Float32Array(audio.analyser.fftSize);
                        audio.analyser.getFloatTimeDomainData(samples);
                        peak=Math.max(peak,...samples.map(Math.abs));
                        await new Promise(r=>setTimeout(r,100));
                    }
                    const after=player.getLyricsPlaybackClock();
                    if(after.paused||after.buffering||after.positionMs<before.positionMs+700)throw Error('Clock stalled');
                    if(peak<.00001)throw Error('Decoded signal stayed silent');
                    return {positionMs:Math.round(after.positionMs),peak,clockAdvancedMs:Math.round(after.positionMs-before.positionMs)};
                };
                window.__threeProviderCurrent=r;
                const started=performance.now();
                const accepted=await api.play_track(tracks[0],tracks,0);
                if(!accepted?.success)throw Error('Play rejected');
                r.first=await advancing(tracks[0]);r.firstPlaying=true;
                r.startAndMeasureMs=Math.round(performance.now()-started);
                document.getElementById('pb-btn-play').click();
                await wait(()=>player.getLyricsPlaybackClock().paused,'pause');
                const paused=player.getLyricsPlaybackClock().positionMs;
                await new Promise(r=>setTimeout(r,500));
                if(Math.abs(player.getLyricsPlaybackClock().positionMs-paused)>200)throw Error('Paused clock moved');
                r.pause=true;
                document.getElementById('pb-btn-play').click();await wait(()=>!player.getLyricsPlaybackClock().paused,'resume');r.resume=true;
                player.seekTo(30000);
                await wait(()=>{const c=player.getLyricsPlaybackClock();return !c.buffering&&!c.seeking&&c.positionMs>=29500;},'seek');
                r.seek=true;
                await api.next_track();r.next=await advancing(tracks[1]);r.nextPlaying=true;
                const queue=await api.get_queue();r.queueTracks=queue.tracks.length;
                if(r.queueTracks!==2)throw Error('Queue not retained');
                document.getElementById('pb-btn-play').click();
                return r;
            }''', json.dumps({'source': source, 'query': query}), timeout=130)
            row['style'] = style
            row['resolutions'] = [r for r in RESOLUTIONS if r['source'] == source
                                  and r['source_id'] in {t['source_id'] for t in row['tracks']}]
            results.append(row)
            (Path(ctx.spec['out_dir']) / 'progress.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
            print('[playback] ' + json.dumps(row, ensure_ascii=True), flush=True)
        (Path(ctx.spec['out_dir']) / ('player-' + style + '.png')).write_bytes(ctx.sess.screenshot_png())
    for row in results:
        expected = ('sndcdn.com', 'soundcloud.cloud') if row['source'] == 'soundcloud' else ('googlevideo.com',)
        hosts = [r['host'] for r in row['resolutions'] if r['host']]
        if not hosts or not all(any(h == suffix or h.endswith('.' + suffix) for suffix in expected) for h in hosts):
            raise RuntimeError('Unexpected audio origin for ' + row['source'] + ': ' + str(hosts))
    return {'results': results, 'realProviders': True, 'realBridge': True, 'audioFixtures': False,
            'realSignalMeasured': True, 'speakerDestinationDisconnected': True, 'vpnModified': False}


def main():
    if '--child' in sys.argv:
        observe_resolver()
        from tools.bench import bench_child
        def checked(ctx):
            try:
                return scenario(ctx)
            except Exception:
                try:
                    failure = ctx.js_async('async()=>({current:window.__threeProviderCurrent, clock:(await import(new URL("./js/player.js",location.href))).getLyricsPlaybackClock()})')
                    failure['resolutions'] = RESOLUTIONS
                    (Path(ctx.spec['out_dir'])/'failure.json').write_text(json.dumps(failure,ensure_ascii=False,indent=2),encoding='utf-8')
                except Exception:
                    pass
                raise
        bench_child.scenarios.scenario_startup = checked
        bench_child.main()
        return 0
    parser=argparse.ArgumentParser()
    parser.add_argument('--source', default='youtube,soundcloud,spotify')
    parser.add_argument('--styles', default='current,macos')
    args=parser.parse_args()
    from tools.bench import profile
    out = ROOT / 'tools/bench/results' / ('three-provider-playback-' + time.strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix='nedotify-three-playback-') as folder:
        scratch = Path(folder)
        profile.seed_db(scratch / '.nedotify/nedotify_storage.db', [], [],
                        settings={'app': {'close_to_tray': False}, 'zapret': {'enabled': False, 'auto_start': False}})
        spec = scratch / 'spec.json'
        spec.write_text(json.dumps({'scenario': 'startup', 'profile_root': folder, 'out_dir': str(out), 'settle_sec': .1}), encoding='utf-8')
        env = profile.child_env(scratch, extra={k: folder for k in ('HOME', 'APPDATA', 'LOCALAPPDATA')})
        env.update(NEDOTIFY_BENCH_SPEC=str(spec), NEDOTIFY_BENCH_RESULTS=str(out / 'result.json'),
                   NEDOTIFY_BENCH_MODE='three-provider-live', NEDOTIFY_BENCH_TRANSPORT='native',
                   NEDOTIFY_PLAYBACK_STYLES=args.styles, NEDOTIFY_PLAYBACK_SOURCES=args.source)
        with (out / 'child.log').open('w', encoding='utf-8') as log:
            proc = subprocess.Popen([sys.executable, __file__, '--child'], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                proc.wait(timeout=550)
            finally:
                if proc.poll() is None:
                    subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True)
                    proc.wait(timeout=15)
        result = json.loads((out / 'result.json').read_text(encoding='utf-8'))
        print(json.dumps({'artifact': str(out / 'result.json'), 'ok': result['ok'], 'error': result.get('error')}, ensure_ascii=True))
        return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
