"""Actual SoundCloud -> AppApi -> proxy -> HLS.js -> WebView audio, isolated."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def scenario(ctx):
    outcomes = []
    for style in ('current', 'macos'):
        result = ctx.js_async(r'''async style => {
            const api = window.pywebview.api;
            await api.save_setting('ui_style',style,'interface');
            const settings = await import(new URL('./js/settings.js',location.href));
            settings.applySettingsFromBackend(await api.get_settings());
            const player = await import(new URL('./js/player.js',location.href));
            // Real public track, never a fabricated audio URL or callback.
            const track={source:'soundcloud',source_id:'2393146779',title:'SoundCloud playback check',duration:92};
            const result=await api.play_track(track,[track],0);
            if(!result?.success)throw Error('Actual play_track rejected');
            const deadline=performance.now()+60000;
            while(performance.now()<deadline){
                const clock=player.getLyricsPlaybackClock();
                if(!clock.paused&&!clock.buffering&&clock.positionMs>1200){
                    const before=clock.positionMs;
                    await new Promise(r=>setTimeout(r,1200));
                    const after=player.getLyricsPlaybackClock();
                    if(after.positionMs>before+500&&!after.paused&&!after.buffering){
                        await api.play_pause();
                        return {style,playing:true,clock_advanced:true,position_ms:after.positionMs,duration_ms:after.durationMs};
                    }
                }
                await new Promise(r=>setTimeout(r,200));
            }
            const selected=player.getCurrentTrack();
            let shape={};
            try{const local=new URL(selected?.stream_url||'',location.href);const remote=new URL(local.searchParams.get('url')||'https://invalid.example/');shape={host:remote.hostname,manifest_path:remote.pathname.includes('/playlist/'),stream_type:selected?.stream_type};}catch{}
            return {style,playing:false,error:'Actual SoundCloud playback did not reach an advancing unbuffered clock',
                clock:player.getLyricsPlaybackClock(),stream:shape,
                console_errors:(window.__bench?.consoleErrors||[]).slice(-8).map(value=>String(value).replace(/https?:\/\/\S+/g,'<url>'))};
        }''', json.dumps(style), timeout=75)
        outcomes.append(result)
    return {'actual_bridge': True, 'api_stubs': False, 'source': 'soundcloud', 'source_id': '2393146779',
            'skins': outcomes, 'note': 'Decoded media clock verified; physical speaker output not assessed'}


def main():
    if '--child' in sys.argv:
        from tools.bench import bench_child
        bench_child.scenarios.scenario_startup = scenario
        bench_child.main()
        return
    from tools.bench import profile
    with tempfile.TemporaryDirectory(prefix='nedotify-sc-native-') as folder:
        scratch=Path(folder)
        out=ROOT/'tools/bench/results'/('soundcloud-native-'+time.strftime('%Y%m%d-%H%M%S'))
        out.mkdir(parents=True)
        profile.seed_db(scratch/'.nedotify/nedotify_storage.db', [], [], settings={'app': {'close_to_tray': False}})
        spec=scratch/'spec.json'
        spec.write_text(json.dumps({'scenario':'startup','profile_root':str(scratch),'settle_sec':.5}),encoding='utf-8')
        env=profile.child_env(scratch,extra={key:str(scratch) for key in ('HOME','APPDATA','LOCALAPPDATA')})
        env.update(NEDOTIFY_BENCH_SPEC=str(spec),NEDOTIFY_BENCH_RESULTS=str(out/'result.json'),
                   NEDOTIFY_BENCH_MODE='soundcloud-native',NEDOTIFY_BENCH_TRANSPORT='native')
        with (out/'child.log').open('w',encoding='utf-8') as log:
            child=subprocess.Popen([sys.executable,__file__,'--child'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            try:child.wait(timeout=210)
            except subprocess.TimeoutExpired:
                subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],capture_output=True)
                raise
        report=json.loads((out/'result.json').read_text(encoding='utf-8'))
        print(json.dumps({'artifact':str(out/'result.json'),'ok':report['ok'],'data':report.get('data'),'error':report.get('error')}))
        return 0 if report['ok'] else 1


if __name__=='__main__':
    raise SystemExit(main())
