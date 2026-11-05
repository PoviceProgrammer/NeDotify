"""Verify new recommendation controls in real WebView2, using isolated fixtures.

Only external candidate collection is replaced. Bridge, ranking, SQLite, queue,
playback and authored UI are real. Does not measure live provider relevance.
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
    out = Path(ctx.spec['out_dir'])
    results = []
    for style in ('current', 'macos'):
        result = ctx.js_async(r'''async style => {
            const api=window.pywebview.api;
            const settings=await import(new URL('./js/settings.js',location.href));
            await api.save_setting('ui_style',style,'interface');
            window.settings=await api.get_settings();
            settings.applySettingsFromBackend(window.settings);
            await window.NeDotifyStyles.ensureForPage('home');
            window.showPage('home');
            await (await import(new URL('./js/home.js',location.href))).loadHome();
            const controls=await import(new URL('./js/recommendation-controls.js',location.href));
            for(const mode of ['familiar','balanced','discovery']) {
                document.querySelector(`#home-recommendation-controls [data-recommendation-mode="${mode}"]`).click();
                const deadline=performance.now()+5000;
                while(performance.now()<deadline && ((await api.get_settings()).personalization.recommendation_mode!==mode || document.querySelector('#home-recommendation-controls button').disabled))await new Promise(r=>setTimeout(r,30));
                if((await api.get_settings()).personalization.recommendation_mode!==mode)throw Error('Mode not persisted: '+mode);
            }
            await settings.ensureSettingsPanel();
            await window.NeDotifyStyles.ensureForPage('settings');
            window.showPage('settings');
            document.querySelector('.settings-nav-btn[data-panel="player"]').click();
            const selected=document.querySelector('#settings-recommendation-controls [aria-pressed="true"]');
            if(selected?.dataset.recommendationMode!=='discovery')throw Error('Settings selection out of sync');
            return {style,mode:controls.recommendationMode(),settingsSynced:true};
        }''', json.dumps(style))
        time.sleep(.75)
        (out / f'{style}-settings.png').write_bytes(ctx.sess.screenshot_png())
        ctx.js("window.showPage('home');document.getElementById('home-recommendation-controls').scrollIntoView({block:'center'})")
        time.sleep(.75)
        (out / f'{style}-home.png').write_bytes(ctx.sess.screenshot_png())
        result['playlist'] = ctx.js_async(r'''async()=>{
            const api=window.pywebview.api;
            const lib=await import(new URL('./js/library.js',location.href));
            window.showPage('library');await window.NeDotifyStyles.ensureForPage('library');
            const playlists=await api.get_playlists();const playlist=playlists.find(p=>p.name==='Evening selection');
            await lib.selectSection('playlist',playlist);
            const deadline=performance.now()+10000;
            while(performance.now()<deadline && !document.querySelector('.playlist-recommendations .playlist-recommendation'))await new Promise(r=>setTimeout(r,50));
            const section=document.querySelector('.playlist-recommendations');
            if(!section?.querySelector('.playlist-recommendation'))throw Error('Missing playlist suggestions: '+section?.innerText);
            if(!section.querySelector('.playlist-recommendation-reason'))throw Error('Missing recommendation reasons');
            section.scrollIntoView({block:'start'});
            return {text:section.innerText,playlistId:playlist.id};
        }''')
        time.sleep(.25)
        (out / f'{style}-playlist.png').write_bytes(ctx.sess.screenshot_png())
        result['actions'] = ctx.js_async(r'''async()=>{
            const api=window.pywebview.api;
            const section=document.querySelector('.playlist-recommendations');
            const waitFor=async test=>{const end=performance.now()+7000;while(performance.now()<end){if(await test())return;await new Promise(r=>setTimeout(r,50))}throw Error('UI action timed out')};
            const playlist=(await api.get_playlists()).find(p=>p.name==='Evening selection');
            const before=(await api.get_playlist_tracks(playlist.id)).tracks.length;
            const first=section.querySelector('.playlist-recommendation');
            const title=first.querySelector('strong').textContent;
            first.querySelector('.playlist-recommendation-play').click();
            await waitFor(async()=> (await api.get_queue()).tracks.some(t=>t.title===title));
            first.querySelector('.playlist-recommendation-add').click();
            await waitFor(async()=> (await api.get_playlist_tracks(playlist.id)).tracks.length===before+1);
            await waitFor(()=>!Array.from(section.querySelectorAll('strong')).some(el=>el.textContent===title));
            section.querySelector('.playlist-recommendations-refresh').click();
            await waitFor(()=>section.dataset.state==='ready');
            if(Array.from(section.querySelectorAll('strong')).some(el=>el.textContent===title))throw Error('Added song suggested again');
            const lib=await import(new URL('./js/library.js',location.href));
            await lib.selectSection('favorites');
            await waitFor(()=>section.dataset.state==='ready');
            const favorite=section.querySelector('.playlist-recommendation strong').textContent;
            section.querySelector('.playlist-recommendation-add').click();
            await waitFor(async()=> (await api.get_favorites()).some(t=>t.title===favorite));
            return {played:true,added:true,refreshExcludesAdded:true,favoritesAdded:true};
        }''')
        result['wave'] = ctx.js_async(r'''async()=>{
            const api=window.pywebview.api;
            const wave=await import(new URL('./js/track-wave.js',location.href));
            const waitFor=async test=>{const end=performance.now()+10000;while(performance.now()<end){if(await test())return;await new Promise(r=>setTimeout(r,50))}throw Error('Wave action timed out: '+JSON.stringify(wave.getTrackWaveState()))};
            const seed=(await api.get_favorites())[0];
            await window.NeDotify.startTrackWave(seed);
            await waitFor(async()=> (await api.get_queue()).tracks.length>=10 && wave.getTrackWaveState().status==='ready');
            const initial=(await api.get_queue()).tracks.length;
            for(let i=0;i<initial-5;i++)await api.next_track();
            await waitFor(async()=> (await api.get_queue()).tracks.length>initial);
            const queue=await api.get_queue();
            const keys=queue.tracks.map(t=>t.artist+':'+t.title);
            if(new Set(keys).size!==keys.length)throw Error('Repeated wave tracks');
            const player=await import(new URL('./js/player.js',location.href));
            await waitFor(()=>{const clock=player.getLyricsPlaybackClock();return !clock.paused&&!clock.buffering&&clock.positionMs>100});
            document.getElementById('pb-btn-queue').click();
            return {initial,afterRefill:queue.tracks.length,active:wave.getTrackWaveState().active,unique:true,localPlaybackAdvancing:true};
        }''')
        time.sleep(.75)
        (out / f'{style}-wave.png').write_bytes(ctx.sess.screenshot_png())
        result['wave']['stopped'] = ctx.js_async(r'''async()=>{
            document.querySelector('.queue-wave-stop').click();
            const wave=await import(new URL('./js/track-wave.js',location.href));
            if(wave.getTrackWaveState().active)throw Error('Wave still active');
            document.getElementById('queue-drawer-close').click();
            await window.pywebview.api.play_pause();
            return true;
        }''')
        results.append(result)
    origin = ctx.js('performance.timeOrigin')
    ctx.sess.ws.call('Page.reload', {'ignoreCache': True})
    ctx.sess.wait_for_new_document(origin, timeout=30)
    ctx.sess.wait_for_js('window._nedotifyInitialized === true', timeout=30)
    persisted = ctx.js_async('''async()=>{
        const api=window.pywebview.api;
        const settings=await api.get_settings();
        if(settings.personalization.recommendation_mode!=='discovery')throw Error('Preference lost on reload');
        return true;
    }''')
    return {'fixture_candidates': True, 'actual_bridge': True, 'skins': results, 'preferenceSurvivesReload': persisted}


def install_candidates():
    from services.recommendation_service import RecommendationService
    root = Path(os.environ['NEDOTIFY_BENCH_PROFILE'])
    def collect(self, profile, seeds=None, artists=None, limit=60, **kwargs):
        seed_artists = list(artists or [t.get('artist') for t in seeds or [] if t.get('artist')]) or ['Artist 000']
        return [dict(title=f'New recording {index + 1}', artist=f'Discovery Artist {index % 18:02d}',
                     source='local', source_id=f'candidate-{index}', file_path=str(root / '.nedotify' / f'candidate-{index}.wav'),
                     duration=90, cover_path=str(root / '.nedotify' / 'covers' / f'fixture_cover_{index % 6:02d}.png'),
                     recommendation_source='fixture_related', recommendation_relevance=.85,
                     recommendation_seed_artists=seed_artists[:2], genre='electronic') for index in range(80)]
    RecommendationService._collect_candidates = collect


def main():
    if '--child' in sys.argv:
        install_candidates()
        from tools.bench import bench_child
        bench_child.scenarios.scenario_startup = scenario
        bench_child.main()
        return
    from tools.bench import profile
    from core.database import DatabaseManager
    scratch = Path(tempfile.mkdtemp(prefix='nedotify-recommendation-features-'))
    out = ROOT / 'tools/bench/results' / ('recommendation-features-' + time.strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True)
    covers = profile.write_covers(scratch, n=6)
    audio = scratch / '.nedotify/fixture.wav'
    profile.write_silent_audio(audio, 90)
    for i in range(80):
        os.link(audio, scratch / '.nedotify' / f'candidate-{i}.wav')
    tracks = profile.make_track_specs(12)
    for i, track in enumerate(tracks):
        track_audio = scratch / '.nedotify' / f'seed-{i}.wav'
        os.link(audio, track_audio)
        track.update(source='local', file_path=str(track_audio), is_downloaded=1, is_favorite=int(i < 4), duration=90)
    database = scratch / '.nedotify/nedotify_storage.db'
    profile.seed_db(database, tracks, covers, settings={
        'general': {'close_to_tray': 'false'}, 'services': {'lastfm_enabled': 'false'},
    })
    db = DatabaseManager(str(database))
    with db.conn:
        db.conn.execute("UPDATE playlists SET name='Evening selection' WHERE id=(SELECT MIN(id) FROM playlists)")
        playlist_id = db.conn.execute('SELECT MIN(id) FROM playlists').fetchone()[0]
        ids = [row[0] for row in db.conn.execute('SELECT id FROM tracks ORDER BY id LIMIT 4')]
        db.conn.executemany('INSERT INTO playlist_tracks (playlist_id,track_id,position) VALUES (?,?,?)',
                            [(playlist_id, track_id, i) for i, track_id in enumerate(ids)])
    db.close()
    spec = scratch / 'spec.json'
    spec.write_text(json.dumps({'scenario': 'startup', 'profile_root': str(scratch), 'out_dir': str(out), 'settle_sec': .5}), encoding='utf-8')
    env = profile.child_env(scratch, extra={
        'HOME': str(scratch), 'APPDATA': str(scratch / 'AppData/Roaming'),
        'LOCALAPPDATA': str(scratch / 'AppData/Local'),
        'NEDOTIFY_BENCH_SPEC': str(spec), 'NEDOTIFY_BENCH_RESULTS': str(out / 'result.json'),
        'NEDOTIFY_BENCH_MODE': 'recommendation-features-native', 'NEDOTIFY_BENCH_TRANSPORT': 'native',
        'NEDOTIFY_BENCH_PROFILE': str(scratch),
    })
    print(json.dumps({'profile': str(scratch), 'results': str(out)}), flush=True)
    with (out / 'child.log').open('w', encoding='utf-8') as log:
        child = subprocess.Popen([sys.executable, str(Path(__file__)), '--child'], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            child.wait(timeout=240)
        except subprocess.TimeoutExpired:
            subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'], capture_output=True)
            raise
    result = json.loads((out / 'result.json').read_text(encoding='utf-8'))
    print(json.dumps(result, ensure_ascii=True, indent=2))
    if not result['ok']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
