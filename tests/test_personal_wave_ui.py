from tests.jsdom import run_node, source


def test_wave_shelf_passes_entire_list_to_playback_and_guards_future_refresh():
    code = source('personal-wave.js').replace("import('./events.js')", "Promise.resolve({addPythonEventHandler:subscribe})")
    run_node(r'''
import assert from 'node:assert/strict';import vm from 'node:vm';
const nodes=new Map(),calls=[],timers=new Map();let listener,seq=0;
function node(){return {children:[],textContent:'',disabled:false,events:{},
 querySelector(selector){if(!nodes.has(selector))nodes.set(selector,node());return nodes.get(selector);},
 append(child){this.children.push(child)},replaceChildren(){this.children=[]},
 addEventListener(name,fn){this.events[name]=fn},before(){}};}
const anchor=node();
const context=vm.createContext({console,Date,Math,Set,Promise,
 document:{getElementById:()=>anchor,createElement:()=>node()},
 window:{addEventListener(){},pywebview:{api:{
 get_personal_wave:async(...args)=>calls.push(['request',...args]),
 replace_personal_wave_tail:async(...args)=>{calls.push(['replace',...args]);return {success:true};}}}},
 subscribe:fn=>{listener=fn},
 createTrackElement:(track,index,tracks)=>({track,index,tracks}),
 setTimeout:(fn,ms)=>{timers.set(++seq,{fn,ms});return seq},clearTimeout:id=>timers.delete(id)});
vm.runInContext(SOURCE.replace(/^import .*;\r?$/gm,'').replace(/\bexport\s+/g,'')+'\nglobalThis.mount=mountPersonalWave;',context);
await context.mount();
const rows=Array.from({length:80},(_,i)=>({title:'Song '+i,artist:'Artist '+i,source:'youtube',source_id:String(i)}));
await listener('personal_wave_ready',{request_id:calls[0][1],tracks:rows});
const list=nodes.get('.personal-wave-tracks');assert.equal(list.children.length,80);
const chosen=list.children[17];assert.equal(chosen.index,17);assert.equal(chosen.tracks.length,80);
assert.equal(chosen.track._personal_wave_session,chosen.tracks[0]._personal_wave_session);
const snapshot={tracks:chosen.tracks,current_index:17,current_track:{...chosen.track,entry_id:'playing'},queue_revision:7};
await listener('queue_updated',snapshot);
const scheduled=[...timers.values()].find(t=>t.ms===500);scheduled.fn();await Promise.resolve();
const pending=calls.filter(c=>c[0]==='request').at(-1);
assert.equal(pending[2].length,18,'exclude played prefix, allow future reranking');
await listener('personal_wave_ready',{request_id:pending[1],tracks:rows.map(t=>({...t,title:'Fresh '+t.title}))});
const update=calls.find(c=>c[0]==='replace');assert.equal(update[1].length,80);
assert.equal(update[3],'playing');assert.equal(update[4],7);
await listener('personal_wave_ready',{request_id:'stale',tracks:[]});
assert.equal(list.children.length,80);
'''.replace('SOURCE',code))
