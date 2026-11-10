"""E1 regression tests: Zapret UI / bridge / state-sync fixes.

Covers the UI batch of the 2026-10-28 audit: BUG-006 (stub status re-read),
BUG-020 (busy check correlation), BUG-021 (in-flight apply vs panel reopen),
BUG-026 (version badge from latest_version), BUG-050/053 (status.message,
enabled&&!running, autostart hint), BUG-051 (update timeout/bridge guard),
BUG-052 (mutual control locks), BUG-054 (panel before bridge ready),
BUG-055 (unknown mode option), BUG-056 (switch/aria-live semantics),
BUG-057 (dead checkbox handler), BUG-058 (comment typo) and the new backend
lifecycle events. Backend tails: BUG-020 (busy answer carries the ACTIVE
request id), BUG-033 (autostart failure feedback event), BUG-041 (_build_status
exception path keeps the full key template).
"""
import re
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tests.jsdom import run_node, source

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = (ROOT / "ui" / "web_new_v2" / "index.html").read_text(encoding="utf-8")
PANEL_SOURCE = source("settings-panel.js")


def zapret_panel_js(body):
    """Evaluate settings-panel.js against a DOM/bridge stub and run `body`.

    Unlike the settings harness this one also records window event listeners
    (so bridge-routed zapret events can be fired) and provides a controllable
    fake timer queue, which the bounded re-read loop and the operation safety
    timeouts run on.
    """
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const elements = new Map(), calls = [], toasts = [], windowEvents = [];
const windowListeners = new Map(), timers = [];
function element(id) {
    const classes = new Set(), listeners = new Map(), props = new Map(), attributes = new Map();
    const children = [];
    const item = {id, value:'', checked:false, disabled:false, textContent:'', children,
      style:{setProperty:(k,v)=>props.set(k,v),getPropertyValue:k=>props.get(k),removeProperty:k=>props.delete(k)},
      classList:{contains:k=>classes.has(k),add:(...ks)=>ks.forEach(k=>classes.add(k)),remove:(...ks)=>ks.forEach(k=>classes.delete(k)),toggle(k,on=!classes.has(k)){on?classes.add(k):classes.delete(k);return on}},
      addEventListener:(k,fn)=>{const arr=listeners.get(k)||[];arr.push(fn);listeners.set(k,arr);},
      removeEventListener:(k,fn)=>{listeners.set(k,(listeners.get(k)||[]).filter(f=>f!==fn));},
      fire:async (k,ev)=>{for (const fn of (listeners.get(k)||[]).slice()) await fn(ev||{target:item});},
      appendChild:(child)=>{children.push(child);return child;},
      setAttribute:(k,v)=>attributes.set(k,String(v)),
      getAttribute:(k)=>attributes.get(k)??null,
      querySelectorAll:()=>[]};
    elements.set(id,item);return item;
}
const root = element('root');
const context = vm.createContext({
    console:{log(){},warn(){},error(){},debug(){},info(){}},
    Promise,Number,Math,JSON,Date,
    setTimeout:(fn,ms)=>{timers.push({fn,ms});return timers.length;},
    clearTimeout:(id)=>{const t=timers[id-1];if(t)t.fn=null;},
    window:{settings:{},
      addEventListener:(k,fn)=>{const arr=windowListeners.get(k)||[];arr.push(fn);windowListeners.set(k,arr);},
      removeEventListener:(k,fn)=>{windowListeners.set(k,(windowListeners.get(k)||[]).filter(f=>f!==fn));},
      dispatchEvent:(e)=>{windowEvents.push(e);for(const fn of (windowListeners.get(e.type)||[]).slice())fn(e);return true;}},
    document:{documentElement:root,body:root,
      getElementById:(id)=>elements.get(id)||null,
      createElement:(tag)=>({tagName:String(tag).toUpperCase(),value:'',textContent:'',setAttribute(){},appendChild(){},remove(){}}),
      addEventListener(){},dispatchEvent(){},querySelectorAll:()=>[]},
    localStorage:{getItem:()=>null,setItem(){},removeItem(){}},
    CustomEvent:class{constructor(type,options){this.type=type;this.detail=options?.detail;}},
    showToast:(...args)=>toasts.push(args),
    saveSetting:(key,value,category)=>{calls.push([key,value,category]);return true;},
});
vm.runInContext(PANEL.replace(/^import .*;\r?$/gm,'').replace(/\bexport\s+/g,'') + '\nglobalThis.subject={setupZapretPanel};', context);
const {subject, window, CustomEvent} = context;
const tick = () => new Promise(r => setImmediate(r));
const fireWindow = async (type, detail) => { window.dispatchEvent(new CustomEvent(type, {detail})); await tick(); };
const flushTimers = async () => {
    for (let i = 0; i < 30; i++) {
        const due = timers.filter(t => t.fn);
        if (!due.length) break;
        const fn = due[0].fn;
        due[0].fn = null;
        fn();
        await tick();
    }
};
function stubStatus(overrides = {}) {
    return Object.assign({running:false, enabled:false, auto_start:false, autoupdate:false,
        mode:'youtube_discord', custom_args:'', binary_path:'', binary_found:true,
        has_internet:true, version:'v72.13', pending_update:'', message:'Zapret отключен'}, overrides);
}
""".replace("PANEL", PANEL_SOURCE) + body)


def test_bug006_stub_status_never_flips_the_toggle_and_is_retried():
    zapret_panel_js(r"""
