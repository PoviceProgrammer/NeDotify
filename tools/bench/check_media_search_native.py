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
    from tools.bench.scenarios import set_window_minimized
    from tools.bench.check_playback_latency_native import TRACKS
    ctx.js_async("async skin=>{const api=window.pywebview.api;await api.save_setting('ui_style',skin,'interface');(await import(new URL('./js/settings.js',location.href))).applySettingsFromBackend(await api.get_settings());}",json.dumps(os.environ['NEDOTIFY_MEDIA_SKIN']))
    ctx.js_async('''async track => {
      const api=window.pywebview.api;
      await api.play_track(track,[track],0);
      const p=await import(new URL('./js/player.js',location.href));
      for(let i=0;i<100;i++) { const c=p.getLyricsPlaybackClock(); if(!c.paused&&c.positionMs>100)return true; await new Promise(r=>setTimeout(r,200)); }
      throw Error('Live audio did not start');
    }''',json.dumps(TRACKS[4]))
    from ctypes import wintypes
    windows=[]
    @ctypes.WINFUNCTYPE(ctypes.c_bool,wintypes.HWND,wintypes.LPARAM)
    def own_window(hwnd,_):
        owner=wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd,ctypes.byref(owner))
        if owner.value==os.getpid() and ctypes.windll.user32.IsWindowVisible(hwnd):
            windows.append(hwnd)
        return True
    ctypes.windll.user32.EnumWindows(own_window,0)
    hwnd=windows[0] if windows else None
    assert hwnd
    results=[]
    for minimized in (False,True):
        set_window_minimized(hwnd,minimized)
        # Keyboard media events pass through Windows' system media routing,
        # rather than invoking the JavaScript handler or posting its callback.
        for expected in (True,False):
            time.sleep(2)
            ctypes.windll.user32.keybd_event(0xB3,0,0,0)
            ctypes.windll.user32.keybd_event(0xB3,0,2,0)
            deadline=time.monotonic()+5
            paused=None
            while time.monotonic()<deadline:
                paused=ctx.js_async("async()=> (await import(new URL('./js/player.js',location.href))).getLyricsPlaybackClock().paused")
                if paused == expected: break
                time.sleep(.1)
            results.append({'minimized':minimized,'expected_paused':expected,'paused':paused,'session_state':ctx.js('navigator.mediaSession.playbackState')})
    # Verify next/previous through the same Windows route while minimized.
    ctx.js_async("""async tracks=>{
      await window.pywebview.api.play_track(tracks[0],tracks,0);
      await new Promise(r=>setTimeout(r,2000));
      return true;
    }""",json.dumps([TRACKS[4],TRACKS[6]]))
    navigation=[]
    set_window_minimized(hwnd,True)
    for key, expected in ((0xB0,TRACKS[6]['source_id']),(0xB1,TRACKS[4]['source_id'])):
        time.sleep(1)
        ctypes.windll.user32.keybd_event(key,0,0,0)
        ctypes.windll.user32.keybd_event(key,0,2,0)
        deadline=time.monotonic()+15
        selected=None
        while time.monotonic()<deadline:
            selected=ctx.js_async("async()=> (await import(new URL('./js/player.js',location.href))).getCurrentTrack()?.source_id")
            if str(selected)==expected:break
            time.sleep(.2)
        navigation.append({'key':key,'expected':expected,'selected':selected,'passed':str(selected)==expected})
    set_window_minimized(hwnd,False)
    ctypes.windll.user32.SetForegroundWindow(hwnd)
    time.sleep(.5)
    shots=[]
    for skin in (os.environ['NEDOTIFY_MEDIA_SKIN'],):
        ctx.js_async('''async skin=>{
          const api=window.pywebview.api;
          await api.save_setting('ui_style',skin,'interface');
          (await import(new URL('./js/settings.js',location.href))).applySettingsFromBackend(await api.get_settings());
          document.querySelector('[data-page="search"]')?.click();
          await new Promise(r=>setTimeout(r,500));
          const s=await import(new URL('./js/search.js',location.href));
          s.saveSearchQuery('Radiohead');s.saveSearchQuery('Земфира');s.saveSearchQuery('Daft Punk — Discovery');
          const input=document.getElementById('search-input'); input.blur(); input.focus();
          if(document.getElementById('search-suggestions-dropdown').classList.contains('hidden'))throw Error('Recent dropdown did not open');
          return true;
        }''',json.dumps(skin))
        time.sleep(.3)
        dest=Path(os.environ['NEDOTIFY_BENCH_RESULTS']).parent/f'search-{skin}.png'
        dest.write_bytes(ctx.sess.screenshot_png());shots.append(str(dest))
        ctx.js_async("""async()=>{
          const s=await import(new URL('./js/search.js',location.href));
          const dropdown=document.getElementById('search-suggestions-dropdown');
          const deleted=dropdown.querySelector('[data-delete-query]').dataset.deleteQuery;
          dropdown.querySelector('[data-delete-query]').click();
          if(s.getSearchHistory().includes(deleted))throw Error('Delete failed');
          dropdown.querySelector('#btn-clear-all-history').click();
          if(s.getSearchHistory().length)throw Error('Clear failed');
          if(!dropdown.querySelector('.search-history-empty'))throw Error('Missing empty state');
          s.saveSearchQuery('Radiohead');
          const input=document.getElementById('search-input');input.blur();input.focus();
          input.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true}));
          if(!document.activeElement.matches('.search-history-query'))throw Error('Arrow navigation failed');
          dropdown.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
          if(!dropdown.classList.contains('hidden'))throw Error('Escape failed');
          input.blur();input.focus();
          dropdown.querySelector('.search-history-query').click();
          if(input.value!=='Radiohead'||!dropdown.classList.contains('hidden'))throw Error('Search repeat failed');
          input.value='';
          return true;
        }""")
    return {'window_pid':os.getpid(),'window_hwnd':hwnd,'skin':os.environ['NEDOTIFY_MEDIA_SKIN'],'navigation':navigation,'media':results,'all_media_passed':all(r['paused']==r['expected_paused'] for r in results) and all(r['passed'] for r in navigation),'screenshots':shots}


