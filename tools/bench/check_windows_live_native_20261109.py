"""Real WebView2/bridge/album/audio smoke with an empty disposable profile.

No provider stubs, no user cookies, no Zapret launch. Audio is muted while
the real decoder clock, pause, resume and seek are checked.
"""
from __future__ import annotations

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
    import ctypes
    from ctypes import wintypes
    visible = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == os.getpid() and ctypes.windll.user32.IsWindowVisible(hwnd):
            visible.append(int(hwnd))
        return True

    ctypes.windll.user32.EnumWindows(visit, 0)
    if not visible:
        raise RuntimeError('App has no visible native window')
    result = ctx.js_async(r'''async()=>{
        const api=window.pywebview.api;
        const player=await import(new URL('./js/player.js',location.href));
        const search=await import(new URL('./js/search.js',location.href));
        const wait=async(test,label,ms=20000)=>{
            const deadline=performance.now()+ms;
            while(performance.now()<deadline){if(await test())return;await new Promise(r=>setTimeout(r,100));}
            throw Error(label+' timed out: '+JSON.stringify(player.getLyricsPlaybackClock()));
        };
        player.applyMuteState(true);
        await api.set_volume(0);
        await search.openAlbumModal({source:'youtube',source_id:'MPREb_oBucXyijinj',title:'Parachutes',artist:'Coldplay'});
        const modal=document.getElementById('album-detail-modal');
        const title=modal.querySelector('[data-album-detail-title]')?.textContent;
        const count=modal.querySelectorAll('#album-modal-tracks .track-item').length;
        if(title!=='Parachutes'||count!==10)throw Error('Album UI incomplete: '+title+' '+count);
        const art=modal.querySelector('[data-album-detail-cover]');
        await wait(()=>art?.complete&&art.naturalWidth>0,'album cover',10000);
        document.getElementById('btn-play-full-album').click();
        await wait(()=>{const c=player.getLyricsPlaybackClock();return !c.paused&&!c.buffering&&c.positionMs>300},'real album playback',35000);
        const queue=await api.get_queue();
        if(queue.tracks.length!==10)throw Error('Wrong album queue length');
        const first=player.getLyricsPlaybackClock();
        await new Promise(r=>setTimeout(r,700));
        const next=player.getLyricsPlaybackClock();
        if(next.positionMs<=first.positionMs+100)throw Error('Audio clock did not advance');
        document.getElementById('pb-btn-play').click();
        await wait(()=>player.getLyricsPlaybackClock().paused,'pause');
        const pausedAt=player.getLyricsPlaybackClock().positionMs;
        await new Promise(r=>setTimeout(r,500));
        if(Math.abs(player.getLyricsPlaybackClock().positionMs-pausedAt)>200)throw Error('Paused clock advancing');
        document.getElementById('pb-btn-play').click();
        await wait(()=>!player.getLyricsPlaybackClock().paused,'resume');
        player.seekTo(30000);
        await wait(()=>{const c=player.getLyricsPlaybackClock();return !c.buffering&&!c.seeking&&c.positionMs>=29500},'seek');
        const firstKey=player.getLyricsPlaybackClock().trackKey;
        await api.next_track();
        await wait(()=>{const c=player.getLyricsPlaybackClock();return c.trackKey!==firstKey&&!c.paused&&!c.buffering&&c.positionMs>200},'next album track',35000);
        document.getElementById('pb-btn-play').click();
        return {albumTitle:title,albumTracks:count,coverLoaded:true,queueTracks:queue.tracks.length,
            realDecoderClockAdvanced:true,pause:true,resume:true,seek:true,nextTrack:true,
            audioMuted:true,fixtures:false};
    }''', timeout=115)
    result['visibleNativeWindow'] = True
    path = Path(ctx.spec['out_dir']) / 'native-album-player.png'
    path.write_bytes(ctx.sess.screenshot_png())
    result['screenshot'] = str(path)
    return result


def child():
    from core.database import DatabaseManager
    profile = Path(os.environ['USERPROFILE'])
    (profile / '.nedotify').mkdir(parents=True, exist_ok=True)
    db = DatabaseManager(str(profile / '.nedotify/nedotify_storage.db'))
    cookiefile = profile / 'empty-cookies.txt'
    cookiefile.write_text('# Netscape HTTP Cookie File\n', encoding='utf-8')
    rows = [('general.first_launch_done', 'true', 'general'),
            ('personalization.onboarding_completed', 'true', 'personalization'),
            ('app.close_to_tray', 'false', 'app'),
            ('zapret.enabled', 'false', 'zapret'), ('zapret.auto_start', 'false', 'zapret'),
            ('auth.cookies_file_path', str(cookiefile), 'auth'), ('auth.browser_cookies', 'none', 'auth')]
    db.conn.executemany('INSERT OR REPLACE INTO settings(key,value,category) VALUES(?,?,?)', rows)
    db.conn.commit()
    db.close()
    from tools.bench import bench_child
    bench_child.scenarios.scenario_startup = scenario
    bench_child.main()


def main():
    if '--child' in sys.argv:
        child()
        return 0
    from tools.bench import profile
    out = ROOT / 'tools/bench/results' / ('windows-native-live-' + time.strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix='nedotify-windows-live-') as folder:
        scratch = Path(folder)
        spec = scratch / 'spec.json'
        spec.write_text(json.dumps({'scenario': 'startup', 'profile_root': folder, 'out_dir': str(out), 'settle_sec': .3}), encoding='utf-8')
        env = profile.child_env(scratch, extra={key: folder for key in ('HOME', 'APPDATA', 'LOCALAPPDATA')})
        env.update(NEDOTIFY_BENCH_SPEC=str(spec), NEDOTIFY_BENCH_RESULTS=str(out / 'result.json'),
                   NEDOTIFY_BENCH_MODE='windows-live', NEDOTIFY_BENCH_TRANSPORT='native')
        with (out / 'child.log').open('w', encoding='utf-8') as log:
            proc = subprocess.Popen([sys.executable, __file__, '--child'], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                proc.wait(timeout=200)
            except subprocess.TimeoutExpired:
                subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True)
                raise
        result = json.loads((out / 'result.json').read_text(encoding='utf-8'))
        print(json.dumps({'artifact': str(out / 'result.json'), 'ok': result.get('ok'), 'error': result.get('error'), 'data': result.get('data')}, ensure_ascii=True))
        return 0 if result.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
