"""Native Windows CPU/RAM/GPU and style-work control with full visual effects."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import wave

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

INSTRUMENT = r'''(() => {
    window.__resourceCounts = {rect:{},style:0,clear:{}};
    const rect=Element.prototype.getBoundingClientRect;
    Element.prototype.getBoundingClientRect=function(...args){
        const c=window.__resourceCounts, id=this.id||this.tagName;
        c.rect[id]=(c.rect[id]||0)+1;return rect.apply(this,args);
    };
    const computed=window.getComputedStyle;
    window.getComputedStyle=function(...args){window.__resourceCounts.style++;return computed.apply(this,args)};
    const clear=CanvasRenderingContext2D.prototype.clearRect;
    CanvasRenderingContext2D.prototype.clearRect=function(...args){
        const c=window.__resourceCounts,id=this.canvas.id||'unnamed';
        c.clear[id]=(c.clear[id]||0)+1;return clear.apply(this,args);
    };
    return true;
})()'''


def scenario(ctx):
    from tools.bench import procsampler, scenarios
    from tools.bench.windows_gpu import WindowsGpuSampler
    ctx.js(INSTRUMENT)
    track = {'source':'local','source_id':'resource-audio','title':'Native resource fixture',
             'artist':'Benchmark','duration':180,'file_path':os.environ['NEDOTIFY_RESOURCE_AUDIO'],
             'cover_path':os.environ['NEDOTIFY_RESOURCE_COVER']}
    ctx.js_async(r'''async track => {
        const result=await window.pywebview.api.play_track(track,[track],0);
        window.showPage('player');
        const player=await import(new URL('./js/player.js',location.href));
        const deadline=performance.now()+10000;
        while(performance.now()<deadline){
            const clock=player.getLyricsPlaybackClock();
            if(!clock.paused&&!clock.buffering&&clock.positionMs>100)return result;
            await new Promise(r=>setTimeout(r,100));
        }
        throw Error('Native fixture did not start');
    }''', json.dumps(track))
    outcomes = []
    seconds = int(os.environ.get('NEDOTIFY_RESOURCE_SECONDS','10'))
    with WindowsGpuSampler() as gpu:
        for skin in ('current','macos'):
            for progress in ('panel','solid'):
                ctx.js_async(r'''async state => {
                    const api=window.pywebview.api;
                    await api.save_setting('ui_style',state.skin,'interface');
                    await api.save_setting('slider_type',state.progress,'player');
                    const settings=await import(new URL('./js/settings.js',location.href));
                    settings.applySettingsFromBackend(await api.get_settings());
                    return true;
                }''', json.dumps({'skin':skin,'progress':progress}))
                time.sleep(2)
                before = ctx.perf_metrics()
                ctx.js("window.__resourceCounts={rect:{},style:0,clear:{}}")
                sampler=procsampler.ProcSampler(pid=os.getpid())
                sampler._prime()
                gpu_rows=[]
                started=time.monotonic()
                for _ in range(seconds):
                    time.sleep(1)
                    sampler.samples.append(sampler._take())
                    _, children=sampler._tree_pids(os.getpid())
                    gpu_rows.append(gpu.sample({os.getpid(),*children}))
                elapsed=time.monotonic()-started
                after=ctx.perf_metrics()
                counts=ctx.js('window.__resourceCounts')
                perf={key:round(after[key]-before[key],5) for key in scenarios.CDP_DELTA_KEYS
                      if isinstance(before.get(key),(int,float)) and isinstance(after.get(key),(int,float))}
                state=ctx.js(r'''(() => ({hidden:document.hidden,skin:document.documentElement.dataset.uiStyle,
                    progress:document.documentElement.dataset.progressStyle,
                    fps:getComputedStyle(document.documentElement).getPropertyValue('--ui-fps'),
                    canvases:[...document.querySelectorAll('canvas')].map(c=>({id:c.id,width:c.width,height:c.height})),
                    viewport:[innerWidth,innerHeight,devicePixelRatio]}))()''')
                image_path=Path(os.environ['NEDOTIFY_BENCH_RESULTS']).parent/f'{skin}-{progress}.png'
                image_path.write_bytes(ctx.sess.screenshot_png())
                row={'skin':skin,'progress':progress,'seconds':round(elapsed,3),'state':state,
                     'process':sampler.summary(),'gpu_samples':gpu_rows,'cdp_delta':perf,'counts':counts,
                     'screenshot':str(image_path)}
                outcomes.append(row)
                valid_gpu=[r for r in gpu_rows if r.get('available')]
                print('[resources] '+json.dumps({'skin':skin,'progress':progress,
                    'cpu_one_core_mean':row['process'].get('tree_cpu_pct',{}).get('mean'),
                    'rss_mib_mean':row['process'].get('tree_rss_mb',{}).get('mean'),
                    'gpu_busiest_mean':sum(r['busiest_engine_pct'] for r in valid_gpu)/max(1,len(valid_gpu)),
                    'style_sec':perf.get('RecalcStyleDuration'),'style_count':perf.get('RecalcStyleCount'),
                    'rects':counts.get('rect',{}).get('pb-progress-track',0)}),flush=True)
    return {'api_stubs':False,'audio':'generated PCM fixture','full_visual_settings':True,'cases':outcomes,
            'cpu_basis':'100% = one logical core; process tree includes WebView2',
            'gpu_basis':'busiest per-process engine percentage, not whole-GPU total',
            'memory_basis':'summed RSS includes shared browser pages; GPU memory recorded separately'}


def main():
    if '--child' in sys.argv:
        from tools.bench import bench_child
        bench_child.scenarios.scenario_startup=scenario
        bench_child.main()
        return 0
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label',default='baseline')
    parser.add_argument('--seconds',type=int,default=10)
    args=parser.parse_args()
    from tools.bench import profile
    import numpy as np
    with tempfile.TemporaryDirectory(prefix='nedotify-resources-') as folder:
        scratch=Path(folder)
        out=ROOT/'tools/bench/results'/('resources-'+args.label+'-'+time.strftime('%Y%m%d-%H%M%S'))
        out.mkdir(parents=True)
        covers=profile.write_covers(scratch)
        audio=scratch/'.nedotify/resource.wav'
        rate=22050
        t=np.arange(rate*180,dtype=np.float32)/rate
        pulse=np.exp(-np.mod(t,.48)*15)
        samples=(.015*np.sin(2*np.pi*80*t)*pulse+.002*np.sin(2*np.pi*1200*t)).astype(np.float32)
        with wave.open(str(audio),'wb') as stream:
            stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(rate)
            stream.writeframes((samples*32767).astype('<i2').tobytes())
        tracks=profile.make_track_specs(500)
        for track in tracks:
            track.update(source='local',file_path=str(audio),is_downloaded=1)
        settings={'app':{'close_to_tray':'false'},'audio':{'volume':'5'},
            'services':{'youtube_enabled':'false','soundcloud_enabled':'false'},
            'theme':{'transparency_enabled':'true','glass_blur':'15','custom_bg_image':str(covers[0])},
            'interface':{'transparency_enabled':'true','glass_blur':'15','macos_blur':'38'},
            'optimization':{'blur_quality':'hq','resource_blur':'true','fps_ui':'60','fps_particles':'60','resource_particles':'true'},
            'atmosphere':{'enabled':'true','quality':'high','intensity':'.7',
                'effects':json.dumps({'rain':True,'fog':True,'snow':False,'thunderstorm':True})}}
        profile.seed_db(scratch/'.nedotify/nedotify_storage.db',tracks,covers,settings=settings)
        spec=scratch/'spec.json'
        spec.write_text(json.dumps({'scenario':'startup','profile_root':str(scratch),'settle_sec':3}),encoding='utf-8')
        env=profile.child_env(scratch,extra={key:str(scratch) for key in ('HOME','APPDATA','LOCALAPPDATA')})
        env.update(NEDOTIFY_BENCH_SPEC=str(spec),NEDOTIFY_BENCH_RESULTS=str(out/'result.json'),
                   NEDOTIFY_BENCH_MODE='resources-native',NEDOTIFY_BENCH_TRANSPORT='native',
                   NEDOTIFY_RESOURCE_AUDIO=str(audio),NEDOTIFY_RESOURCE_COVER=covers[0],
                   NEDOTIFY_RESOURCE_SECONDS=str(args.seconds))
        with (out/'child.log').open('w',encoding='utf-8') as log:
            child=subprocess.Popen([sys.executable,__file__,'--child'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            try:child.wait(timeout=max(180,args.seconds*4+90))
            except subprocess.TimeoutExpired:
                subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],capture_output=True)
                raise
        report=json.loads((out/'result.json').read_text(encoding='utf-8'))
        print(json.dumps({'artifact':str(out/'result.json'),'ok':report['ok'],'error':report.get('error')}))
        return 0 if report['ok'] else 1


if __name__=='__main__':
    raise SystemExit(main())
