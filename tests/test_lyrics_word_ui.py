"""Real normalized word timings, shared DOM renderer and playback-clock lifecycle."""
from tests.jsdom import run_node, source


def test_word_progress_validation_and_seek_reset():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const ctx = vm.createContext({});
vm.runInContext(ENGINE.replaceAll('export ', ''), ctx);
const word = {text: 'Привет ', startMs: 1000, endMs: 1400};
assert.equal(ctx.wordProgress(word, 900), 0);
assert.equal(ctx.wordProgress(word, 1100), .25);
assert.equal(ctx.wordProgress(word, 1500), 1);
assert.equal(ctx.wordProgress({text: '!', startMs: 10, endMs: 10}, 10), 1);
assert.equal(ctx.normalizedTimedLines({syncType: 'word', lines: [{startMs: 1000, endMs: 1600, words: [word]}]}).length, 1);
for (const bad of [NaN, Infinity, -1]) {
  assert.equal(ctx.normalizedTimedLines({syncType: 'word', lines: [{startMs: 0, endMs: 1600, words: [{...word, startMs: bad}]}]}).length, 0);
}
const painter = vm.runInContext('new WordPainter([{startMs:1000,endMs:1400,words:[{text:"One",startMs:1000,endMs:1400}]}, {startMs:2000,endMs:2400,words:[{text:"Two",startMs:2000,endMs:2400}]}])', ctx);
function span() {return {dataset: {}, style: {setProperty(k,v) {this[k] = v}}};}
const first=span(), second=span(), rows=[[[first],[second]]];
painter.paint(rows, 1200, 'standard', true);
assert.equal(first.style['--lyric-word-fill'], '50.00%');
painter.paint(rows, 2200);
assert.equal(first.style['--lyric-word-fill'], '100.00%');
assert.equal(second.style['--lyric-word-fill'], '50.00%');
painter.paint(rows, 1200);
assert.equal(second.style['--lyric-word-fill'], '0.00%');
assert.equal(first.style['--lyric-word-fill'], '50.00%');
""".replace('ENGINE', source('lyrics-word-engine.js')))


def test_pointer_capture_waits_for_real_drag_and_preserves_word_clicks():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const events = new Map(), captured = [];
const viewport = {addEventListener: (name,fn) => events.set(name,fn),
  setPointerCapture: id => captured.push(id), releasePointerCapture() {},
  classList: {add() {},remove() {}}};
const state = {viewport, manual:0, base:0, minY:-100};
const context = vm.createContext({Math, ensureMeasured: () => true,
  markManualInput() {}, writeManual() {}, clampManual: (_,n) => n,
  manualRange: () => ({lo:0,hi:100})});
const code=SOURCE;
vm.runInContext(code.slice(code.indexOf('function bindKineticInput('),code.indexOf('function markManualInput(')),context);
context.bindKineticInput(state);
events.get('pointerdown')({button:0,pointerId:1,clientY:20});
events.get('pointermove')({pointerId:1,clientY:22});
assert.equal(captured.length,0,'a click must keep the original word as its target');
events.get('pointerup')({pointerId:1});
events.get('click')({stopPropagation(){throw Error('ordinary word click was suppressed')}, preventDefault(){}});
events.get('pointerdown')({button:0,pointerId:2,clientY:20});
events.get('pointermove')({pointerId:2,clientY:35});
assert.deepEqual(captured,[2]);
let suppressed=false;
events.get('pointerup')({pointerId:2});
events.get('click')({stopPropagation(){suppressed=true},preventDefault(){}});
assert.equal(suppressed,true,'a scrub must never seek');
""".replace('SOURCE', source('lyrics.js')))


HARNESS = r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const handlers = new Map(), frames = new Map(), events = [], seeks = [];
let frameId = 0;
function el() {return {children: [], dataset: {}, innerHTML: '', textContent: '',
  style: {setProperty(k,v) {this[k]=v}}, classList: {add(){},remove(){},toggle(){}},
  appendChild(child) {this.children.push(child)}, addEventListener(name,fn) {this[name]=fn},
  querySelector() {return null}, getClientRects() {return [1]}};}