const toggle=element('toggle-zapret-enabled'),statusEl=element('zapret-update-status');
let real=false, reads=0;
const stub={running:false,binary_found:false,binary_path:'',has_internet:true,version:'',pending_update:'',message:'Определение статуса...'};
window.pywebview={api:{get_zapret_status:async()=>{reads++;return real?stubStatus({running:true,message:'Zapret запущен'}):stub;}}};
subject.setupZapretPanel();await tick();
assert.equal(toggle.classList.contains('on'),false,'the placeholder must not flip the toggle');
assert.match(statusEl.textContent,/Определение статуса/);
real=true;
await flushTimers();
assert.equal(toggle.classList.contains('on'),true,'the bounded re-read must land the real state');
assert.equal(toggle.getAttribute('aria-checked'),'true');
assert.match(statusEl.textContent,/Zapret запущен/);
assert.equal(timers.filter(t=>t.fn).length,0,'the retry loop stops after the first real read');
const readsAfterSuccess=reads;
await flushTimers();
assert.equal(reads,readsAfterSuccess,'no polling once the status is known');
""")


def test_bug006_stub_retries_are_bounded():
    zapret_panel_js(r"""
element('toggle-zapret-enabled');element('zapret-update-status');
let reads=0;
window.pywebview={api:{get_zapret_status:async()=>{reads++;return {running:false,message:'Определение статуса...',binary_found:false,binary_path:'',has_internet:true,version:'',pending_update:''};}}};
subject.setupZapretPanel();await tick();
await flushTimers();await flushTimers();
assert.ok(reads<=4,'initial read + at most 3 retries, got '+reads);
assert.equal(timers.filter(t=>t.fn).length,0,'no eternal timers while the backend stays a stub');
""")


def test_bug054_missing_bridge_awaits_awaitbridge():
    zapret_panel_js(r"""
const toggle=element('toggle-zapret-enabled');
let release;
window.awaitBridge=()=>new Promise(r=>{release=r;});
subject.setupZapretPanel();await tick();
assert.equal(toggle.classList.contains('on'),false,'no bridge yet - no fake state');
window.pywebview={api:{get_zapret_status:async()=>stubStatus({running:true})}};
release();await tick();await tick();
assert.equal(toggle.classList.contains('on'),true,'the status loads once the bridge is ready');
assert.equal(toggle.getAttribute('aria-checked'),'true');
""")


def test_bug054_missing_bridge_falls_back_to_bounded_polling():
    zapret_panel_js(r"""
const toggle=element('toggle-zapret-enabled');
let reads=0;
subject.setupZapretPanel();await tick();  // no bridge and no awaitBridge helper
window.pywebview={api:{get_zapret_status:async()=>{reads++;return stubStatus({running:true});}}};
await flushTimers();
assert.equal(reads,1,'the poll lands exactly once after the bridge appears');
assert.equal(toggle.classList.contains('on'),true);
assert.equal(timers.filter(t=>t.fn).length,0);
""")


def test_bug006_bridge_error_status_never_flips_the_toggle():
    # E2: the api-level catch shape ({running:false, error:...} without a
    # message) is not a state read — trusting its running=false used to flip
    # a running toggle off. It must behave like the placeholder: keep the
    # last known state, explain, and retry (bounded).
    zapret_panel_js(r"""
