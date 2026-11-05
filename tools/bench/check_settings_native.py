"""Real WebView2 + real bridge/settings/SQLite in an isolated scratch profile.

Run with .venv_win/Scripts/python.exe tools/bench/check_settings_native.py.
Uses bench_child's native transport and startup hooks, never api_stubs.
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


MOUNT = """async style => {
    const module=await import(new URL('./js/settings.js',location.href));
    await window.pywebview.api.save_setting('ui_style',style,'interface');
    window.settings=await window.pywebview.api.get_settings();
    module.applySettingsFromBackend(window.settings);await module.ensureSettingsPanel();
    window.showPage('settings');
    await (await import(new URL('./js/equalizer.js',location.href))).initEqualizer();
    return [...document.querySelectorAll('#view-settings input[type=range]')].map(el=>({
        selector:el.id?'#'+el.id:el.dataset.atmosphereKey?`[data-atmosphere-key="${el.dataset.atmosphereKey}"]`:`.eq-band-slider[data-group="${el.dataset.group}"]`,
        value:Number(el.value),min:Number(el.min),max:Number(el.max),step:Number(el.step)||1
    }));
}"""


def scenario(ctx):
    results = []
    out = Path(ctx.spec['out_dir'])
    out.mkdir(parents=True, exist_ok=True)
    for style in ('current', 'macos'):
        inventory = ctx.js_async(MOUNT, json.dumps(style))
        expected = []
        for item in inventory:
            value = round(item['min'] + int((item['max'] - item['min']) / item['step'] * .6) * item['step'], 2)
            if value == item['value']:
                value = round(item['min'] + item['step'], 2)
            result = ctx.js_async("""async ({selector,value})=>{
                const el=document.querySelector(selector);
                el.disabled=false;el.closest('details')?.setAttribute('open','');
                el.value=String(value);el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));
                await new Promise(r=>setTimeout(r,selector.includes('eq-')?350:60));
                const settings=await window.pywebview.api.get_settings();
                const macos=document.documentElement.dataset.uiStyle==='macos';
                const fields={
                    'slider-font-size':macos?['interface','macos_font_size']:['theme','font_size'],
                    'slider-glass-blur':macos?['interface','macos_blur']:['theme','glass_blur'],
                    'slider-transparency-level':['theme','transparency_level'],'slider-border-radius':['interface','border_radius'],
                    'player-progress-transparency':['player','progress_transparency'],'slider-bg-blur':['theme','bg_blur'],
                    'slider-bg-dim':['theme','bg_dim'],'slider-crossfade-sec':['audio','crossfade_duration_sec'],
                    'slider-unfocus-fps':['efficiency','unfocus_fps_limit'],'slider-fps-particles':['optimization','fps_particles'],
                    'slider-fps-visualizer':['optimization','fps_visualizer'],'slider-fps-ui':['optimization','fps_ui'],
                    'eq-preamp':['equalizer','preamp']
                };
                let actual;
                if(el.dataset.atmosphereKey)actual=el.dataset.atmosphereKey.split('.').reduce((node,key)=>node[key],settings.atmosphere);
                else if(el.classList.contains('eq-band-slider'))actual=settings.equalizer.bands[Number(el.dataset.group)];
                else {const [category,key]=fields[el.id];actual=settings[category][key];}
                if(actual!==value)throw new Error(selector+' actual bridge read='+actual+' expected='+value);
                return {value:Number(document.querySelector(selector).value),persisted:actual};
            }""", json.dumps({'selector': item['selector'], 'value': value}))
            assert result['value'] == value, (style, item, result['value'])
            expected.append((item['selector'], value))
        eq = ctx.js_async("""async()=>{
            const api=window.pywebview.api;
            const accepted=await api.set_equalizer(2.5,[-20,-12,-8,-2,0,.5,2,8,12,20],6);
            return {accepted,restored:await api.get_equalizer()};
        }""")
        assert eq['accepted'] is True and eq['restored']['mode'] == '6', eq
        # Return to the 10-band layout used in inventory; verify mode6 separately in SQLite.
        assert ctx.js_async("async()=>window.pywebview.api.set_equalizer(6,Array(10).fill(4),10)") is True
        for index, row in enumerate(expected):
            if row[0] == '#eq-preamp': expected[index] = (row[0], 6)
            elif row[0].startswith('.eq-band-slider'): expected[index] = (row[0], 4)
        origin = ctx.js('performance.timeOrigin')
        ctx.sess.ws.call('Page.reload', {'ignoreCache': True})
        ctx.sess.wait_for_new_document(origin, timeout=90)
        ctx.sess.wait_for_js('window._nedotifyInitialized === true', timeout=90)
        restored = ctx.js_async(MOUNT, json.dumps(style))
        values = {row['selector']: row['value'] for row in restored}
        for selector, value in expected:
            assert values[selector] == value, (style, selector, value, values[selector])
        for panel in ('appearance', 'audio', 'player', 'atmosphere', 'optimization'):
            ctx.js(f"document.querySelector('[data-panel={panel}]').click()")
            time.sleep(.15)
            (out / f'{style}-{panel}.png').write_bytes(ctx.sess.screenshot_png())
        results.append({'style': style, 'sliders': len(inventory), 'reloaded': True, 'mode6': eq})
    return {'actual_bridge': True, 'api_stubs': False, 'skins': results}


def main():
    if '--child' in sys.argv:
        from tools.bench import bench_child
        bench_child.scenarios.scenario_startup = scenario  # measurement hook only
        bench_child.main()
        return
    from tools.bench import profile
    scratch = Path(tempfile.mkdtemp(prefix='nedotify-settings-native-'))
    out = ROOT / 'tools' / 'bench' / 'results' / ('settings-native-' + time.strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True, exist_ok=True)
    profile.seed_db(scratch / '.nedotify' / 'nedotify_storage.db', [], [], settings={
        'app': {'close_to_tray': False}, 'services': {'lastfm_enabled': False},
        'equalizer': {'mode': 10},
    })
    spec = scratch / 'spec.json'
    spec.write_text(json.dumps({'scenario': 'startup', 'profile_root': str(scratch), 'out_dir': str(out), 'settle_sec': .5}), encoding='utf-8')
    env = profile.child_env(scratch, debug_port=9337, extra={
        'HOME': str(scratch), 'APPDATA': str(scratch / 'AppData' / 'Roaming'),
        'LOCALAPPDATA': str(scratch / 'AppData' / 'Local'),
        'NEDOTIFY_BENCH_SPEC': str(spec), 'NEDOTIFY_BENCH_RESULTS': str(out / 'result.json'),
        'NEDOTIFY_BENCH_MODE': 'settings-native', 'NEDOTIFY_BENCH_TRANSPORT': 'native',
        'NEDOTIFY_BENCH_PROFILE': str(scratch),
    })
    print(json.dumps({'profile': str(scratch), 'results': str(out)}), flush=True)
    with (out / 'child.log').open('w', encoding='utf-8') as log:
        proc = subprocess.Popen([sys.executable, str(Path(__file__)), '--child'], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            proc.wait(timeout=300)
        except subprocess.TimeoutExpired:
            subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True)
            raise
    result = json.loads((out / 'result.json').read_text(encoding='utf-8'))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result['ok']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
