"""Actual player waveform selection: real peaks or honest progress fallback."""
from tests.jsdom import run_node, source


def waveform_case(body):
    run_node(r"""
import assert from 'node:assert/strict';import vm from 'node:vm';
const code=SOURCE, classes=new Set(),rendered=[];let backend=[],decoded=null,optionsSeen=null;
function classList(){const values=new Set();return {contains:k=>values.has(k),add:k=>values.add(k),remove:k=>values.delete(k),toggle(k,v){v?values.add(k):values.delete(k);}};}
const root={dataset:{progressStyle:'bars'},classList:{add:k=>classes.add(k),remove:k=>classes.delete(k),contains:k=>classes.has(k),toggle(k,v){v?classes.add(k):classes.delete(k);}}};
const canvases=['pb','pp','mp'].map(prefix=>({id:prefix+'-waveform-canvas',classList:classList(),width:300,height:20,getContext:()=>({clearRect(){}})}));
const track={source:'youtube',source_id:'fixture',title:'Fixture'},state={track,durationMs:100000,positionMs:25000};
const audio={currentSrc:'http://127.0.0.1/playing-audio'};
const context=vm.createContext({AbortController,console,Number,Array,window:{pywebview:{api:{get_waveform:async()=>{if(backend instanceof Error)throw backend;return backend;}}}},document:{documentElement:root,getElementById:id=>canvases.find(c=>c.id===id)},playbackState:state,activeAudio:audio,
 fetchRealPeaks:async(t,options)=>{optionsSeen=options;return typeof decoded==='function'?decoded(t,options):decoded;},
 renderWaveforms:()=>rendered.push(vm.runInContext('currentWaveformData',context))});
const start=code.indexOf('export async function fetchAndRenderWaveform('),end=code.indexOf('export function renderWaveforms(',start);
vm.runInContext('let waveformRequestId=0,waveformAbortController=null,currentWaveformData=null,isWaveformScrubberActive=false;'+code.slice(start,end).replace(/\bexport\s+/g,''),context);
""".replace('SOURCE',source('player.js'))+body)


def test_unavailable_audio_keeps_plain_progress_instead_of_fabricated_peaks():
    waveform_case(r"""
await context.fetchAndRenderWaveform(track);
assert.equal(vm.runInContext('currentWaveformData',context),null,'Missing real audio must not produce title-seeded bars');
assert.ok(classes.has('waveform-unavailable'));
assert.ok(canvases.every(c=>c.classList.contains('hidden')));
assert.equal(rendered.length,0);
""")


def test_soundcloud_failure_still_allows_real_stream_peaks():
    waveform_case(r"""
backend=new Error('waveform endpoint unavailable');decoded=[0,.3,1,0];
await context.fetchAndRenderWaveform(track);
assert.deepEqual(Array.from(vm.runInContext('currentWaveformData',context)),decoded);
assert.equal(classes.has('waveform-unavailable'),false);
assert.ok(canvases.every(c=>!c.classList.contains('hidden')));
""")


def test_decode_uses_the_resolved_active_stream_and_cancellable_request():
    waveform_case(r"""
decoded=[0,1,0];await context.fetchAndRenderWaveform(track);
assert.equal(optionsSeen?.url,audio.currentSrc);
assert.ok(optionsSeen?.signal instanceof AbortSignal);
""".replace('instanceof AbortSignal',"&& typeof optionsSeen.signal.aborted==='boolean'"))


def test_replaced_track_aborts_old_analysis_and_cannot_overwrite_new_peaks():
    waveform_case(r"""
let completeOld,oldSignal;decoded=(t,options)=>new Promise(resolve=>{completeOld=resolve;oldSignal=options?.signal;});
const first=context.fetchAndRenderWaveform(track);await new Promise(setImmediate);
const next={source:'local',id:2,stream_url:'http://127.0.0.1/next-audio'};state.track=next;decoded=[0,1,0];
await context.fetchAndRenderWaveform(next);assert.equal(oldSignal?.aborted,true);
completeOld([1,1,1]);await first;
assert.deepEqual(Array.from(vm.runInContext('currentWaveformData',context)),[0,1,0]);
""")


def test_new_loaded_source_wins_over_previous_current_src_while_media_loads():
    waveform_case(r"""
audio.currentSrc='http://127.0.0.1/previous-track';audio._loadedSourceUrl='http://127.0.0.1/new-track';
decoded=[0,1,0];await context.fetchAndRenderWaveform(track);
assert.equal(optionsSeen.url,audio._loadedSourceUrl);
""")


def test_real_silence_does_not_become_louder_than_quiet_audio_when_drawing():
    run_node(r"""
import assert from 'node:assert/strict';import vm from 'node:vm';
class Path2D {constructor(){this.commands=[];}roundRect(...v){this.commands.push(v);}rect(...v){this.commands.push(v);}moveTo(...v){this.commands.push(v);}lineTo(...v){this.commands.push(v);}closePath(){}}
const code=SOURCE,context=vm.createContext({Path2D});
vm.runInContext(code.slice(code.indexOf('function buildWaveformPath('),code.indexOf('function drawWaveformToCanvas(')),context);
const silent=context.buildWaveformPath(300,86,[0,0,0],'bars',-1);
assert.ok(silent.commands.every(v=>v[3]===3),'True silence should be only the three-pixel baseline');
const quiet=context.buildWaveformPath(300,86,[.1,.1,.1],'bars',-1);
assert.ok(quiet.commands.every(v=>Math.abs(v[3]-8.2)<.001),'Quiet audio retains actual amplitude');
const wave=context.buildWaveformPath(300,86,[0,0,0],'wave',-1);
assert.ok(wave.commands.every(v=>v[1]===42||v[1]===44),'Silent wave envelope retains only the minimum contour');
""".replace('SOURCE',source('player.js')))