const toggle=element('toggle-zapret-enabled'),statusEl=element('zapret-update-status');
let fail=false, reads=0;
window.pywebview={api:{get_zapret_status:async()=>{reads++;return fail
    ? {running:false,enabled:false,auto_start:false,mode:'youtube_discord',binary_found:false,error:'boom'}
    : stubStatus({running:true,message:'Zapret запущен'});}}};
subject.setupZapretPanel();await tick();
assert.equal(toggle.classList.contains('on'),true);
fail=true;
subject.setupZapretPanel();await tick();  // panel re-entry while the bridge errors
assert.equal(toggle.classList.contains('on'),true,'an error answer must not flip the toggle off');
assert.equal(toggle.getAttribute('aria-checked'),'true');
assert.match(statusEl.textContent,/повторяем попытку/);
await flushTimers();
assert.ok(reads<=5,'initial + at most 3 retries after the error, got '+reads);
assert.equal(timers.filter(t=>t.fn).length,0,'the error retry loop is bounded too');
""")


def test_bug020_busy_check_keeps_active_request_correlation():
    zapret_panel_js(r"""
const btnCheck=element('btn-check-zapret-update'),statusEl=element('zapret-update-status'),badge=element('zapret-version-badge');
const requested=[];
window.pywebview={api:{
  check_zapret_update:async(rid)=>{requested.push(rid);return {status:'busy',request_id:'zapret-check:0'};},
  get_zapret_status:async()=>stubStatus(),
}};
subject.setupZapretPanel();await tick();
await btnCheck.fire('click');await tick();
assert.deepEqual(requested,['zapret-check:1']);
assert.equal(btnCheck.disabled,true,'wait for the ACTIVE check instead of failing silently');
assert.match(statusEl.textContent,/уже выполняется/);
// The completion event carries the ACTIVE id, not the id this click has sent.
await fireWindow('nedotify:zapret_update_checked',{request_id:'zapret-check:0',update_available:false,current_version:'v72.13',latest_version:'v72.13'});
assert.equal(btnCheck.disabled,false);
assert.match(statusEl.textContent,/Установлена последняя версия/);
assert.equal(badge.textContent,'v72.13');
""")


def test_bug020_busy_without_correlation_id_unlocks_instead_of_dead_wait():
    zapret_panel_js(r"""
const btnCheck=element('btn-check-zapret-update'),statusEl=element('zapret-update-status');
window.pywebview={api:{
  check_zapret_update:async()=>({status:'busy'}),
  get_zapret_status:async()=>stubStatus(),
}};
subject.setupZapretPanel();await tick();
await btnCheck.fire('click');await tick();
assert.equal(btnCheck.disabled,false,'without a rid the button must not die for 30s');
assert.match(statusEl.textContent,/уже выполняется/);
assert.equal(timers.filter(t=>t.fn).length,0);
""")


def test_bug020_check_timeout_reports_honestly_and_unlocks():
    zapret_panel_js(r"""
const btnCheck=element('btn-check-zapret-update'),statusEl=element('zapret-update-status');
window.pywebview={api:{
  check_zapret_update:async()=>new Promise(()=>{}),
  get_zapret_status:async()=>stubStatus(),
}};
subject.setupZapretPanel();await tick();
btnCheck.fire('click');await tick();   // the bridge never answers: do not await the click
await flushTimers();
assert.equal(btnCheck.disabled,false);
assert.match(statusEl.textContent,/слишком много времени/);
""")


def test_bug020_completion_during_inflight_busy_answer_is_not_lost():
    # E2: the ACTIVE check's completion event can arrive while a busy answer
    # is still in flight (the bridge promise resolves after the event). The
    # rid does not match yet, so the event used to be dropped and the UI then
    # waited a dead 30 s for an event that had already fired.
    zapret_panel_js(r"""
const btnCheck=element('btn-check-zapret-update'),statusEl=element('zapret-update-status');
let releaseSecond=null;
window.pywebview={api:{
  check_zapret_update:async(rid)=>{
    if (rid==='zapret-check:1') return new Promise(()=>{});  // first check runs server-side
    return new Promise(r=>{releaseSecond=()=>r({status:'busy',request_id:'zapret-check:1'});});
  },
  get_zapret_status:async()=>stubStatus(),
}};
subject.setupZapretPanel();await tick();
btnCheck.fire('click');await tick();          // click 1 hangs -> the timeout will unlock
await flushTimers();
assert.equal(btnCheck.disabled,false);
btnCheck.fire('click');await tick();          // click 2: busy answer in flight, unresolved
// the first check completes NOW, before the busy answer resolves
await fireWindow('nedotify:zapret_update_checked',{request_id:'zapret-check:1',update_available:false,current_version:'v72.13',latest_version:'v72.13'});
releaseSecond();await tick();await tick();
assert.equal(btnCheck.disabled,false,'the cached completion must finish the adopted wait');
assert.match(statusEl.textContent,/Установлена последняя версия/,'the real result must land, not a busy placeholder');
assert.equal(timers.filter(t=>t.fn).length,0,'no 30 s dead wait for an event that already fired');
""")


def test_bug026_badge_shows_versions_and_honest_states():
    zapret_panel_js(r"""
