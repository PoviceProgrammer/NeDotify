"""Presentation persistence and the pack's actual local HTTP contract."""
import io
import json
from pathlib import Path
import shutil
import subprocess
from wsgiref.util import setup_testing_defaults

import bottle
import pytest

from core.ui_assets import install_macos_assets

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('path,status,mime', [
    ('tokens.css', 200, 'text/css'), ('interface.css', 200, 'text/css'), ('settings.css', 200, 'text/css'), ('library.css', 200, 'text/css'),
    ('assets/atmosphere-dusk.png', 200, 'image/png'),
    ('missing.css', 404, None), ('../web_new_v2/index.html', 404, None),
    ('../../core/settings.py', 404, None), ('/etc/passwd', 404, None),
])
def test_pack_assets(path, status, mime):
    app = bottle.Bottle()
    @app.get('/<file:path>')
    def existing_webview_catchall(file):
        return bottle.HTTPError(404, 'Outside the main UI root')
    install_macos_assets(app, ROOT)
    env = {}
    setup_testing_defaults(env)
    env.update(PATH_INFO='/MACos_ui/' + path, **{'wsgi.input': io.BytesIO()})
    response = {}
    def start(status, headers, exc_info=None):
        response.update(status=int(status.split()[0]), headers=dict(headers))
    result = app(env, start)
    try:
        body = b''.join(result)
    finally:
        if hasattr(result, 'close'):
            result.close()
    assert response['status'] == status
    if mime:
        assert mime in response['headers']['Content-Type']
        assert (b'data-ui-style="macos"' if mime == 'text/css' else b'\x89PNG') in body


def test_presentation_state_without_playback_dependencies():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node unavailable')
    source = (ROOT / 'ui/web_new_v2/js/ui-style.js').read_text(encoding='utf-8')
    script = r'''
    const vm = require('node:vm'), assert = require('node:assert/strict');
    const source = SOURCE;
    function boot(cache = {}) {
        const props = new Map(), stored = new Map(Object.entries(cache)), callbacks = {};
        const classes = new Set();
        const root = {dataset:{},classList:{contains:k=>classes.has(k)},style:{getPropertyValue:k=>props.get(k)||'',setProperty:(k,v)=>props.set(k,v)}};
        const media = {matches:false,addEventListener:(key, fn)=>callbacks.system=fn};
        const window = {matchMedia:()=>media,dispatchEvent:()=>{},addEventListener:()=>{},settings:{}};
        const document = {documentElement:root,querySelectorAll:()=>[],getElementById:()=>null};
        const localStorage = {getItem:k=>stored.get(k)??null,setItem:(k,v)=>stored.set(k,v)};
        const context = vm.createContext({window,document,localStorage,Event:class{},MutationObserver:class{observe(){}},
          getComputedStyle:()=>({getPropertyValue:()=> '24, 214, 162'})});
        vm.runInContext(source,context);
        return {app:window.NeDotifyAppearance,root,stored,window,media,callbacks,props,classes};
    }
    let t = boot({'nedotify_interface_ui_style':'broken JSON'});
    assert.equal(t.root.dataset.uiStyle,'current');
    t.app.init(()=>Promise.resolve(true));
    t.app.restore({interface:{ui_style:'macos',macos_mode:'light'}});
    assert.equal(t.root.dataset.uiStyle,'macos');assert.equal(t.root.dataset.macosMode,'light');
    assert.equal(t.stored.get('nedotify_interface_ui_style'),'"macos"');
    const restarted=boot(Object.fromEntries(t.stored));
    assert.equal(restarted.root.dataset.uiStyle,'macos');assert.equal(restarted.root.dataset.macosMode,'light');
    t.app.apply('macos','system');t.media.matches=true;t.callbacks.system();
    assert.equal(t.root.dataset.macosMode,'dark');
    t.app.restore({interface:{ui_style:'current',macos_mode:'system'}});
    assert.equal(t.root.dataset.uiStyle,'current');
    t.app.apply('untrusted','invalid');assert.equal(t.root.dataset.uiStyle,'current');
    // Reading storage errors must not stop first paint.
    t.app.restore({theme:{theme:'midnight'}});assert.equal(t.root.dataset.uiStyle,'current');
    t.window.settings={optimization:{performance_preset:'low',resource_blur:false,resource_bg:true}};
    t.classes.add('perf-low');t.app.refresh();
    assert.equal(t.root.dataset.macosTransparency,'false');
    assert.equal(t.root.dataset.macosBackground,'true');
    t.window.settings.optimization.resource_bg=false;t.app.refresh();
    assert.equal(t.root.dataset.macosBackground,'false');
    '''.replace('SOURCE', json.dumps(source))
    result = subprocess.run([node, '-e', script], capture_output=True, text=True, encoding='utf-8', timeout=15)
    assert result.returncode == 0, result.stderr


