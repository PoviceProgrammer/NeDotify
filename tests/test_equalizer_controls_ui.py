"""EQ restoration must not replace edits or lose the selected band layout."""
from tests.jsdom import run_node, source


def eq_js(body):
    run_node(r"""
import assert from 'node:assert/strict';import vm from 'node:vm';
const nodes=[],timers=new Map(),writes=[],dsp=[],storage=new Map();let restore;
function element(id='',className=''){
  const values=new Set(),listeners=new Map();
  const e={id,dataset:{},children:[],style:{setProperty(k,v){this[k]=v}},textContent:'',value:'0',
    classList:{add:k=>values.add(k),remove:k=>values.delete(k),contains:k=>values.has(k),toggle(k,on=!values.has(k)){on?values.add(k):values.delete(k);return on}},
    setAttribute(k,v){this[k]=v},addEventListener(k,fn){listeners.set(k,fn)},
    appendChild(child){this.children.push(child)},querySelectorAll(selector){return nodes.filter(n=>this.children.includes(n)&&matches(n,selector))},
    fire(type){listeners.get(type)?.({target:this,stopPropagation(){},preventDefault(){}})},
    set className(value){values.clear();value.split(' ').filter(Boolean).forEach(k=>values.add(k))},
    set innerHTML(value){const remove=child=>{child.children.forEach(remove);const index=nodes.indexOf(child);if(index>=0)nodes.splice(index,1)};this.children.forEach(remove);this.children=[]},
  };e.className=className;nodes.push(e);return e;
}
function matches(node,selector){return selector.split(',').some(s=>node.classList.contains(s.trim().slice(1)))}
for(const id of ['eq-bands-container','eq-preamp','eq-val-preamp','btn-eq-reset','eq-dropdown-btn','eq-preset-current-text'])element(id);
const group=element('eq-mode-btn-group'),menu=element('eq-dropdown-menu');
for(const mode of [3,6,10]){const button=element('','eq-mode-btn');button.dataset.mode=String(mode);group.appendChild(button)}
for(const key of ['flat','bass_boost','treble_boost','vocal','rock','pop','jazz']){const option=element('','custom-glass-dropdown-item');option.dataset.value=key;menu.appendChild(option)}
const get=id=>nodes.find(n=>n.id===id),query=selector=>nodes.filter(n=>matches(n,selector));
const events=[];
const window={dispatchEvent:event=>events.push(event.type),settings:{equalizer:{}},pywebview:{api:{
  get_equalizer:()=>new Promise(resolve=>restore=resolve),
  set_equalizer:(...args)=>{writes.push(['eq',...args]);return Promise.resolve(true)},
  save_setting:(...args)=>{writes.push(['setting',...args]);return Promise.resolve(true)},
}}};
const context=vm.createContext({window,console,CustomEvent:class {constructor(type){this.type=type;}},document:{getElementById:get,createElement:()=>element(),querySelectorAll:query,addEventListener(){}},
  localStorage:{getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value)},
  setTimeout:fn=>{timers.set(1,fn);return 1},clearTimeout:id=>timers.delete(id),setEq:(...args)=>dsp.push(args),showToast(){},
});
vm.runInContext(SOURCE.replace(/^import .*;\r?$/gm,'').replace(/\bexport\s+/g,'')+'\nglobalThis.subject={initEqualizer};',context);
const subject=context.subject;
""".replace('SOURCE', source('equalizer.js')) + body)


def test_late_equalizer_restore_cannot_overwrite_user_input_and_mode_is_saved():
    eq_js(r"""
const loading=subject.initEqualizer();
group.children.find(n=>n.dataset.mode==='6').fire('click');
assert.equal(query('.eq-band-slider').length,6);
const slider=query('.eq-band-slider')[0];slider.value='3.5';slider.fire('input');
get('eq-preamp').value='2.5';get('eq-preamp').fire('input');
restore({preamp:0,bands:Array(10).fill(0)});await loading;
assert.equal(get('eq-preamp').value,2.5);
assert.equal(get('eq-preset-current-text').textContent,'Пресет: Пользовательский');
assert.equal(window.settings.equalizer.bands[0],3.5);assert.equal(window.settings.equalizer.bands[1],3.5);
for(const callback of timers.values())callback();await new Promise(setImmediate);
assert.equal(writes.find(call=>call[0]==='eq')[3],6,'band layout and gains use one bridge action');
assert.deepEqual(writes.find(call=>call[0]==='eq')[1],2.5);
""")


def test_cached_layout_preset_and_reset_stay_in_sync():
    eq_js(r"""
storage.set('nedotify_equalizer',JSON.stringify({preamp:1,bands:[6,5,3,1,0,0,0,0,0,0],mode:10}));
const loading=subject.initEqualizer();
restore({preamp:1,bands:[6,5,3,1,0,0,0,0,0,0]});await loading;
assert.equal(query('.eq-band-slider').length,10);
assert.equal(group.children.find(n=>n.dataset.mode==='10')['aria-pressed'],'true');
assert.equal(get('eq-preset-current-text').textContent,'Пресет: Усиление баса');
assert.equal(menu.children.find(n=>n.dataset.value==='bass_boost')['aria-selected'],'true');
get('btn-eq-reset').fire('click');
assert.equal(get('eq-preamp').value,0);assert.equal(get('eq-preset-current-text').textContent,'Пресет: Сброс (Flat)');
assert.ok(window.settings.equalizer.bands.every(value=>value===0));
assert.equal(get('eq-preamp').style['--value-percent'],'50%');
""")


def test_backend_eq_restore_publishes_the_same_bands_to_the_audio_panel():
    eq_js(r"""
const loading=subject.initEqualizer();
restore({preamp:2,bands:[6,5,4,3,2,1,0,-1,-2,-3],mode:10});await loading;
assert.deepEqual(Array.from(window.settings.equalizer.bands),[6,5,4,3,2,1,0,-1,-2,-3]);
assert.equal(window.settings.equalizer.preamp,2);
assert.equal(events.at(-1),'nedotify:equalizer_changed');
assert.equal(writes.length,0,'restoring must not save a different preference');
""")


def test_rejected_equalizer_save_restores_gains_thumb_labels_and_dsp():
    eq_js(r"""
const loading=subject.initEqualizer();
restore({preamp:2,bands:Array(10).fill(1),mode:10});await loading;
window.pywebview.api.set_equalizer=()=>Promise.resolve(false);
get('eq-preamp').value='7';get('eq-preamp').fire('input');
for(const callback of timers.values())callback();await new Promise(setImmediate);
assert.equal(get('eq-preamp').value,2);
assert.equal(get('eq-val-preamp').textContent,'+2.0 dB');
assert.equal(window.settings.equalizer.preamp,2);
assert.deepEqual(Array.from(window.settings.equalizer.bands),Array(10).fill(1));
assert.equal(dsp.at(-1)[0],2);
assert.equal(storage.has('nedotify_equalizer'),false,'rejected values never reach the next startup cache');
""")
