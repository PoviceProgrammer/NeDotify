"""Exercise the shipped drag bindings and seek path without a user profile."""
from tests.jsdom import run_node, source


def test_all_player_seek_surfaces_preview_and_commit_the_pointer_position():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const code=SOURCE;
for(const style of ['current','macos']) {
 const nodes=new Map(), documentEvents=new Map(), frames=[], reports=[];
 for(const prefix of ['pb','pp','mp']) {
  const listeners=new Map(),attributes=new Map();
  nodes.set(prefix+'-progress-track', {
   listeners,style:{setProperty(){}},addEventListener:(name,fn)=>listeners.set(name,fn),
   removeEventListener:(name,fn)=>{if(listeners.get(name)===fn)listeners.delete(name);},
   removeAttribute:name=>attributes.delete(name),
   getAttribute:name=>attributes.get(name),setAttribute:(name,v)=>attributes.set(name,v),
   getBoundingClientRect:()=>({left:100,width:400}),focus(){},
   setPointerCapture(){},hasPointerCapture:()=>true,releasePointerCapture(){},
  });
  nodes.set(prefix+'-progress-fill',{style:{}});
  nodes.set(prefix+'-time-current',{textContent:''});
  nodes.set(prefix+'-time-total',{textContent:''});
 }
 const state={durationMs:120000,positionMs:0};
 const audio={currentTime:0};
 const context=vm.createContext({
  playbackState:state,activeAudio:audio,finishFade(){},performance:{now:()=>100},
  setTimeout:()=>1,clearTimeout(){},console,window:{},
  document:{documentElement:{dataset:{uiStyle:style}},getElementById:id=>nodes.get(id),
   addEventListener:(name,fn)=>documentEvents.set(name,fn),
   removeEventListener:(name,fn)=>{if(documentEvents.get(name)===fn)documentEvents.delete(name);}},
  formatTime:seconds=>String(seconds),renderWaveforms:pct=>frames.push(pct),
  setEl:(id,prop,v)=>{nodes.get(id).style[prop]=v;},
  setElText:(id,v)=>{nodes.get(id).textContent=v;},
  api:(...args)=>reports.push(args),
 });
 const helper=code.slice(code.indexOf('function paintPlaybackProgress('),code.indexOf('\nfunction api(method,'));
 const seek=code.slice(code.indexOf('export function seekTo('),code.indexOf('\nexport function getCurrentTrack'));
 const bindings=code.slice(code.indexOf("    setupDragBar('mp-progress-track'"),code.indexOf('    // Volume bar drag'));
 vm.runInContext('let isDraggingProgress=false, cancelProgressDrag=null, automaticTransition=null, lastSeekTime=0, isSeeking=false, seekTimeoutId=null;'+helper+seek.replace('export ','')+bindings,context);
 for(const prefix of ['pb','pp','mp']) {
  const track=nodes.get(prefix+'-progress-track');
  const event=(clientX,pointerId=3)=>({clientX,pointerId,button:0,pointerType:'mouse',
   target:{closest:()=>null},preventDefault(){}});
  track.listeners.get('pointerdown')(event(200));
  assert.equal(frames.at(-1),.25,style+': '+prefix+' click must preview its own position');
  documentEvents.get('pointermove')(event(300));
  assert.equal(frames.at(-1),.5);
  for (const other of ['pb','pp','mp']) {
   assert.equal(nodes.get(other+'-progress-track').getAttribute('aria-valuenow'),'50.0');
   assert.equal(nodes.get(other+'-time-current').textContent,'60');
  }
  documentEvents.get('pointerup')(event(400));
  assert.equal(state.positionMs,90000,style+': '+prefix+' release must seek to its final coordinate');
  assert.equal(audio.currentTime,90);
  assert.equal(frames.at(-1),.75,'Seek must repaint the waveform immediately');
  assert.equal(nodes.get('pp-time-current').textContent,'90');
  assert.equal(nodes.get('pb-progress-track').getAttribute('aria-valuenow'),'75.0');
  assert.equal(documentEvents.size,0,'Each drag must remove document handlers');
  assert.equal(vm.runInContext('isDraggingProgress',context),false);
  assert.equal(reports.at(-1)[0],'report_position');
  const count=reports.length;
  track.listeners.get('pointerdown')(event(200));
  documentEvents.get('pointercancel')(event(300));
  assert.equal(reports.length,count,'Cancelling must not seek');
  assert.equal(state.positionMs,90000);
  assert.equal(frames.at(-1),.75,'Cancel restores actual media time');
  assert.equal(documentEvents.size,0);
  track.listeners.get('pointerdown')(event(200));
  state.track={id:'next'};
  documentEvents.get('pointermove')(event(300));
  assert.equal(documentEvents.size,0,'Track replacement cancels the captured gesture');
  assert.equal(reports.length,count,'The old gesture cannot seek the next track');
  assert.equal(vm.runInContext('isDraggingProgress',context),false);
  for (const duration of [0,Infinity,NaN]) {
   state.durationMs=duration;
   track.listeners.get('pointerdown')(event(200));
   assert.equal(documentEvents.size,0,'Unknown duration must not start a seek');
  }
  state.durationMs=120000;
 }
}
""".replace('SOURCE', source('player.js')))


def test_position_events_keep_milliseconds_and_disable_unknown_duration():
    from tests.helpers import player_test
    player_test(r"""
