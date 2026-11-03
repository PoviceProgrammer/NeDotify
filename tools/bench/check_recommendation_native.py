"""Isolated live WebView media-key and recent-search verification."""
import ctypes
import sqlite3
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
    skin=os.environ['NEDOTIFY_LYRICS_SKIN']
    result=ctx.js_async(r'''async skin=>{
      const api=window.pywebview.api;
      await api.save_setting('ui_style',skin,'interface');
      (await import(new URL('./js/settings.js',location.href))).applySettingsFromBackend(await api.get_settings());
      const bridge=await import(new URL('./js/events.js',location.href));
      let mixes=[];
      const remove=bridge.addPythonEventHandler((name,data)=>{if(name==='mixes_ready')mixes=Array.isArray(data)?data:(data.tracks||[])});
      // Exercise the normal request-tagged home flow; untagged replies are
      // intentionally rejected once a section request has been registered.
      (await import(new URL('./js/home.js',location.href))).loadHome();
      const start=performance.now();let card=null,mix=null;
      while(performance.now()-start<20000){
        mix=mixes.find(m=>m.title==='Открытия для вас');
        card=[...document.querySelectorAll('#home-mixes .feed-card')].find(c=>c.querySelector('.feed-card-title')?.textContent===mix?.title);
        if(mix&&card)break;
        await new Promise(r=>setTimeout(r,100));
      }
      remove();
      if(!mix||!card)throw Error('No genuine discovery mix/card within20s');
      document.getElementById('home-mixes').scrollIntoView({block:'center'});
      const expected=mix.tracks.map(t=>[t.source,String(t.source_id)]);
      card.querySelector('.feed-card-play').click();
      const player=await import(new URL('./js/player.js',location.href));
      let queue=null,advancing=false,previous=null;
      const deadline=performance.now()+25000;
      while(performance.now()<deadline){
        queue=await api.get_queue();
        const clock=player.getLyricsPlaybackClock();
        if(!clock.paused&&!clock.buffering&&clock.positionMs>100){
          if(previous!==null&&clock.positionMs>previous+100){advancing=true;break;}
          previous=clock.positionMs;
        }
        await new Promise(r=>setTimeout(r,250));
      }
      const actual=queue.tracks.map(t=>[t.source,String(t.source_id)]);
      const exact=JSON.stringify(actual)===JSON.stringify(expected);
      return {skin,mix_count:mixes.length,discovery_count:mix.tracks.length,queue_exact:exact,advancing,
        examples:mix.tracks.slice(0,3).map(t=>({source:t.source,source_id:t.source_id,title:t.title,artist:t.artist})),
        queue_count:actual.length,passed:exact&&advancing};
    }''',json.dumps(skin),timeout=65)
    dest=Path(os.environ['NEDOTIFY_BENCH_RESULTS']).parent/('recommendations-'+skin+'.png')
    dest.write_bytes(ctx.sess.screenshot_png());result['screenshot']=str(dest)
    return result


def main():
    if '--child' in sys.argv:
        from tools.bench import bench_child
        bench_child.scenarios.scenario_startup=scenario
        bench_child.main();return
    if '--skin' not in sys.argv:
        with tempfile.TemporaryDirectory(prefix='nedotify-user-snapshot-') as folder:
            snapshot=Path(folder)/'snapshot.db'
            source=sqlite3.connect((Path.home()/'.nedotify/nedotify_storage.db').as_uri()+'?mode=ro',uri=True)
            dest=sqlite3.connect(snapshot);source.backup(dest);source.close();dest.close()
            codes=[subprocess.call([sys.executable,__file__,'--skin',skin,'--snapshot',str(snapshot)],cwd=ROOT) for skin in ('current','macos')]
            return max(codes)
    from tools.bench import profile
    with tempfile.TemporaryDirectory(prefix='nedotify-recommendation-') as folder:
        scratch=Path(folder)
        out=ROOT/'tools/bench/results'/('recommendation-native-'+time.strftime('%Y%m%d-%H%M%S'));out.mkdir(parents=True)
        (scratch/'.nedotify').mkdir()
        snapshot=Path(sys.argv[sys.argv.index('--snapshot')+1]) if '--snapshot' in sys.argv else Path.home()/'.nedotify/nedotify_storage.db'
        source=sqlite3.connect(snapshot.as_uri()+'?mode=ro',uri=True)
        dest=sqlite3.connect(scratch/'.nedotify/nedotify_storage.db');source.backup(dest);source.close()
        jar=scratch/'.nedotify/bench_cookies.txt';jar.write_text('# Netscape HTTP Cookie File\n',encoding='utf-8')
        for key,value,category in [('app.close_to_tray','false','app'),('zapret.auto_start','false','zapret'),
                                   ('auth.cookies_file_path',str(jar),'auth'),('auth.browser_cookies','none','auth')]:
            dest.execute('INSERT OR REPLACE INTO settings(key,value,category) VALUES(?,?,?)',(key,value,category))
        dest.commit();dest.close()
        spec=scratch/'spec.json';spec.write_text(json.dumps({'scenario':'startup','profile_root':str(scratch),'settle_sec':.1}),encoding='utf-8')
        env=profile.child_env(scratch,extra={key:str(scratch) for key in ('HOME','APPDATA','LOCALAPPDATA')})
        env.update(NEDOTIFY_BENCH_SPEC=str(spec),NEDOTIFY_BENCH_RESULTS=str(out/'result.json'),NEDOTIFY_LYRICS_SKIN=sys.argv[sys.argv.index('--skin')+1],NEDOTIFY_BENCH_MODE='recommendation-native',NEDOTIFY_BENCH_TRANSPORT='native')
        with (out/'child.log').open('w',encoding='utf-8') as log:
            child=subprocess.Popen([sys.executable,__file__,'--child'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            try:child.wait(timeout=150)
            except subprocess.TimeoutExpired:
                subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],capture_output=True);raise
        report=json.loads((out/'result.json').read_text(encoding='utf-8'))
        print(json.dumps({'artifact':str(out/'result.json'),**report},ensure_ascii=True))
        return 0 if report.get('ok') and report.get('data',{}).get('passed') else 1

if __name__=='__main__':raise SystemExit(main())