const btnCheck=element('btn-check-zapret-update'),statusEl=element('zapret-update-status'),badge=element('zapret-version-badge');
window.pywebview={api:{
  check_zapret_update:async(rid)=>({status:'pending',request_id:rid}),
  get_zapret_status:async()=>stubStatus(),
}};
subject.setupZapretPanel();await tick();
// update available: "installed X -> available Y"
await btnCheck.fire('click');await tick();
await fireWindow('nedotify:zapret_update_checked',{request_id:'zapret-check:1',update_available:true,current_version:'v72.13',latest_version:'v72.14'});
assert.equal(badge.textContent,'v72.14','the badge must show latest_version (there is no `version` field)');
assert.match(statusEl.textContent,/v72\.13/);
assert.match(statusEl.textContent,/v72\.14/);
assert.match(statusEl.textContent,/Обновить/);
// manual update required: honest app-update text
await btnCheck.fire('click');await tick();
await fireWindow('nedotify:zapret_update_checked',{request_id:'zapret-check:2',update_available:true,manual_update_required:true,latest_version:'v99.0'});
assert.match(statusEl.textContent,/обновите приложение NeDotify/i);
assert.doesNotMatch(statusEl.textContent,/Нажмите «Обновить»/);
// version unknown
await btnCheck.fire('click');await tick();
await fireWindow('nedotify:zapret_update_checked',{request_id:'zapret-check:3',version_unknown:true});
assert.match(statusEl.textContent,/Не удалось определить последнюю доступную версию/);
// network error is not reported as "you have the latest version"
await btnCheck.fire('click');await tick();
await fireWindow('nedotify:zapret_update_checked',{request_id:'zapret-check:4',error:'github unreachable'});
assert.match(statusEl.textContent,/Не удалось проверить обновления/);
assert.ok(toasts.some(t=>t[1]==='error'));
""")


def test_bug021_inflight_apply_survives_reopen():
    zapret_panel_js(r"""
const toggle=element('toggle-zapret-enabled'),select=element('select-zapret-mode'),btnUpdate=element('btn-update-zapret');
let backendRunning=false,resolveToggle=null;
window.pywebview={api:{
  toggle_zapret:(...args)=>{calls.push(['zapret',...args]);return new Promise(r=>{resolveToggle=()=>{backendRunning=Boolean(args[0]);r({success:true,running:backendRunning,message:'запущен'});};});},
  get_zapret_status:async()=>stubStatus({running:backendRunning,message:backendRunning?'Zapret запущен':'Zapret отключен'}),
}};
subject.setupZapretPanel();await tick();
await toggle.fire('click');
assert.equal(toggle.classList.contains('on'),true,'optimistic state stays while the call is in flight');
assert.equal(toggle.disabled,true);
assert.equal(select.disabled,true);
assert.equal(btnUpdate.disabled,true);
subject.setupZapretPanel();await tick();  // leave and re-enter during the apply
assert.equal(toggle.classList.contains('on'),true,'reopen must not clobber an in-flight apply');
resolveToggle();await tick();await tick();
assert.equal(backendRunning,true);
assert.equal(toggle.classList.contains('on'),true,'the final state comes from the backend fact');
assert.equal(toggle.disabled,false);
assert.equal(select.disabled,false);
assert.equal(btnUpdate.disabled,false);
""")


def test_bug021_failed_apply_reports_and_unlocks():
    zapret_panel_js(r"""