def test_style_survives_database_restart(tmp_path, redirect_home):
    from core.database import DatabaseManager
    from core.settings import SettingsManager
    db = DatabaseManager(str(tmp_path / 'style.db'))
    settings = SettingsManager(db)
    assert settings.get('interface', 'ui_style') == 'current'
    settings.set('interface', 'ui_style', 'macos')
    settings.set('interface', 'macos_mode', 'light')
    assert settings.sync_flush_now()
    restored = SettingsManager(db)
    assert restored.get('interface', 'ui_style') == 'macos'
    assert restored.get('interface', 'macos_mode') == 'light'


def test_wallpaper_load_failure_and_settings_preview():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node unavailable')
    source = (ROOT / 'ui/web_new_v2/js/ui-style.js').read_text(encoding='utf-8')
    script = r'''
    const assert=require('node:assert/strict'),vm=require('node:vm');
    const props=new Map(),images=[],elements=new Map();
    for(const id of ['macos-backdrop','macos-effects-status','macos-background-status','macos-enable-effects'])elements.set(id,{style:{},textContent:'',addEventListener(){}});
    const root={dataset:{},classList:{contains:()=>false},style:{getPropertyValue:k=>props.get(k)||'',setProperty:(k,v)=>props.set(k,v)}};
    const window={settings:{optimization:{performance_preset:'low',resource_blur:false,resource_bg:true},theme:{custom_bg_image:'broken'}},matchMedia:()=>({matches:false,addEventListener(){}}),dispatchEvent(){},addEventListener(){}};
    const document={documentElement:root,body:{classList:{contains:()=>false}},getElementById:k=>elements.get(k)||null,querySelectorAll:()=>[]};
    class Image{constructor(){images.push(this);}}
    const context=vm.createContext({window,document,Image,Event:class{},MutationObserver:class{observe(){}},localStorage:{getItem:()=>null},setTimeout:()=>1,clearTimeout(){},getComputedStyle:()=>({getPropertyValue:()=> '0, 122, 255'})});
    vm.runInContext(SOURCE,context);window.NeDotifyAppearance.init(()=>Promise.resolve(true));
    const background=elements.get('macos-backdrop');
    assert.equal(root.dataset.macosBackground,'true');assert.equal(root.dataset.macosTransparency,'false');
    images[0].onerror();assert.equal(background.style.backgroundImage,'');
    assert.match(elements.get('macos-background-status').textContent,/встроенный/);
    window.settings.theme.custom_bg_image='first';window.NeDotifyAppearance.refresh();
    const stale=images[1].onload;
    window.settings.theme.custom_bg_image='second';window.NeDotifyAppearance.refresh();
    stale();assert.equal(background.style.backgroundImage,'');
    images[2].onload();assert.match(background.style.backgroundImage,/second/);
    window.settings.theme.bg_blur=12;window.settings.theme.bg_dim=20;window.NeDotifyAppearance.refresh();
    assert.equal(props.get('--mac-wallpaper-blur'),'12px');assert.equal(props.get('--mac-wallpaper-dim'),'0.2');
    assert.equal(images.length,3,'slider previews must reuse the loaded image');
    window.settings.theme.custom_bg_image='';window.NeDotifyAppearance.refresh();assert.equal(background.style.backgroundImage,'');
    window.settings.optimization.resource_bg=false;window.NeDotifyAppearance.refresh();assert.equal(root.dataset.macosBackground,'false');
    '''.replace('SOURCE', json.dumps(source))
    result = subprocess.run([node, '-e', script], capture_output=True, text=True, encoding='utf-8', timeout=15)
    assert result.returncode == 0, result.stderr


def test_slider_keyboard_uses_existing_seek_and_volume_callbacks():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node unavailable')
    source = (ROOT / 'ui/web_new_v2/js/player.js').read_text(encoding='utf-8')
    source = source[source.index('function setupDragBar('):source.index('\nfunction api(method,')]
    script = r'''
    const assert=require('node:assert/strict'),vm=require('node:vm');
    const listeners={},calls=[];
    const track={addEventListener:(k,f)=>listeners[k]=f,getAttribute:()=> '25'};
    const context=vm.createContext({document:{getElementById:()=>track},playbackState:{durationMs:120000}});
    vm.runInContext(SOURCE,context);
    context.setupDragBar('pb-progress-track',{onDrag:v=>calls.push(v),onRelease:v=>calls.push(v)});
    const key=(key,ctrlKey=false)=>listeners.keydown({key,ctrlKey,preventDefault(){},stopPropagation(){}});
    key('ArrowRight');assert.equal(calls.length,2);assert.ok(Math.abs(calls[1]-35/120)<.00001);
    key('Home');assert.equal(calls.at(-1),0);key('End');assert.equal(calls.at(-1),1);
    const count=calls.length;key('ArrowRight',true);assert.equal(calls.length,count);
    context.setupDragBar('pb-volume-track',{onDrag:v=>calls.push(v),onRelease:v=>calls.push(v)});
    key('ArrowUp');assert.equal(calls.at(-1),.3);
    '''.replace('SOURCE', json.dumps(source))
    result = subprocess.run([node, '-e', script], capture_output=True, text=True, encoding='utf-8', timeout=10)
    assert result.returncode == 0, result.stderr
