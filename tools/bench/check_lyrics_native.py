"""Isolated live WebView media-key and recent-search verification."""
import ctypes
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
    track={'source':'soundcloud','source_id':'303974832','title':'Сукины дети','artist':'Danzal_Parkour','duration':219.057}
    results=[]
    for skin in (os.environ['NEDOTIFY_LYRICS_SKIN'],):
        result=ctx.js_async(r'''async ({skin,track})=>{
          const api=window.pywebview.api;
          await api.save_setting('ui_style',skin,'interface');
          (await import(new URL('./js/settings.js',location.href))).applySettingsFromBackend(await api.get_settings());
          const events=[];
          const listener=e=>{
            const d=e.detail||{};
            events.push({status:d.status,identity_recovered:d.identity_recovered,matched_artist:d.matched_artist,
              source:d.source,phase:d.phase,characters:(d.plainLyrics||d.syncedLyrics||'').length,
              audio_position_ms:p.getLyricsPlaybackClock().positionMs,audio_paused:p.getLyricsPlaybackClock().paused});
          };
          document.addEventListener('nedotify:lyrics_ready',listener);
          const p=await import(new URL('./js/player.js',location.href));
          const response=await api.play_track(track,[track],0);
          document.querySelector('[data-page="player"]')?.click();
          const deadline=performance.now()+65000;
          let firstPosition=null,advancing=false;
          while(performance.now()<deadline){
            const clock=p.getLyricsPlaybackClock();
            if(!clock.paused&&clock.positionMs>100){
              if(firstPosition===null)firstPosition=clock.positionMs;
              if(clock.positionMs>firstPosition+100)advancing=true;
            }
            const lines=[...document.querySelectorAll('#lyrics-content .lyric-line')];
            const visible=lines.filter(el=>el.getClientRects().length>0).length;
            const characters=document.getElementById('lyrics-content')?.textContent?.length||0;
            const found=events.find(e=>e.status==='found'&&e.identity_recovered&&String(e.matched_artist).includes('1.Kla'));
            if(found&&visible>0&&characters>500&&advancing){
              document.removeEventListener('nedotify:lyrics_ready',listener);
              return {skin,bridge_success:response?.success,advancing,visible_lines:visible,characters,events,
                playback_mode:advancing?'actual_audio':'nonplayback',passed:true};
            }
            await new Promise(r=>setTimeout(r,200));
          }
          document.removeEventListener('nedotify:lyrics_ready',listener);
          return {skin,bridge_success:response?.success,advancing,events,
            lines:document.querySelectorAll('#lyrics-content .lyric-line').length,
            characters:document.getElementById('lyrics-content')?.textContent?.length||0,passed:false};
        }''',json.dumps({'skin':skin,'track':track}),timeout=80)
        results.append(result)
    return {'results':results,'all_passed':all(r['passed'] for r in results)}


def main():
    if '--child' in sys.argv:
        from tools.bench import bench_child
        bench_child.scenarios.scenario_startup=scenario
        bench_child.main();return
    if '--skin' not in sys.argv:
        codes=[subprocess.call([sys.executable,__file__,'--skin',skin],cwd=ROOT) for skin in ('current','macos')]
        return max(codes)
    from tools.bench import profile
    with tempfile.TemporaryDirectory(prefix='nedotify-lyrics-') as folder:
        scratch=Path(folder)
        out=ROOT/'tools/bench/results'/('lyrics-native-'+time.strftime('%Y%m%d-%H%M%S'));out.mkdir(parents=True)
        profile.seed_db(scratch/'.nedotify/nedotify_storage.db',[],[],settings={'app':{'close_to_tray':False}})
        spec=scratch/'spec.json';spec.write_text(json.dumps({'scenario':'startup','profile_root':str(scratch),'settle_sec':.1}),encoding='utf-8')
        env=profile.child_env(scratch,extra={key:str(scratch) for key in ('HOME','APPDATA','LOCALAPPDATA')})
        env.update(NEDOTIFY_BENCH_SPEC=str(spec),NEDOTIFY_BENCH_RESULTS=str(out/'result.json'),NEDOTIFY_LYRICS_SKIN=sys.argv[sys.argv.index('--skin')+1],NEDOTIFY_BENCH_MODE='lyrics-native',NEDOTIFY_BENCH_TRANSPORT='native')
        with (out/'child.log').open('w',encoding='utf-8') as log:
            child=subprocess.Popen([sys.executable,__file__,'--child'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            try:child.wait(timeout=150)
            except subprocess.TimeoutExpired:
                subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],capture_output=True);raise
        report=json.loads((out/'result.json').read_text(encoding='utf-8'))
        print(json.dumps({'artifact':str(out/'result.json'),**report},ensure_ascii=True))
        return 0 if report.get('ok') and report.get('data',{}).get('all_passed') else 1

if __name__=='__main__':raise SystemExit(main())