const toggle=element('toggle-zapret-enabled'),select=element('select-zapret-mode'),btnUpdate=element('btn-update-zapret');
window.pywebview={api:{
  toggle_zapret:async()=>({success:false,running:false,message:'отказ'}),
  get_zapret_status:async()=>stubStatus(),
}};
subject.setupZapretPanel();await tick();
await toggle.fire('click');await tick();await tick();
assert.equal(toggle.classList.contains('on'),false);
assert.equal(toggle.disabled,false);
assert.equal(select.disabled,false);
assert.equal(btnUpdate.disabled,false);
assert.ok(toasts.some(t=>t[1]==='warning'));
""")


def test_selection_progress_and_cancel_keep_controls_locked_until_worker_finishes():
    zapret_panel_js(r"""
const toggle=element('toggle-zapret-enabled'), select=element('select-zapret-mode');
const status=element('zapret-update-status'), host=element('status-host');
status.parentElement=host;
let finish;
window.pywebview={api:{
  toggle_zapret:async(enabled)=>{
    calls.push(['toggle',enabled]);
    if(enabled)return new Promise(resolve=>{finish=resolve;});
    return {success:true,pending:true,running:true};
  },
  get_zapret_status:async()=>stubStatus(),
}};
subject.setupZapretPanel();await tick();
await toggle.fire('click');
await fireWindow('nedotify:zapret_selection_progress',{message:'Попытка 2 из 5'});
assert.equal(status.textContent,'Попытка 2 из 5');
const cancel=host.children.find(child=>child.textContent==='Отменить включение');
assert.ok(cancel);
await cancel.onclick();
assert.equal(cancel.disabled,true);
assert.equal(select.disabled,true);
assert.deepEqual(calls.filter(call=>call[0]==='toggle').map(call=>call[1]),[true,false]);
finish({success:false,running:false,message:'Подбор отменён'});await tick();await tick();
assert.equal(select.disabled,false);
assert.equal(toggle.classList.contains('on'),false);
""")


def test_update_check_completion_cannot_overwrite_active_selection_progress():
    zapret_panel_js(r"""
const toggle=element('toggle-zapret-enabled'),select=element('select-zapret-mode');
const check=element('btn-check-zapret-update'),status=element('zapret-update-status');
let finish,requestId;
window.pywebview={api:{
  get_zapret_status:async()=>stubStatus(),
  check_zapret_update:async(rid)=>{requestId=rid;return {status:'pending',request_id:rid};},
  toggle_zapret:()=>new Promise(resolve=>{finish=resolve;}),
}};
subject.setupZapretPanel();await tick();
await check.fire('click');await tick();
await toggle.fire('click');await tick();
await fireWindow('nedotify:zapret_selection_progress',{message:'Попытка 3 из 5'});
await fireWindow('nedotify:zapret_update_checked',{request_id:requestId,latest_version:'v72.13',current_version:'v72.13'});
assert.equal(status.textContent,'Попытка 3 из 5');
finish({success:false,running:false,message:'Подбор отменён'});await tick();
""")


def test_bug052_update_locks_toggle_select_and_itself():
    zapret_panel_js(r"""
const toggle=element('toggle-zapret-enabled'),select=element('select-zapret-mode'),btnUpdate=element('btn-update-zapret');
let resolveUpdate=null;
window.pywebview={api:{
  update_zapret:()=>new Promise(r=>{resolveUpdate=r;}),
  get_zapret_status:async()=>stubStatus(),
}};
subject.setupZapretPanel();await tick();
btnUpdate.fire('click');await tick();   // in flight: do not await the click
assert.equal(btnUpdate.disabled,true);
assert.equal(toggle.disabled,true,'no toggle while winws may be replaced');
assert.equal(select.disabled,true,'no mode change while winws may be replaced');
resolveUpdate({success:true,message:'обновлено',status:{version:'v72.13'}});
await tick();await tick();
assert.equal(btnUpdate.disabled,false);
assert.equal(toggle.disabled,false);
assert.equal(select.disabled,false);
""")


def test_bug052_update_bridge_unavailable_reports_and_unlocks():
    zapret_panel_js(r"""
const btnUpdate=element('btn-update-zapret'),statusEl=element('zapret-update-status');
window.pywebview={api:{get_zapret_status:async()=>stubStatus()}};  // update_zapret missing
subject.setupZapretPanel();await tick();
btnUpdate.fire('click');await tick();await tick();
assert.equal(btnUpdate.disabled,false);
assert.ok(toasts.some(t=>t[1]==='error'),'the failure must reach the toast channel');
assert.match(statusEl.textContent,/Zapret отключен/,'the final refresh lands the honest backend status');
""")


def test_bug051_update_safety_timeout_unlocks_panel():
    zapret_panel_js(r"""