def main():
    if '--child' in sys.argv:
        from tools.bench import bench_child
        bench_child.scenarios.scenario_startup=scenario
        bench_child.main();return
    if '--skin' not in sys.argv:
        codes=[subprocess.call([sys.executable,__file__,'--skin',skin],cwd=ROOT) for skin in ('current','macos')]
        return max(codes)
    from tools.bench import profile
    with tempfile.TemporaryDirectory(prefix='nedotify-media-') as folder:
        scratch=Path(folder)
        out=ROOT/'tools/bench/results'/('media-search-'+time.strftime('%Y%m%d-%H%M%S'));out.mkdir(parents=True)
        profile.seed_db(scratch/'.nedotify/nedotify_storage.db',[],[],settings={'app':{'close_to_tray':False}})
        spec=scratch/'spec.json';spec.write_text(json.dumps({'scenario':'startup','profile_root':str(scratch),'settle_sec':.1}),encoding='utf-8')
        env=profile.child_env(scratch,extra={key:str(scratch) for key in ('HOME','APPDATA','LOCALAPPDATA')})
        env.update(NEDOTIFY_BENCH_SPEC=str(spec),NEDOTIFY_BENCH_RESULTS=str(out/'result.json'),NEDOTIFY_MEDIA_SKIN=sys.argv[sys.argv.index('--skin')+1],NEDOTIFY_BENCH_MODE='media-search',NEDOTIFY_BENCH_TRANSPORT='native')
        with (out/'child.log').open('w',encoding='utf-8') as log:
            child=subprocess.Popen([sys.executable,__file__,'--child'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            try:child.wait(timeout=150)
            except subprocess.TimeoutExpired:
                subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],capture_output=True);raise
        report=json.loads((out/'result.json').read_text(encoding='utf-8'))
        print(json.dumps({'artifact':str(out/'result.json'),**report},ensure_ascii=True))
        return 0 if report.get('ok') and report.get('data',{}).get('all_media_passed') else 1

if __name__=='__main__':raise SystemExit(main())

