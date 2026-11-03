"""Behavioral regression coverage for waveform painting and deferred startup work."""
from tests.jsdom import run_node, source


def test_bottom_waveform_mask_recomputes_when_mobile_hides_the_like_button():
    run_node(r"""
import assert from 'node:assert/strict';import vm from 'node:vm';
const code=SOURCE,properties=new Map();let hidden=false;
const nodes={
 'player-bar':{getBoundingClientRect:()=>({left:10,right:810,width:800}),style:{setProperty:(k,v)=>properties.set(k,v)}},
 'pb-btn-like':{getBoundingClientRect:()=>hidden?{left:0,right:0,width:0}:{left:260,right:294,width:34}},
 'pb-volume-btn':{getBoundingClientRect:()=>({left:680,right:714,width:34})},
};
const info={getBoundingClientRect:()=>({left:80,right:230,width:150})};
nodes['player-bar'].querySelector=()=>info;
const context=vm.createContext({document:{getElementById:id=>nodes[id]},getComputedStyle:()=>({borderLeftWidth:'1',borderRightWidth:'1'})});
const start=code.indexOf('function syncBottomWaveformBounds()'),end=code.indexOf('\nfunction scheduleBottomWaveformBoundsSync',start);
vm.runInContext(code.slice(start,end),context);
context.syncBottomWaveformBounds();assert.equal(properties.get('--pb-waveform-left'),'249.0px');
hidden=true;context.syncBottomWaveformBounds();
assert.equal(properties.get('--pb-waveform-left'),'231.0px','hidden like button must use the metadata edge rather than retain desktop bounds');
assert.equal(properties.get('--pb-waveform-right'),'129.0px');
""".replace('SOURCE', source('player.js')))


def test_waveform_geometry_reused_for_progress_and_paint_invalidated_for_shape():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const code = SOURCE;
const root = {dataset:{progressStyle:'bars'},classList:{contains:()=>false}};
let built=0, color='#00ff88', opacity=0.82;
class Path2D {
 constructor(){built++;this.commands=[];}
 moveTo(...v){this.commands.push(['moveTo',...v]);} lineTo(...v){this.commands.push(['lineTo',...v]);}
 closePath(){this.commands.push(['closePath']);} roundRect(...v){this.commands.push(['roundRect',...v]);}
 rect(...v){this.commands.push(['rect',...v]);}
}
const fills=[],clips=[];
const ctx={clearRect(){},fill(path){fills.push(path);},save(){},restore(){},beginPath(){},rect(...v){clips.push(v);},clip(){}};
const canvas={clientWidth:300,clientHeight:20,parentElement:{},getContext:()=>ctx};
const context=vm.createContext({Path2D,document:{documentElement:root},window:{devicePixelRatio:1},
 getWaveColor:()=>color,getProgressOpacity:()=>opacity,
 sizeCanvasForDpr:(cv,ctx,w,h)=>({bw:w*context.window.devicePixelRatio,bh:h*context.window.devicePixelRatio})});