const btnUpdate=element('btn-update-zapret'),statusEl=element('zapret-update-status'),toggle=element('toggle-zapret-enabled');
window.pywebview={api:{
  update_zapret:()=>new Promise(()=>{}),
  get_zapret_status:async()=>stubStatus(),
}};
subject.setupZapretPanel();await tick();
btnUpdate.fire('click');await tick();   // hung bridge: do not await the click
assert.equal(btnUpdate.disabled,true);
await flushTimers();await tick();
assert.equal(btnUpdate.disabled,false,'the 120s safety timeout must unlock the panel');
assert.equal(toggle.disabled,false);
assert.match(statusEl.textContent,/не завершилось вовремя/);
assert.equal(timers.filter(t=>t.fn).length,0);
""")


def test_bug050_053_status_message_and_mismatch_warnings():
    zapret_panel_js(r"""
const statusEl=element('zapret-update-status'),warn=element('zapret-state-warning'),toggle=element('toggle-zapret-enabled');
window.pywebview={api:{get_zapret_status:async()=>stubStatus({enabled:true,running:false,message:'Zapret отключен'})}};
subject.setupZapretPanel();await tick();
assert.match(statusEl.textContent,/Zapret отключен/,'status.message must be visible');
assert.equal(warn.style.display,'block');
assert.match(warn.textContent,/не запущен/);
window.pywebview.api.get_zapret_status=async()=>stubStatus({enabled:true,running:true,message:'Zapret запущен'});
subject.setupZapretPanel();await tick();
assert.equal(warn.style.display,'none','a consistent state shows no warning');
window.pywebview.api.get_zapret_status=async()=>stubStatus({enabled:false,auto_start:true,message:'Zapret отключен'});
subject.setupZapretPanel();await tick();
assert.equal(warn.style.display,'block');
assert.match(warn.textContent,/автозапуск не сработает/,'autostart without enabled services must be explained');
""")


def test_bug055_unknown_mode_gets_placeholder_option():
    zapret_panel_js(r"""
const select=element('select-zapret-mode'),toggle=element('toggle-zapret-enabled');
window.pywebview={api:{get_zapret_status:async()=>stubStatus({mode:'custom',custom_args:'--fake-tls 5'})}};
subject.setupZapretPanel();await tick();
assert.equal(select.value,'custom','an unknown stored mode must not blank the select');
assert.equal(select.children.length,1);
assert.equal(select.children[0].value,'custom');
assert.match(select.children[0].textContent,/Свой режим/);
select.value='';
subject.setupZapretPanel();await tick();
assert.equal(select.children.length,1,'the placeholder is injected once');
// the stored mode still travels with the toggle (custom_args preserved)
window.pywebview.api.toggle_zapret=(...args)=>{calls.push(['zapret',...args]);return Promise.resolve({success:true,running:false});};
await toggle.fire('click');await tick();await tick();
assert.deepEqual(calls.find(c=>c[0]==='zapret'),['zapret',true,'custom','--fake-tls 5','']);
""")


def test_bug055_mode_alternation_never_duplicates_options():
    # E2: the old single-slot guard remembered only the last injected mode, so
    # alternating custom <-> preset stacked duplicate <option>s. Presets must
    # never be injected (static markup owns them) and the placeholder must be
    # pruned once the backend reports a preset again.
    zapret_panel_js(r"""
const select=element('select-zapret-mode'),toggle=element('toggle-zapret-enabled');
let mode='custom';
window.pywebview={api:{get_zapret_status:async()=>stubStatus({mode})}};
subject.setupZapretPanel();await tick();
assert.equal(select.children.length,1,'the custom placeholder is injected');
mode='standard';
subject.setupZapretPanel();await tick();
assert.equal(select.children.length,0,'returning to a preset prunes the placeholder');
mode='custom';
subject.setupZapretPanel();await tick();
assert.equal(select.children.length,1,'the placeholder is re-injected once after the prune');
mode='standard';
subject.setupZapretPanel();await tick();
assert.equal(select.children.length,0,'no accumulation across alternations');
// the placeholder still travels with the toggle after a prune cycle
mode='custom';
subject.setupZapretPanel();await tick();
window.pywebview.api.toggle_zapret=(...args)=>{calls.push(['zapret',...args]);return Promise.resolve({success:true,running:false});};
await toggle.fire('click');await tick();await tick();
assert.deepEqual(calls.find(c=>c[0]==='zapret'),['zapret',true,'custom','','']);
""")


def test_bug056_switch_semantics_are_kept_in_sync():
    zapret_panel_js(r"""
