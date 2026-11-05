"""Exercise settings callbacks, restoration and bridge failures with real JS."""
from pathlib import Path

from tests.jsdom import run_node, source

ROOT = Path(__file__).resolve().parents[1]


def settings_js(body):
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const elements = new Map(), storage = new Map(), calls = [], toasts = [];
function element(id, min=0, max=100, value=0) {
    const classes = new Set(), listeners = new Map(), props = new Map(), attributes = new Map();
    const item = {id,min,max,value,disabled:false,style:{setProperty:(k,v)=>props.set(k,v),getPropertyValue:k=>props.get(k),removeProperty:k=>props.delete(k)},
      classList:{contains:k=>classes.has(k),add:(...ks)=>ks.forEach(k=>classes.add(k)),remove:(...ks)=>ks.forEach(k=>classes.delete(k)),toggle(k,on=!classes.has(k)){on?classes.add(k):classes.delete(k);return on}},
      addEventListener:(k,fn)=>listeners.set(k,fn),removeEventListener:k=>listeners.delete(k),
      fire:async k=>listeners.get(k)?.({target:item}),querySelectorAll:()=>[],setAttribute:(k,v)=>attributes.set(k,String(v)),getAttribute:k=>attributes.get(k)??null};
    elements.set(id,item);return item;
}
const root = element('root');root.dataset={};
const context=vm.createContext({console,Promise,Number,Math,JSON,Date,getComputedStyle:()=>({getPropertyValue:()=>''}),
    window:{settings:{},addEventListener(){},dispatchEvent(){},pywebview:{api:{save_setting:(...args)=>{calls.push(args);return true}}}},
    document:{documentElement:root,body:root,getElementById:id=>elements.get(id)||null,
      querySelector:selector=>elements.get(selector.match(/data-resource="(.*?)"/)?.[1])||null,
      querySelectorAll:()=>[],addEventListener(){},dispatchEvent(){}},
    localStorage:{getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
    CustomEvent:class {constructor(type,options){this.type=type;this.detail=options?.detail}},
    showToast:(...args)=>toasts.push(args),initParticles(){},stopParticles(){},setParticlesFps(){},setVisualizerFps(){},setUiFps(){},
    setVisualizerEnabled:(...args)=>calls.push(['visualizer',...args]),applyAudioSettings(){},
    syncCustomColorFields(){},syncThemeSelection(){},renderIcons(){},evaluateEfficiencyState(){},
    restoreAtmosphereSettings(){},restoreDiscordSettings(){},
});
vm.runInContext((ALIASES + "\n" + SOURCE + "\n" + PANEL).replace(/^import .*;\r?$/gm,'').replace(/\bexport\s+/g,'')+
    '\napplyAuraOrbs=()=>{};globalThis.subject={applySettingsFromBackend,getSavedCustomThemes,setupSlider,setupToggle,saveSetting,setupOptimizationPanel,applyPerformancePreset,setupZapretPanel,applyTransparency,syncSlider,applyCustomBg,initPrivacySettings,syncPrivacySettings,applyBorderRadius};',context);
const {subject,window}=context;
""".replace('ALIASES', source('setting-aliases.js')).replace('SOURCE', source('settings.js')).replace('PANEL', source('settings-panel.js')) + body)


def test_audio_settings_apply_immediately_and_aliases_roll_back_together():
    settings_js(r"""
window.settings={audio:{crossfade_duration:3,crossfade_duration_sec:3}};
const gains=[];context.applyAudioSettings=audio=>gains.push(audio.crossfade_duration);
window.pywebview.api.save_setting=()=>false;
assert.equal(await subject.saveSetting('crossfade_duration_sec',8,'audio'),false);
assert.equal(gains[0],8,'audio consumer is updated without a restart');
assert.equal(window.settings.audio.crossfade_duration,3);
assert.equal(window.settings.audio.crossfade_duration_sec,3);
assert.equal(storage.get('nedotify_audio_crossfade_duration'),'3');
""")


def test_retired_flow_preferences_do_not_activate_a_consumer():
    settings_js(r"""
window.settings={};const applied=[];context.setFlowEnabled=value=>applied.push(value);
subject.applySettingsFromBackend({audio:{queue_autopilot:true,flow_enabled:true}});
assert.equal(applied.length,0);
""")


def test_empty_backend_theme_collection_does_not_revive_a_stale_browser_copy():
    settings_js(r"""
storage.set('nedotify_custom_themes',JSON.stringify([{name:'Old',palette:{'--primary':'#118855'}}]));
assert.equal(subject.getSavedCustomThemes({custom_themes:[]}).length,0);
""")


def test_synchronous_bridge_failure_restores_atmosphere_switch_and_aliases():
    settings_js(r"""
const toggle=element('toggle-atmosphere'),effects=[];
context.restoreAtmosphereSettings=()=>effects.push(window.settings.atmosphere.enabled?'on':'off');
window.settings={atmosphere:{enabled:false},ui:{particles_enabled:false},optimization:{resource_particles:false}};
subject.setupToggle('toggle-atmosphere','enabled','atmosphere',context.restoreAtmosphereSettings);
window.pywebview.api.save_setting=()=>{throw new Error('bridge unavailable')};
await toggle.fire('click');
assert.equal(window.settings.ui.particles_enabled,false);
assert.equal(window.settings.optimization.resource_particles,false);
assert.equal(toggle.classList.contains('on'),false);
assert.equal(effects.at(-1),'off');
""")


def test_slow_failed_alias_write_does_not_revert_a_newer_preference():
    settings_js(r"""
let rejectOld;window.pywebview.api.save_setting=()=>new Promise(resolve=>rejectOld=()=>resolve(false));
const old=subject.saveSetting('font_family','Inter','theme');
window.pywebview.api.save_setting=()=>true;
assert.equal(await subject.saveSetting('font_family','Arial','interface'),true);
rejectOld();await old;
assert.equal(window.settings.theme.font_family,'Arial');
assert.equal(window.settings.interface.font_family,'Arial');
assert.equal(toasts.length,0);
""")


def test_corner_radius_applies_clamps_and_rolls_back_a_rejected_save():
    settings_js(r"""
const slider=element('slider-border-radius'),label=element('label-border-radius');
window.settings={interface:{border_radius:12}};
assert.equal(subject.applyBorderRadius('18'),18);
assert.equal(root.style.getPropertyValue('--interface-radius'),'18px');
assert.equal(root.style.getPropertyValue('--radius-md'),'18px');
assert.equal(slider.value,18);assert.equal(label.textContent,'18px');
assert.equal(subject.applyBorderRadius(Infinity),12);
assert.equal(subject.applyBorderRadius(-5),0);
assert.equal(subject.applyBorderRadius(200),24);
window.pywebview.api.save_setting=()=>false;
assert.equal(await subject.saveSetting('border_radius',20,'interface'),false);
assert.equal(root.style.getPropertyValue('--interface-radius'),'12px');
""")


def test_slider_previews_current_value_and_commits_decimal_on_change():
    settings_js(r"""
const slider=element('test-slider',0,10,2);
let preview;
context.preview=value=>preview=[value,window.settings.audio.gain];
vm.runInContext("subject.setupSlider('test-slider','gain','audio',preview)",context);
slider.value='2.5';await slider.fire('input');
assert.deepEqual(preview,['2.5',2.5]);
assert.equal(calls.length,0,'Dragging must not write to the backend on every frame');
assert.equal(slider.style.getPropertyValue('--value-percent'),'25%');
slider.value='3.5';await slider.fire('change');
assert.deepEqual(preview,['3.5',3.5]);
assert.deepEqual(calls,[['gain',3.5,'audio']]);
""")


def test_failed_slider_commit_restores_value_before_drag_and_its_audio_effect():
    settings_js(r"""
const slider=element('gain-slider',0,10,2);
window.settings={audio:{gain:2}};
const gains=[];context.applyAudioSettings=audio=>gains.push(audio.gain);
subject.setupSlider('gain-slider','gain','audio',value=>{slider.value=value});
window.pywebview.api.save_setting=()=>false;
slider.value='7';await slider.fire('input');await slider.fire('change');
await new Promise(setImmediate);
assert.equal(window.settings.audio.gain,2,'failed commit restores the value before preview');
assert.equal(Number(slider.value),2,'thumb returns to the saved position');
assert.equal(gains.at(-1),2,'the audio consumer is rolled back too');
""")


def test_reopening_optimization_preserves_custom_blur_and_disabled_effects():
    settings_js(r"""
for(const [id,min,max] of [['glass-blur',0,40],['fps-particles',5,30],['fps-visualizer',10,60],['fps-ui',15,60]]) element('slider-'+id,min,max);
for(const name of ['bg','particles','covers','visualizers','blur']) element(name);
window.settings={theme:{glass_blur:23},ui:{particles_enabled:false,cover_visualizer:false},optimization:{performance_preset:'balanced',blur_quality:'lq',resource_blur:true,fps_particles:17,fps_visualizer:35,fps_ui:50}};
subject.setupOptimizationPanel();subject.setupOptimizationPanel();
assert.equal(root.style.getPropertyValue('--glass-blur'),'23px');
assert.equal(elements.get('slider-fps-particles').value,17);
assert.equal(elements.get('slider-fps-visualizer').value,35);
assert.equal(elements.get('particles').classList.contains('active'),false);
assert.equal(elements.get('visualizers').classList.contains('active'),false);
assert.equal(window.settings.ui.particles_enabled,false);
assert.ok(!calls.some(call=>call[0]!=='visualizer'),'Opening a tab must not save defaults over user settings');
subject.applyPerformancePreset('low');
subject.setupOptimizationPanel();
assert.equal(root.style.getPropertyValue('--glass-blur'),'0px');
assert.equal(window.settings.optimization.glow_quality,'off');
assert.equal(window.settings.optimization.resource_blur,false);
assert.equal(window.settings.theme.glass_blur,0);
""")


def test_failed_setting_writes_report_failure_without_unhandled_rejection():
    settings_js(r"""
window.pywebview.api.save_setting=()=>Promise.reject(new Error('disconnected'));
assert.equal(await subject.saveSetting('autoplay',true,'audio'),false);
window.pywebview.api.save_setting=()=>false;
assert.equal(await subject.saveSetting('autoplay',false,'audio'),false);
window.pywebview.api.save_setting=()=>{throw new Error('bridge gone')};
assert.equal(await subject.saveSetting('autoplay',true,'audio'),false);
assert.equal(toasts.length,3);assert.ok(toasts.every(item=>item[1]==='error'));
""")


def test_secret_settings_are_not_mirrored_to_local_storage():
    settings_js(r"""
await subject.saveSetting('lastfm_api_key','private-key','services');
await subject.saveSetting('lastfm_api_secret','private-secret','services');
await subject.saveSetting('proxy_url','https://user:pass@example.test','auth');
assert.equal(storage.has('nedotify_services_lastfm_api_key'),false);
assert.equal(storage.has('nedotify_services_lastfm_api_secret'),false);
assert.equal(storage.has('nedotify_auth_proxy_url'),false);
assert.equal(calls.length,3,'secrets still persist through the backend bridge');
""")


def test_privacy_controls_save_opt_in_and_keep_lastfm_key_out_of_browser_mirrors():
    settings_js(r"""
const lyrics=element('toggle-lyrics-enabled'),lastfm=element('toggle-lastfm-enabled');
const username=element('input-lastfm-username'),apiKey=element('input-lastfm-api-key');
lyrics.classList.add('on');apiKey.value='';
window.settings={lyrics:{enabled:true},services:{lastfm_enabled:false},auth:{}};
subject.initPrivacySettings();
await lyrics.fire('click');
await lastfm.fire('click');
username.value='  listener42  ';await username.fire('change');
apiKey.value='  private-api-key  ';await apiKey.fire('change');
assert.deepEqual(calls,[['enabled',false,'lyrics'],['lastfm_enabled',true,'services'],['lastfm_username','listener42','auth'],['lastfm_api_key','private-api-key','services']]);
assert.equal(lyrics.classList.contains('on'),false);assert.equal(lyrics.getAttribute('aria-checked'),'false');
assert.equal(lastfm.classList.contains('on'),true);assert.equal(lastfm.getAttribute('aria-checked'),'true');
assert.equal(window.settings.services.lastfm_api_key,'');
assert.equal(window.settings.services.has_lastfm_api_key,true);
assert.equal(storage.has('nedotify_services_lastfm_api_key'),false);
assert.equal(apiKey.value,'');
""")


def test_privacy_settings_restore_masked_credentials_without_exposing_key():
    settings_js(r"""
const lyrics=element('toggle-lyrics-enabled'),lastfm=element('toggle-lastfm-enabled');
const username=element('input-lastfm-username'),apiKey=element('input-lastfm-api-key');
apiKey.value='';
window.settings={};
window.settings.lyrics={enabled:false};
window.settings.services={lastfm_enabled:true,lastfm_api_key:'DO_NOT_RENDER',has_lastfm_api_key:true};
window.settings.auth={lastfm_username:'listener42'};
subject.syncPrivacySettings();
assert.equal(lyrics.classList.contains('on'),false);assert.equal(lyrics.getAttribute('aria-checked'),'false');
assert.equal(lastfm.classList.contains('on'),true);assert.equal(lastfm.getAttribute('aria-checked'),'true');
assert.equal(username.value,'listener42');
assert.equal(apiKey.value,'');
assert.match(apiKey.placeholder,/Ключ сохранён/);
""")


def test_privacy_controls_are_present_in_their_settings_panels():
    from html.parser import HTMLParser

    class ControlsParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = []
            self.controls = {}
            self.disclosure = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            ancestors = {node_id for _, node_id in self.stack if node_id}
            control_id = attrs.get("id")
            if control_id:
                self.controls[control_id] = (tag, attrs, ancestors)
            if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
                self.stack.append((tag, control_id))

        def handle_endtag(self, tag):
            for index in range(len(self.stack) - 1, -1, -1):
                if self.stack[index][0] == tag:
                    del self.stack[index:]
                    break

        def handle_data(self, data):
            if any(node_id == "lastfm-disclosure" for _, node_id in self.stack):
                self.disclosure.append(data)

    parser = ControlsParser()
    parser.feed((ROOT / "ui/web_new_v2/index.html").read_text(encoding="utf-8"))
    lyrics = parser.controls["toggle-lyrics-enabled"]
    assert "settings-audio" in lyrics[2]
    assert lyrics[1].get("role") == "switch"
    for control_id in ("toggle-lastfm-enabled", "input-lastfm-username", "input-lastfm-api-key", "lastfm-disclosure"):
        assert "settings-auth" in parser.controls[control_id][2]
    assert parser.controls["input-lastfm-username"][1].get("type") == "text"
    assert parser.controls["input-lastfm-api-key"][1].get("type") == "password"
    disclosure = " ".join(" ".join(parser.disclosure).split()).lower()
    assert "last.fm" in disclosure
    assert "исполнителя" in disclosure and "недавних треков" in disclosure
    assert "имя пользователя" in disclosure


def test_slider_can_save_separate_values_for_each_interface_style():
    settings_js(r"""
const slider=element('glass',0,40,15);
let macos=true;
context.target=()=>macos?{key:'macos_blur',category:'interface'}:{key:'glass_blur',category:'theme'};
vm.runInContext("subject.setupSlider('glass','glass_blur','theme',undefined,target)",context);
slider.value='32';await slider.fire('input');
assert.equal(window.settings.interface.macos_blur,32);assert.equal(calls.length,0);
await slider.fire('change');assert.deepEqual(calls.at(-1),['macos_blur',32,'interface']);
macos=false;slider.value='12';await slider.fire('change');
assert.deepEqual(calls.at(-1),['glass_blur',12,'theme']);assert.equal(window.settings.interface.macos_blur,32);
""")


def test_legacy_fractional_transparency_is_restored_as_percent():
    settings_js(r"""
const slider=element('slider-transparency-level');
subject.applyTransparency(.8,true);
assert.equal(root.style.getPropertyValue('--app-bg-opacity'),.8);
assert.equal(slider.disabled,false);
subject.applyTransparency(65,true);
assert.equal(root.style.getPropertyValue('--app-bg-opacity'),.65);
subject.applyTransparency(65,false);
assert.equal(root.style.getPropertyValue('--app-bg-opacity'),1);
assert.equal(slider.disabled,true);
""")


def test_legacy_background_blur_is_clamped_to_visible_sixteen_without_other_setting_writes():
    settings_js(r"""
const slider=element('slider-bg-blur',0,16,0), label=element('label-bg-blur');
const background=element('custom-bg-layer'), dim=element('custom-bg-dim-layer');
element('row-custom-bg-preview');element('bg-image-preview');element('app-container');
root.style.setProperty('--app-bg-opacity','0.63');
context.window.NeDotifyAppearance={refresh(){}};
subject.syncSlider('slider-bg-blur',40,'label-bg-blur','px');
assert.equal(slider.value,16);assert.equal(label.textContent,'16px');
subject.applyCustomBg('assets/backgrounds/legacy.jpg',40,30);
assert.equal(background.style.filter,'blur(16px)');
assert.equal(JSON.parse(storage.get('nedotify_theme_bg_blur')),16);
assert.equal(root.style.getPropertyValue('--app-bg-opacity'),'0.63');
assert.equal(calls.length,0,'restoring the old blur must not write unrelated settings');
""")


def test_zapret_reopened_panel_uses_latest_mode_and_failed_stop_restores_state():
    settings_js(r"""
const toggle=element('toggle-zapret-enabled'),select=element('select-zapret-mode');
let status={running:false,mode:'youtube_discord',custom_args:'old'};
window.pywebview.api.get_zapret_status=async()=>status;
// E1 (BUG-009/021 contract): the bridge reports the ACTUAL running state and
// the panel must sync the toggle to it after every apply.
window.pywebview.api.toggle_zapret=async(...args)=>{calls.push(['zapret',...args]);status={...status,running:args[0]};return {success:true,running:args[0]}};
subject.setupZapretPanel();await new Promise(setImmediate);
status={running:false,mode:'custom',custom_args:'new',binary_path:'C:/winws.exe'};
subject.setupZapretPanel();await new Promise(setImmediate);
await toggle.fire('click');await new Promise(setImmediate);
assert.deepEqual(calls.find(call=>call[0]==='zapret'),['zapret',true,'custom','new','C:/winws.exe']);
assert.equal(toggle.classList.contains('on'),true);
window.pywebview.api.toggle_zapret=async()=>{throw new Error('disconnected')};
await toggle.fire('click');await new Promise(setImmediate);
assert.equal(toggle.disabled,false);assert.equal(toggle.classList.contains('on'),true);
assert.equal(toasts.at(-1)[1],'error');
""")