const start=code.indexOf('function buildWaveformPath('),end=code.indexOf("\ndocument.addEventListener('nedotify:slider_type_changed'",start);
vm.runInContext('let hoveredWaveformNormX=-1;'+code.slice(start,end),context);
const peaks=[0.2,0.8,0.4,1];
context.drawWaveformToCanvas(canvas,peaks,0.251);
assert.equal(built,1);assert.equal(fills.length,2);assert.equal(fills[0],fills[1]);
assert.equal(fills[0].commands.length,60);assert.equal(fills[0].commands[0][0],'roundRect');
assert.equal(clips[0][2],300*0.251,'progress clip retains its sub-bar pixel edge');
context.drawWaveformToCanvas(canvas,peaks,0.252);
assert.equal(built,1,'Playback position must reuse geometry');
color='#cc00ff';opacity=.5;context.drawWaveformToCanvas(canvas,peaks,0.252);
assert.equal(built,1,'Colour and alpha must reuse geometry');
vm.runInContext('hoveredWaveformNormX=.5',context);
context.drawWaveformToCanvas(canvas,peaks,.252);assert.equal(built,2);
context.drawWaveformToCanvas(canvas,[...peaks],.252);assert.equal(built,3);
canvas._wfW=400;context.drawWaveformToCanvas(canvas,peaks,.252);assert.equal(built,4);
root.dataset.progressStyle='wave';context.drawWaveformToCanvas(canvas,peaks,.252);assert.equal(built,5);
const path=canvas._wfGeometry.path;
assert.equal(path.commands[0][0],'moveTo');assert.equal(path.commands.at(-1)[0],'closePath');
context.window.devicePixelRatio=2;canvas._wfProgressPixel=undefined;
context.drawWaveformToCanvas(canvas,peaks,.253);
assert.equal(built,5,'DPR changes raster scale, not CSS-coordinate geometry');
assert.equal(canvas._wfBw,800);
""".replace('SOURCE', source('player.js')))


def test_hidden_ancestors_skip_waveform_and_restore_paused_canvas():
    run_node(r"""
import assert from 'node:assert/strict';import vm from 'node:vm';
const code=SOURCE, canvases=new Map(),drawn=[];let hidden=false;
for(const id of ['pb','pp','mp'])canvases.set(id+'-waveform-canvas',{
 id,visible:id==='pb',classList:{contains:()=>false},checkVisibility(options){assert.notEqual(options.checkOpacity,true,'Entrance opacity must not suppress a paused waveform');return this.visible;},_wfW:300,_wfH:20,_wfProgressPixel:30});
const context=vm.createContext({document:{getElementById:id=>canvases.get(id)},
 isPlayerUiHidden:()=>hidden,drawWaveformToCanvas:(canvas,peaks,progress)=>drawn.push([canvas,progress])});
const start=code.indexOf('export function renderWaveforms('),end=code.indexOf('\n}\n',start)+3;
vm.runInContext('const isWaveformScrubberActive=true,currentWaveformData=[.2,.8];'+code.slice(start,end).replace('export ',''),context);
context.renderWaveforms(.25);assert.deepEqual(drawn.map(([cv])=>cv.id),['pb']);
const pp=canvases.get('pp-waveform-canvas');pp.visible=true;
context.renderWaveforms(.25);assert.equal(drawn.at(-1)[0],pp);
assert.equal(pp._wfProgressPixel,undefined,'Paused newly-visible canvas cannot retain a stale progress skip');
hidden=true;const count=drawn.length;context.renderWaveforms(.5);assert.equal(drawn.length,count);
""".replace('SOURCE', source('player.js')))


def test_late_imports_fetch_in_parallel_and_initialize_before_bridge_replay():
    run_node(r"""
import assert from 'node:assert/strict';import vm from 'node:vm';
const code=SOURCE,requested=[],pending=new Map(),calls=[];
assert.ok(code.indexOf('const lateModules') > code.indexOf("await safeInit('Icons'"),
 'Parallel fetches must not starve the icon idle callback that gates initialization');
const context=vm.createContext({loadModule(path){requested.push(path);return new Promise(resolve=>pending.set(path,resolve));},
 safeInit:async(name,fn)=>{await fn();},flushPythonEvents:()=>calls.push('replay'),
 window:{awaitBridge:async()=>{},pywebview:{api:{ui_ready:()=>calls.push('ui_ready')}}}});
const start=code.indexOf('        const lateModules ='),end=code.indexOf('        // Initialize all modules safely',start);
const initStart=code.indexOf("        await safeInit('Lyrics'"),initEnd=code.indexOf("        await safeInit('BatchActionBar'",initStart);
const init=vm.runInContext('(async()=>{'+code.slice(start,end).replace('import(`./${name}.js`)','loadModule(`./${name}.js`)')+code.slice(initStart,initEnd)+'})()',context);
assert.deepEqual(requested,['./lyrics.js','./equalizer.js','./queue.js']);
pending.get('./queue.js')({initQueue:()=>calls.push('queue')});
pending.get('./equalizer.js')({initEqualizer:()=>calls.push('equalizer')});
await new Promise(setImmediate);assert.deepEqual(calls,[],'Fetched modules must wait for listener order');
pending.get('./lyrics.js')({initLyrics:()=>calls.push('lyrics')});await init;
assert.deepEqual(calls,['lyrics','equalizer','queue','replay','ui_ready']);
""".replace('SOURCE', source('main.js')))


def test_settings_panel_prewarms_once_and_replays_first_changed_value():
    run_node(r"""