const toggle=element('toggle-zapret-enabled'),autoStart=element('toggle-zapret-autostart'),autoUpdate=element('toggle-zapret-autoupdate');
window.pywebview={api:{get_zapret_status:async()=>stubStatus({running:true,auto_start:true,autoupdate:true})}};
subject.setupZapretPanel();await tick();
for (const btn of [toggle,autoStart,autoUpdate]) {
    assert.equal(btn.getAttribute('aria-checked'),'true',btn.id+' must mirror .on');
    assert.equal(btn.classList.contains('on'),true);
}
// toggle_zapret is missing -> the click fails and the switch restores ON (aria in sync)
await toggle.fire('click');await tick();await tick();
assert.equal(toggle.classList.contains('on'),true);
assert.equal(toggle.getAttribute('aria-checked'),'true');
// a real status of running:false syncs both the class and the attribute
window.pywebview.api.get_zapret_status=async()=>stubStatus({running:false});
subject.setupZapretPanel();await tick();
assert.equal(toggle.classList.contains('on'),false);
assert.equal(toggle.getAttribute('aria-checked'),'false');
""")


def test_bug057_hidden_checkbox_has_no_dead_handler():
    zapret_panel_js(r"""
const chk=element('zapret-auto-start'),autoStart=element('toggle-zapret-autostart');
window.pywebview={api:{get_zapret_status:async()=>stubStatus()}};
subject.setupZapretPanel();await tick();
await chk.fire('change');
assert.equal(calls.filter(c=>c[0]==='auto_start').length,0,'the hidden checkbox must be dead code');
await autoStart.fire('click');
assert.deepEqual(calls.find(c=>c[0]==='auto_start'),['auto_start',true,'zapret'],'the visible toggle is the single writer');
""")


def test_zapret_lifecycle_events_reach_the_panel():
    zapret_panel_js(r"""
