"""Exercise asynchronous mini-player confirmation without starting WebView."""
from tests.jsdom import run_node, source


def test_mini_player_waits_for_matching_native_event_and_rolls_back_failure():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const listeners = new Map(), timers = new Map(), calls = [], toasts = [];
let timerSeq = 0;
const classes = new Set();
const body = {classList:{contains:k=>classes.has(k),toggle(k,on=!classes.has(k)){on?classes.add(k):classes.delete(k)}}};
const window = {
  addEventListener:(name,fn)=>listeners.set(name,fn),
  dispatchEvent:event=>toasts.push(event.detail),
  pywebview:{api:{toggle_mini_player:async (...args)=>{calls.push(args);return {pending:true}}}},
};
const document = {body};
const context = vm.createContext({window,document,Date,Boolean,CustomEvent:class {constructor(type,options){this.type=type;this.detail=options.detail}},
  setTimeout:(fn,ms)=>{const id=++timerSeq;timers.set(id,{fn,ms});return id},clearTimeout:id=>timers.delete(id)});
const full = SOURCE;
const code = full.match(/let miniPlayerRequestCounter = 0;[\s\S]*?window\.toggleMiniPlayerMode = toggleMiniPlayerMode;/)[0];
vm.runInContext(code.replace(/export async function/, 'async function')+'\nglobalThis.toggle=toggleMiniPlayerMode;',context);
const resultPromise=context.toggle(true);
await Promise.resolve();
const requestId=calls[0][1];
assert.equal(typeof requestId,'string');
assert.equal(body.classList.contains('mini-player-active'),false,'pending native operation must not commit CSS early');
listeners.get('nedotify:mini_player_toggled')({detail:{request_id:'stale',success:true,is_mini:true}});
assert.equal(body.classList.contains('mini-player-active'),false,'stale completion must be ignored');
listeners.get('nedotify:mini_player_toggled')({detail:{request_id:requestId,success:false,is_mini:false}});
assert.equal(await resultPromise,false,'failed native operation returns the previous state');
assert.equal(body.classList.contains('mini-player-active'),false);
assert.equal(timers.size,0);
""".replace("SOURCE", source("main.js")))


def test_mini_player_pending_success_commits_only_after_completion_event():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const listeners=new Map(),timers=new Map(),calls=[];let n=0;
const classes=new Set();const body={classList:{contains:k=>classes.has(k),toggle(k,on=!classes.has(k)){on?classes.add(k):classes.delete(k)}}};
const window={addEventListener:(name,fn)=>listeners.set(name,fn),dispatchEvent(){},pywebview:{api:{toggle_mini_player:async(...args)=>{calls.push(args);return {pending:true}}}}};
const context=vm.createContext({window,document:{body},Date,Boolean,CustomEvent:class {constructor(type,options){this.detail=options.detail}},setTimeout:(fn,ms)=>{const id=++n;timers.set(id,{fn,ms});return id},clearTimeout:id=>timers.delete(id)});
const code=SOURCE.match(/let miniPlayerRequestCounter = 0;[\s\S]*?window\.toggleMiniPlayerMode = toggleMiniPlayerMode;/)[0];
vm.runInContext(code.replace(/export async function/,'async function')+'\nglobalThis.toggle=toggleMiniPlayerMode;',context);
const pending=context.toggle(true);await Promise.resolve();
listeners.get('nedotify:mini_player_toggled')({detail:{request_id:calls[0][1],success:true,is_mini:true}});
assert.equal(await pending,true);assert.equal(body.classList.contains('mini-player-active'),true);assert.equal(timers.size,0);
""".replace("SOURCE", source("main.js")))


def test_superseded_mini_player_request_cannot_roll_back_the_latest_state():
    run_node(r"""
import assert from 'node:assert/strict';import vm from 'node:vm';
const listeners=new Map(),timers=new Map(),calls=[];let n=0;
const classes=new Set();const body={classList:{contains:k=>classes.has(k),toggle(k,on=!classes.has(k)){on?classes.add(k):classes.delete(k)}}};
const window={addEventListener:(name,fn)=>listeners.set(name,fn),dispatchEvent(){},pywebview:{api:{toggle_mini_player:async(...args)=>{calls.push(args);return {pending:true}}}}};
const context=vm.createContext({window,document:{body},Date,Boolean,CustomEvent:class {constructor(type,options){this.detail=options.detail}},setTimeout:(fn,ms)=>{const id=++n;timers.set(id,{fn,ms});return id},clearTimeout:id=>timers.delete(id)});
const code=SOURCE.match(/let miniPlayerRequestCounter = 0;[\s\S]*?window\.toggleMiniPlayerMode = toggleMiniPlayerMode;/)[0];
vm.runInContext(code.replace(/export async function/,'async function')+'\nglobalThis.toggle=toggleMiniPlayerMode;',context);
const old=context.toggle(true);await Promise.resolve();const oldId=calls[0][1];
const latest=context.toggle(true);await Promise.resolve();const latestId=calls[1][1];
assert.equal(await old,false,'superseded caller settles using current state');
listeners.get('nedotify:mini_player_toggled')({detail:{request_id:latestId,success:true,is_mini:true}});
assert.equal(await latest,true);assert.equal(body.classList.contains('mini-player-active'),true);
listeners.get('nedotify:mini_player_toggled')({detail:{request_id:oldId,success:false,is_mini:false}});
assert.equal(body.classList.contains('mini-player-active'),true,'late stale completion cannot undo newer success');
assert.equal(timers.size,0);
""".replace("SOURCE", source("main.js")))
