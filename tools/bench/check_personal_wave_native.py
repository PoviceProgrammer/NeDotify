"""Live personal wave UI/queue smoke in the existing disposable native harness."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.bench import check_windows_live_native_20261109 as native


def scenario(ctx):
    result=ctx.js_async(r'''async()=>{
        const api=window.pywebview.api;
        const player=await import(new URL('./js/player.js',location.href));player.applyMuteState(true);
        await api.save_setting('favorite_artists',['9mice','Heronwater','KAI ANGEL'],'personalization');
        const wait=async(test,ms=35000)=>{const end=performance.now()+ms;while(performance.now()<end){if(await test())return;await new Promise(r=>setTimeout(r,150))}throw Error('Wave UI timeout: '+document.querySelector('.personal-wave-status')?.textContent)};
        await wait(()=>document.querySelector('.personal-wave button')?.disabled===false);
        document.querySelector('.personal-wave button').click();
        await wait(()=>document.querySelector('.personal-wave button')?.disabled===false);
        await wait(()=>document.querySelectorAll('.personal-wave-tracks .track-item').length>=60);
        const count=document.querySelectorAll('.personal-wave-tracks .track-item').length;
        const expectedTitle=document.querySelectorAll('.personal-wave-tracks .track-item')[3].querySelector('.track-title').textContent;
        document.querySelectorAll('.personal-wave-tracks .track-item')[3].click();
        await wait(async()=>{const q=await api.get_queue();return q.tracks.length>=60&&q.current_track?._personal_wave_session&&q.current_index===3});
        const queue=await api.get_queue();
        if(queue.current_track.title!==expectedTitle)throw Error('Wave track/queue mismatch');
        await wait(()=>{const c=player.getLyricsPlaybackClock();return !c.paused&&!c.buffering&&c.positionMs>300});
        document.getElementById('pb-btn-play').click();
        document.querySelector('.personal-wave').scrollIntoView({block:'start'});
        return {shelfTracks:count,queueTracks:queue.tracks.length,chosenIndex:queue.current_index,realStreamAdvancing:true,fixtures:false};
    }''',timeout=115)
    (Path(ctx.spec['out_dir'])/'personal-wave.png').write_bytes(ctx.sess.screenshot_png())
    return result


native.__file__=__file__
native.scenario=scenario
if __name__=='__main__':
    raise SystemExit(native.main())