import assert from 'node:assert/strict';import vm from 'node:vm';
const code=SOURCE,listeners=new Map();let resolvePanel,loads=0,inits=0,replayed=0,restored=0;
const target={value:'42',checked:false,isConnected:true,dispatchEvent(event){replayed++;assert.equal(event.type,'input');assert.equal(this.value,'42');}};
class InputEvent {constructor(type,init={}){this.type=type;this.target=init.target;}stopImmediatePropagation(){this.stopped=true;}preventDefault(){}}
const context=vm.createContext({console,InputEvent,syncAuraOrbsState(){},applySettingsFromBackend(){restored++;target.value='backend';},
 loadPanel(){loads++;return new Promise(resolve=>{resolvePanel=resolve;});},
 document:{querySelectorAll:()=>[],getElementById:()=>({addEventListener(type,fn){listeners.set(type,fn);}})},
 window:{addEventListener(type,fn){listeners.set(type,fn);}},localStorage:{length:0}});
const start=code.indexOf('let settingsPanelPromise'),end=code.indexOf('// Shared runtime helpers',start);
vm.runInContext(code.slice(start,end).replace(/\bexport\s+/g,'').replace("import('./settings-panel.js')",'loadPanel()'),context);
context.initSettings();context.initSettings();
assert.equal(loads,0,'Panel work must wait for readiness or user intent');
listeners.get('keydown')({key:'Tab',preventDefault(){throw Error('native Tab must remain intact');},stopImmediatePropagation(){throw Error('native input must propagate');}});
const event=new InputEvent('input',{target});listeners.get('input')(event);assert.equal(event.stopped,true);
const first=context.ensureSettingsPanel(),second=context.ensureSettingsPanel();assert.equal(first,second);assert.equal(loads,1);
resolvePanel({initSettings(){inits++;target.value='0';}});await first;await new Promise(setImmediate);
assert.equal(inits,1);assert.equal(restored,1);assert.equal(replayed,1);assert.equal(target.value,'42');
await context.ensureSettingsPanel();assert.equal(inits,1);
""".replace('SOURCE', source('settings.js')))


def test_settings_pagehide_cancels_idle_and_pending_initialization():
    run_node(r"""
import assert from 'node:assert/strict';import vm from 'node:vm';
const code=SOURCE,listeners=new Map();let resolvePanel,initialized=0,cancelled=null;
const context=vm.createContext({console,syncAuraOrbsState(){},
 loadPanel:()=>new Promise(resolve=>{resolvePanel=resolve;}),
 document:{querySelectorAll:()=>[],getElementById:()=>null},localStorage:{length:0},
 window:{addEventListener:(type,fn)=>listeners.set(type,fn),
 requestIdleCallback:()=>71,cancelIdleCallback:id=>{cancelled=id;}}});
const start=code.indexOf('let settingsPanelPromise'),end=code.indexOf('// Shared runtime helpers',start);
vm.runInContext(code.slice(start,end).replace(/\bexport\s+/g,'').replace("import('./settings-panel.js')",'loadPanel()'),context);
context.initSettings();listeners.get('nedotify:app_ready')();
const pending=context.ensureSettingsPanel();listeners.get('pagehide')();
resolvePanel({initSettings(){initialized++;}});assert.equal(await pending,null);
assert.equal(cancelled,71);assert.equal(initialized,0);assert.equal(await context.ensureSettingsPanel(),null);
""".replace('SOURCE', source('settings.js')))