vm.runInContext(`
playbackState.status='paused'; activeAudio.duration=NaN;
onPositionChanged(1500,9000);
`,context);
assert.equal(elements.get('pb-time-current').textContent,'0:01');
assert.equal(elements.get('pp-progress-track').getAttribute('aria-valuenow'),'16.7');
assert.equal(vm.runInContext('playbackState.positionMs',context),1500);
vm.runInContext('onPositionChanged(0,0)',context);
for (const prefix of ['pb','pp','mp']) {
 assert.equal(elements.get(prefix+'-progress-track').getAttribute('aria-disabled'),'true');
 assert.equal(elements.get(prefix+'-progress-track').getAttribute('aria-valuenow'),'0.0');
}
vm.runInContext('onPositionChanged(9000,9000)',context);
assert.equal(elements.get('pb-progress-track').getAttribute('aria-valuenow'),'100.0');
assert.equal(elements.get('mp-time-current').textContent,'0:09');
""")


def test_same_track_metadata_preserves_progress_and_new_track_resets_every_surface():
    from tests.test_player_recovery_transitions import player_test
    player_test(r"""
player.onTrackChanged(first);
player.active.currentTime=47;
player.onTrackChanged({...first,title:'Updated metadata'});
for (const prefix of ['pb','pp','mp']) {
 assert.equal(elements.get(prefix+'-time-current').textContent,'0:47');
 assert.equal(elements.get(prefix+'-progress-track').getAttribute('aria-valuenow'),'26.1');
}
player.onTrackChanged(second);
for (const prefix of ['pb','pp','mp']) {
 assert.equal(elements.get(prefix+'-time-current').textContent,'0:00');
 assert.equal(elements.get(prefix+'-progress-track').getAttribute('aria-valuenow'),'0.0');
}
""")


def test_progress_style_offers_panel_and_line_and_migrates_old_preferences():
    run_node(r"""
import assert from 'node:assert/strict';import vm from 'node:vm';
const code=SOURCE;
const context=vm.createContext({});
vm.runInContext(code.slice(code.indexOf('function normalizeProgressStyle('),code.indexOf('function normalizeProgressColor(')),context);
for (const old of ['bars','wave','hidden','default',undefined]) assert.equal(context.normalizeProgressStyle(old),'panel');
for (const old of ['solid','thin','ios']) assert.equal(context.normalizeProgressStyle(old),'solid');
assert.equal(context.normalizeProgressStyle('panel'),'panel');
""".replace('SOURCE',source('settings.js')))