const container = el();
const clock = {positionMs: 1250, paused: true, buffering: false, seeking: false, trackKey: 'track'};
const settings = {lyrics: {mode: 'auto', animations: 'standard'}};
class CustomEvent {constructor(type,options) {this.type=type;this.detail=options?.detail;}}
const ctx = vm.createContext({container, console, Math, Date, Map, Set, CustomEvent,
  requestAnimationFrame: fn => {frames.set(++frameId,fn);return frameId},
  cancelAnimationFrame: id => frames.delete(id),
  getLyricsPlaybackClock: () => clock,
  getCurrentTrack: () => ({title:'Song',artist:'Artist'}), seekTo: p => seeks.push(p),
  renderIcons() {},
  window: {settings, NeDotify: {}, dispatchEvent: e => events.push(e), addEventListener: (name,fn) => handlers.set(name,fn)},
  document: {hidden:false, createElement:el, getElementById:()=>null, addEventListener:(name,fn)=>handlers.set(name,fn)},
});
vm.runInContext(ENGINE.replaceAll('export ', ''),ctx);
vm.runInContext(LYRICS.replace(/^import .*$/gm,'').replaceAll('export ', ''),ctx);
vm.runInContext(`getContainers = () => [container]; resetLyricsScroll = () => {currentLineIndex=-1};
  ensureKineticState = () => ({dirty:false,measured:true}); ensureMeasured = () => false;
  updateLineClasses = () => {}; focusActiveLine = () => {}; updateOffsetBadges = () => {};
  setOffsetControlsEnabled = () => {}; lastLoadedTrackKey='track';`, ctx);
"""


def ui_script(body):
    run_node((HARNESS + body).replace('ENGINE', source('lyrics-word-engine.js')).replace('LYRICS', source('lyrics.js')))


def test_shared_renderer_real_words_pause_seek_resume_and_track_switch():
    ui_script(r"""
const rich = {status:'found',plainLyrics:'Привет мир',syncedLyrics:'[00:01] Привет мир',syncType:'word',
  lines:[{startMs:1000,endMs:2000,words:[{text:'Привет ',startMs:1000,endMs:1500},{text:'мир',startMs:1500,endMs:2000}]}]};
ctx.renderLyrics(rich);
assert.equal(vm.runInContext('wordRows[0][0][0].textContent',ctx), 'Привет ');
assert.equal(vm.runInContext('wordRows[0][0][0].style["--lyric-word-fill"]',ctx), '50.00%');
assert.equal(frames.size,0,'paused audio must not leave an animation loop');
clock.paused=false;
vm.runInContext('syncWordLyrics()',ctx);
assert.equal(frames.size,1);
clock.positionMs=1600;
const fn=frames.values().next().value;frames.clear();fn();
assert.equal(vm.runInContext('wordRows[0][0][0].style["--lyric-word-fill"]',ctx),'100.00%');
assert.equal(vm.runInContext('wordRows[0][0][1].style["--lyric-word-fill"]',ctx),'20.00%');
clock.paused=true;
const pauseFrame=frames.values().next().value;frames.clear();pauseFrame();
assert.equal(frames.size,0);
clock.paused=false;clock.buffering=true;
vm.runInContext('syncWordLyrics()',ctx);
assert.equal(frames.size,0,'buffering must not start a synthetic playback clock');
clock.buffering=false;clock.paused=true;
clock.positionMs=1100;
vm.runInContext('syncWordLyrics()',ctx);
assert.equal(vm.runInContext('wordRows[0][0][0].style["--lyric-word-fill"]',ctx),'20.00%');
assert.equal(vm.runInContext('wordRows[0][0][1].style["--lyric-word-fill"]',ctx),'0.00%');
vm.runInContext('currentOffsetMs=100; wordRows[0][0][1].click({stopPropagation(){}})',ctx);
assert.equal(seeks.at(-1),1400,'word click must seek using source timestamp and user offset');
clock.trackKey='new-track';clock.paused=false;clock.positionMs=1900;
vm.runInContext('syncWordLyrics()',ctx);
assert.equal(frames.size,0,'outgoing crossfade clock cannot animate stale track lyrics');
""")


def test_rich_upgrade_settings_and_two_appearances_share_the_same_renderer():
    ui_script(r"""
ctx.renderLyrics({status:'found',plainLyrics:'Hello',syncedLyrics:'[00:01] Hello'});
assert.equal(vm.runInContext('wordPainter',ctx),null);
const rich={status:'found',plainLyrics:'Hello',syncedLyrics:'[00:01] Hello',syncType:'syllable',
  lines:[{startMs:1000,endMs:1500,words:[{text:'Hel',startMs:1000,endMs:1200},{text:'lo',startMs:1200,endMs:1500}]}]};
ctx.renderLyrics(rich);
assert.equal(vm.runInContext('wordRows[0][0].length',ctx),2,'same LRC must upgrade to real syllable spans');
for(const appearance of ['default','macos']) {
  container.dataset.uiStyle=appearance;
  settings.lyrics.mode='line';ctx.renderLyrics(rich,true);
  assert.equal(vm.runInContext('wordPainter',ctx),null);
  settings.lyrics.mode='word';settings.lyrics.animations='off';ctx.renderLyrics(rich,true);
  assert.equal(vm.runInContext('wordRows[0][0].length',ctx),2);
  assert.equal(container.dataset.lyricsAnimations,'off');
}
ctx.renderLyrics({status:'unavailable'});
assert.equal(vm.runInContext('wordPainter',ctx),null);
assert.equal(frames.size,0);
""")