const toggle=element('toggle-zapret-enabled'),statusEl=element('zapret-update-status'),badge=element('zapret-version-badge');
let backendRunning=true;
window.pywebview={api:{get_zapret_status:async()=>stubStatus({running:backendRunning})}};
subject.setupZapretPanel();await tick();
assert.equal(toggle.classList.contains('on'),true);
// late crash -> error toast + immediate re-sync to the stopped fact
backendRunning=false;
await fireWindow('nedotify:zapret_crashed',{message:'процесс упал',returncode:1,late:true});
assert.ok(toasts.some(t=>t[0]==='процесс упал'&&t[1]==='error'));
assert.equal(toggle.classList.contains('on'),false,'a crash must re-sync the toggle');
// network issue -> one warning per transition, replays stay silent
await fireWindow('nedotify:zapret_network_issue',{message:'сеть потеряна'});
assert.ok(toasts.some(t=>t[0]==='сеть потеряна'&&t[1]==='warning'));
const warningCount=toasts.length;
await fireWindow('nedotify:zapret_network_issue',{message:'сеть потеряна'});
assert.equal(toasts.length,warningCount);
// non-stoppable process after exit
await fireWindow('nedotify:zapret_still_running',{message:'остался запущен'});
assert.ok(toasts.some(t=>t[0]==='остался запущен'&&t[1]==='warning'));
// autostart failure feedback (BUG-033)
await fireWindow('nedotify:zapret_autostart_failed',{message:'автозапуск не удался'});
assert.ok(toasts.some(t=>t[0]==='автозапуск не удался'&&t[1]==='warning'));
// download phases -> status text (sync), badge on finish, toggle re-sync
window.dispatchEvent(new CustomEvent('nedotify:zapret_download_started',{detail:{message:'Загрузка файлов Zapret…'}}));
assert.match(statusEl.textContent,/Загрузка файлов Zapret/);
backendRunning=true;
window.dispatchEvent(new CustomEvent('nedotify:zapret_download_finished',{detail:{message:'Файлы Zapret успешно загружены!',version:'v72.13'}}));
assert.equal(badge.textContent,'v72.13');
await tick();
assert.equal(toggle.classList.contains('on'),true,'finished must refresh the toggle');
window.dispatchEvent(new CustomEvent('nedotify:zapret_download_failed',{detail:{message:'Ошибка загрузки Zapret'}}));
assert.match(statusEl.textContent,/Ошибка загрузки Zapret/);
await tick();
assert.ok(toasts.some(t=>t[1]==='error'));
""")


# ----------------------------- static HTML -----------------------------

def test_bug056_static_aria_attributes_present():
    for control_id in ("toggle-zapret-enabled", "toggle-zapret-autostart", "toggle-zapret-autoupdate"):
        match = re.search(r'<button[^>]*\bid="%s"[^>]*>' % control_id, INDEX_HTML)
        assert match, control_id
        tag = match.group(0)
        assert 'role="switch"' in tag, control_id
        assert 'aria-checked="false"' in tag, control_id
    match = re.search(r'<div[^>]*\bid="zapret-update-status"[^>]*>', INDEX_HTML)
    assert match
    assert 'aria-live="polite"' in match.group(0)


def test_bug053_autostart_sublabel_explains_the_enabled_requirement():
    match = re.search(r'id="toggle-zapret-autostart"', INDEX_HTML)
    assert match
    row_start = INDEX_HTML.rfind('<div class="setting-row">', 0, match.start())
    assert row_start != -1
    assert "включённых службах Zapret" in INDEX_HTML[row_start:match.end()]


def test_bug058_obchod_typo_removed():
    assert "Obchod" not in INDEX_HTML
    assert "Обход DPI" in INDEX_HTML


# ----------------------------- backend tails -----------------------------

def test_bug041_build_status_exception_keeps_full_template():
    pytest.importorskip("services.zapret_service")
    from services.zapret_service import ZapretService

    service = ZapretService()

    def _boom():
        raise RuntimeError("probe failed")

    service.find_binary = _boom
    service._status_cache = {"version": "v72.13", "binary_found": True}
    service._build_status()
    cache = service._status_cache
    assert set(cache) >= {
        "binary_found", "binary_path", "running", "has_internet",
        "version", "message", "pending_update",
    }
    assert cache["message"] == "Ошибка определения статуса"
    assert cache["version"] == "v72.13", "values the previous build knew are preserved"
    assert cache["binary_found"] is True


def test_bug020_busy_check_reports_active_request_id():
    pytest.importorskip("core.api")
    from core.api import AppApi

    release = threading.Event()
    emitted = []

    def slow_check():
        release.wait(5)
        return {"update_available": False}

    api = object.__new__(AppApi)
    api._core = types.SimpleNamespace(zapret=types.SimpleNamespace(check_for_updates=slow_check))
    api._window_op_lock = threading.RLock()
    api._metadata_executor = ThreadPoolExecutor(max_workers=1)
    api._emit = lambda name, payload=None: emitted.append((name, payload))
    try:
        first = api.check_zapret_update("rid-1")
        assert first == {"status": "pending", "request_id": "rid-1"}
        busy = api.check_zapret_update("rid-2")
        assert busy["status"] == "busy"
        assert busy["request_id"] == "rid-1", "the UI must learn the ACTIVE request id"
        release.set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not emitted:
            time.sleep(0.01)
        assert emitted, "the running check must still emit its completion event"
        assert emitted[0][0] == "zapret_update_checked"
        assert emitted[0][1]["request_id"] == "rid-1"
    finally:
        api._metadata_executor.shutdown(wait=True)


def test_bug033_autostart_failure_emits_feedback_event():
    pytest.importorskip("core.app")
    from core.app import AppCore

    class _Settings:
        def __init__(self):
            self.enabled = None

        def get(self, category, key, default=None):
            if category != "zapret":
                return default
            return {"enabled": True, "auto_start": True}.get(key, default)

        def set(self, category, key, value):
            if category == "zapret" and key == "enabled":
                self.enabled = value

    settings = _Settings()
    emitted = []
    core = types.SimpleNamespace(
        settings=settings,
        zapret=types.SimpleNamespace(
            start=lambda **kw: (False, "запуск не удался"),
            stop=lambda: (True, "остановлен"),
            is_running=lambda: False,
            _emit_event=lambda name, payload=None: emitted.append((name, payload)),
        ),
        _shutting_down=threading.Event(),
        _zapret_start_thread=None,
        _service_lock=threading.RLock(),
    )
    AppCore.start_zapret_if_enabled(core)
    core._zapret_start_thread.join(5)
    assert settings.enabled is False, "one-writer fact semantics (A agent) must survive"
    feedback = [item for item in emitted if item[0] == "zapret_autostart_failed"]
    assert feedback, "the autostart failure must reach the UI event channel"
    assert "запуск не удался" in feedback[0][1]["message"]
