"""Execute first-launch guards and playlist validation, including legacy profiles."""
from pathlib import Path

from tests.jsdom import run_node, source


def onboarding_js(body):
    run_node(r"""
import assert from 'node:assert/strict';import vm from 'node:vm';
const storage=new Map();let queries=0,applies=0;
const wizard={hidden:true,querySelectorAll(){queries++;throw new Error('Completed profiles must not build the wizard')}};
const window={settings:{},addEventListener(){}};
const localStorage={getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)};
const context=vm.createContext({window,localStorage,URL,console,Date,setTimeout,
    applySettings:()=>applies++,applySettingsFromBackend:()=>applies++,
    document:{getElementById:()=>wizard}});
vm.runInContext(SOURCE.replace(/^import .*;\r?$/gm,'').replace(/\bexport\s+/g,'')+'\nglobalThis.subject={initOnboarding,validatePlaylistUrl};',context);
const subject=context.subject;
""".replace('SOURCE',source('onboarding.js'))+body)


def test_playlist_validation_accepts_playlists_and_explains_invalid_links():
    onboarding_js(r"""
for(const url of ['https://www.youtube.com/playlist?list=PL123','https://music.youtube.com/playlist?list=PL123',
 'https://soundcloud.com/artist/sets/album','https://www.deezer.com/ru/playlist/123',
 'https://deezer.com/playlist/123','https://link.deezer.com/s/abc'])assert.equal(subject.validatePlaylistUrl(url),'',url);
for(const url of ['', 'music.youtube.com/playlist?list=PL123','https://www.youtube.com/watch?v=123','https://open.spotify.com/track/123',
 'https://music.yandex.ru/album/123','https://open.spotify.com/playlist/123','https://example.com/playlist/123','https://youtube.com.evil.test/playlist?list=123',
 'https://user:password@youtube.com/playlist?list=123','http://www.youtube.com/playlist?list=123'])assert.ok(subject.validatePlaylistUrl(url),url);
""")


def test_onboarding_reentry_control_is_present_in_settings():
    root = Path(__file__).resolve().parents[1]
    html = (root / 'ui/web_new_v2/index.html').read_text(encoding='utf-8')
    settings = (root / 'ui/web_new_v2/js/settings-panel.js').read_text(encoding='utf-8')
    assert 'id="settings-reopen-onboarding"' in html
    assert "getElementById('settings-reopen-onboarding')?.addEventListener('click', reopenOnboarding)" in settings


def test_legacy_completion_flag_keeps_existing_profiles_out_of_wizard():
    onboarding_js(r"""
storage.set('aura_onboarding_done','true');
    const first=subject.initOnboarding(),second=subject.initOnboarding();
    assert.equal(first,second);await first;assert.equal(queries,0);assert.equal(wizard.hidden,true);
    assert.equal(storage.get('aura_onboarding_done'),'true','legacy completion must remain until backend migration succeeds');
""")


def test_legacy_completion_is_migrated_before_local_marker_is_removed():
    onboarding_js(r"""
storage.set('aura_onboarding_done','true');
const saved=[];window.pywebview={api:{save_setting:async(...args)=>{saved.push(args);return {success:true}}}};
await subject.initOnboarding();
assert.deepEqual(saved,[['first_launch_done',true,'general']]);
assert.equal(storage.has('aura_onboarding_done'),false);
assert.equal(window.settings.general.first_launch_done,true);
assert.equal(queries,0);
""")


def test_fresh_backend_settings_are_awaited_without_flashing_first_launch():
    onboarding_js(r"""
let resolveSettings;window.nedotifySettingsReady=new Promise(resolve=>resolveSettings=resolve);
const pending=subject.initOnboarding();await Promise.resolve();assert.equal(queries,0);
window.settings={general:{first_launch_done:true}};resolveSettings();await pending;
assert.equal(queries,0);assert.equal(storage.has('aura_onboarding_done'),false,'backend completion is canonical after restore');
""")


def test_unavailable_local_storage_does_not_block_completed_backend_profile():
    onboarding_js(r"""
localStorage.getItem=()=>{throw new Error('blocked')};localStorage.setItem=()=>{throw new Error('blocked')};
window.settings={personalization:{onboarding_completed:true}};
await subject.initOnboarding();assert.equal(queries,0);assert.equal(wizard.hidden,true);
""")


def test_cold_bridge_is_awaited_before_deciding_this_is_a_new_profile():
    onboarding_js(r"""
let bridgeReady;window.awaitBridge=()=>new Promise(resolve=>bridgeReady=resolve);
const pending=subject.initOnboarding();await Promise.resolve();assert.equal(queries,0);
window.pywebview={api:{get_settings:async()=>({general:{first_launch_done:true}})}};
bridgeReady();await pending;assert.equal(queries,0);assert.equal(applies,2);
assert.equal(storage.has('aura_onboarding_done'),false,'backend completion is canonical after restore');
""")


def test_motion_scenes_follow_draft_and_abort_cleans_up_animations():
    run_node(r"""
import assert from 'node:assert/strict';import vm from 'node:vm';
const animations=[],maps=new Map(),listeners={};
class Node {
 constructor(){this.dataset={};this.style={};this.classes=new Set();this.classList={toggle:(k,on)=>on?this.classes.add(k):this.classes.delete(k)};}
 setAttribute(){} prepend(){} append(){} after(){} before(){} remove(){}
 querySelectorAll(){return [new Node(),new Node()]}
 querySelector(key){if(!maps.has(this))maps.set(this,new Map());const m=maps.get(this);if(!m.has(key))m.set(key,new Node());return m.get(key)}
 animate(){let reject;const a={cancelled:false,finished:new Promise((_,r)=>reject=r),cancel(){this.cancelled=true;reject(Error('cancelled'))}};animations.push(a);return a;}
}
const steps=Array.from({length:6},()=>new Node());const wizard=new Node();
wizard.querySelectorAll=key=>key==='.onboarding-step'?steps:[];
const document={hidden:false,createElement:()=>new Node(),addEventListener:(name,fn)=>listeners[name]=fn};
wizard.addEventListener=()=>{};
const controller=new AbortController();
const context=vm.createContext({document,window:{matchMedia:()=>({matches:false,addEventListener(){}})}});
vm.runInContext(SOURCE.replace('export function','function')+';globalThis.mount=mountOnboardingMotion;',context);
const motion=context.mount(wizard,{signal:controller.signal});
motion.preview({uiStyle:'macos',crossfade:true,sources:{youtube:false,soundcloud:true},format:'flac'});
assert.equal(wizard.dataset.previewStyle,'macos');assert.equal(wizard.dataset.previewCrossfade,'true');
motion.step(3,2);assert.equal(wizard.dataset.motionStep,'3');assert.ok(animations.length>0);
const first=[...animations];motion.step(2,3);assert.ok(first.every(a=>a.cancelled));
controller.abort();assert.ok(animations.every(a=>a.cancelled));await Promise.resolve();
document.hidden=true;listeners.visibilitychange();assert.equal(wizard.dataset.documentHidden,'true');
""".replace('SOURCE',source('onboarding-motion.js')))
