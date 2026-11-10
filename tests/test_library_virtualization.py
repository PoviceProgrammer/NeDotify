"""Execute the shipped library/row JS against deterministic DOM geometry.

The small DOM implements normal insertion/focus/event behavior; row height,
scrollport size and flex gap are controlled independently to exercise resizing.
Real WebView benchmarks remain the authority for paint/CPU measurements.
"""
from tests.jsdom import run_node, source


HARNESS = r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
let rowHeight = 52, rowGap = 4, listTop = 300, currentTrack = null;
let frames = new Map(), nextFrame = 0, iconRoots = [], playCalls = [], menuCalls = [];
class Events {
    constructor() { this.listeners = new Map(); }
    addEventListener(type, fn) { if (!this.listeners.has(type)) this.listeners.set(type, new Set()); this.listeners.get(type).add(fn); }
    removeEventListener(type, fn) { this.listeners.get(type)?.delete(fn); }
    emit(type, event = {}) { event.type = type; event.target ||= this; event.preventDefault ||= () => { event.prevented = true; }; event.stopPropagation ||= () => {}; for (const fn of [...this.listeners.get(type) || []]) fn(event); return event; }
}
class Element extends Events {
    constructor(tag = 'div') { super(); this.tagName = tag.toUpperCase(); this.children = []; this.parentElement = null; this.style = {}; this.dataset = {}; this.attrs = {}; this._classes = new Set(); this.nodeType = 1; this.tabIndex = tag === 'button' ? 0 : -1; this.clientTop = 0; this.scrollTop = 0; this.clientHeight = 600; this.textContent = ''; this.hidden = false; this.classList = { add: (...xs) => xs.forEach(x => this._classes.add(x)), remove: (...xs) => xs.forEach(x => this._classes.delete(x)), contains: x => this._classes.has(x), toggle: (x, force) => { const add = force ?? !this._classes.has(x); add ? this._classes.add(x) : this._classes.delete(x); return add; } }; }
    set className(value) { this._classes = new Set(value.split(/\s+/).filter(Boolean)); } get className() { return [...this._classes].join(' '); }
    setAttribute(name, value) { this.attrs[name] = String(value); if (name === 'class') this.className = value; if (name === 'id') this.id = value; if (name === 'tabindex') this.tabIndex = Number(value); }
    getAttribute(name) { return this.attrs[name] ?? null; }
    appendChild(node) { return this.insertBefore(node, null); }
    insertBefore(node, before) { if (node === before) return node; if (node.parentElement) node.remove(); const at = before ? this.children.indexOf(before) : this.children.length; assert.ok(at >= 0); this.children.splice(at, 0, node); node.parentElement = this; return node; }
    prepend(node) { this.insertBefore(node, this.firstChild); }
    after(node) { this.parentElement.insertBefore(node, this.nextSibling); }
    remove() { if (!this.parentElement) return; if (this.contains(document.activeElement)) document.activeElement = document.body; const at = this.parentElement.children.indexOf(this); this.parentElement.children.splice(at, 1); this.parentElement = null; }
    replaceChildren(...nodes) { for (const child of [...this.children]) child.remove(); nodes.forEach(node => this.appendChild(node)); }
    get firstChild() { return this.children[0] || null; }
    get nextSibling() { return this.parentElement?.children[this.parentElement.children.indexOf(this) + 1] || null; }
    get isConnected() { return this === document.body || Boolean(this.parentElement?.isConnected); }
    contains(node) { return node === this || this.children.some(child => child.contains(node)); }
    matches(selector) { return selector.split(',').some(s => { s = s.trim(); if (s.startsWith('#')) return this.id === s.slice(1); if (s.startsWith('.')) return s.slice(1).split('.').every(x => this._classes.has(x)); if (s.startsWith('[')) return this.getAttribute(s.slice(1, -1)) !== null; return this.tagName.toLowerCase() === s.split('[')[0]; }); }
    closest(selector) { return this.matches(selector) ? this : this.parentElement?.closest(selector) || null; }
    querySelectorAll(selector) { return this.children.flatMap(child => [...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector)]); }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    set innerHTML(html) {
        this.replaceChildren(); this._html = html; const stack = [this];
        for (const token of html.match(/<[^>]+>|[^<]+/g) || []) {
            if (token.startsWith('</')) { if (stack.length > 1) stack.pop(); continue; }
            const match = token.match(/^<([\w-]+)([^>]*)>/); if (!match) continue;
            const node = new Element(match[1]);
            for (const attr of match[2].matchAll(/([\w-]+)="([^"]*)"/g)) node.setAttribute(attr[1], attr[2]);
            stack.at(-1).appendChild(node); if (!['img', 'input', 'br'].includes(match[1]) && !token.endsWith('/>')) stack.push(node);
        }
    }
    get innerHTML() { return this._html || ''; }
    getBoundingClientRect() {
        if (this === scroller) return { top: 20, height: this.clientHeight };
        if (this === container) return { top: 20 + listTop - scroller.scrollTop, height: this.scrollHeight };
        const row = this.closest('.lib-table-row');
        if (row) { const siblings = container.children; let y = listTop; for (const sibling of siblings) { if (sibling === row) break; y += sibling.height + rowGap; } return { top: 20 + y - scroller.scrollTop, height: rowHeight }; }
        return { top: 0, height: this.height };
    }
    get height() { return this.classList.contains('lib-table-row') ? rowHeight : parseFloat(this.style.height) || 0; }
    get scrollHeight() { return this.children.reduce((n, child) => n + child.height, 0) + Math.max(0, this.children.length - 1) * rowGap; }
    getClientRects() { return this.hidden ? [] : [this.getBoundingClientRect()]; }
    focus() { document.activeElement = this; const row = this.closest('.lib-table-row'); if (row) { const rect = row.getBoundingClientRect(); if (rect.top < 20) scroller.scrollTop += rect.top - 20; else if (rect.top + rowHeight > 20 + scroller.clientHeight) scroller.scrollTop += rect.top + rowHeight - 20 - scroller.clientHeight; } container.emit('focusin', { target: this }); }
    click() { const event = { target: this, preventDefault() {}, stopPropagation() {} }; this.onclick?.(event); this.emit('click', event); }
}
const document = new Events(); document.body = new Element('body'); document.documentElement = new Element('html'); document.documentElement.dataset.uiStyle = 'current'; document.activeElement = document.body; document.scrollingElement = document.documentElement; document.fonts = new Events();
document.createElement = tag => new Element(tag); document.querySelectorAll = selector => document.body.querySelectorAll(selector); document.querySelector = selector => document.body.querySelector(selector); document.getElementById = id => document.querySelector('#' + id);
const scroller = new Element(); scroller.overflowY = 'auto'; document.body.appendChild(scroller);
const container = new Element(); container.id = 'lib-active-tracks'; scroller.appendChild(container);
function element(id, parent = document.body) { const found = document.getElementById(id); if (found) return found; const el = new Element(); el.id = id; parent.appendChild(el); return el; }
const window = new Events(); window.pywebview = { api: { play_track: (...args) => playCalls.push(args) } }; window.awaitBridge = async () => {};
const storage = new Map(); const observers = [];
class ResizeObserver { constructor(callback) { this.callback = callback; observers.push(this); } observe() {} unobserve() {} disconnect() { this.disconnected = true; } }
class MutationObserver { constructor(callback) { this.callback = callback; } observe() {} disconnect() {} }
function flush() { let guard = 0; while (frames.size) { assert.ok(guard++ < 20); const callbacks = [...frames.values()]; frames.clear(); callbacks.forEach(fn => fn()); } }
function scrollTo(index, remainder = 0) { scroller.scrollTop = listTop + index * (rowHeight + rowGap) + remainder; scroller.emit('scroll'); flush(); }
function resize() { observers.filter(x => !x.disconnected).forEach(x => x.callback()); flush(); }
const context = vm.createContext({ console, document, window, ResizeObserver, MutationObserver, Set, Map, Promise, Math, Number, String, Date, Intl,
    localStorage: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value) },
    requestAnimationFrame: fn => { frames.set(++nextFrame, fn); return nextFrame; }, cancelAnimationFrame: id => frames.delete(id),
    getComputedStyle: node => ({ overflowY: node.overflowY || 'visible', rowGap: String(rowGap) }),
    CSS: { escape: String }, renderIcons: root => iconRoots.push(root), getCurrentTrack: () => currentTrack, getCoverUrl: () => '',
    escapeHtml: value => String(value ?? ''), formatTime: () => '1:00', formatArtistNames: value => value, getSourceIcon: () => '', isHiddenSource: () => false,
    showToast() {}, showTrackContextMenu: (...args) => menuCalls.push(args), setTimeout: () => 1, clearTimeout() {},
});
function load(code) { vm.runInContext(code.replace(/^import .*;\r?$/gm, '').replace(/\bexport\s+/g, ''), context); }
load(UTILS.slice(UTILS.indexOf('export function isSameTrack('), UTILS.indexOf('// M-2: warn when localStorage')));
load(UTILS.slice(UTILS.indexOf('const pendingTrackDownloads'), UTILS.indexOf('let activeRichMenu')));
load(UTILS.slice(UTILS.indexOf('export const selectedTracksMap'), UTILS.indexOf('export function initBatchActionBar')));
load(VIEW);
load(VIRTUAL);
const tracks = Array.from({ length: 10000 }, (_, index) => ({ id: index + 1, source: 'test', source_id: `track-${index}`, title: `Track ${index}`, artist: 'Artist', duration: 60 }));
const rows = () => container.querySelectorAll('.track-item');
const rowAt = index => rows().find(row => row._trackIndex === index);
function mount() { return context.createLibraryVirtualList(container, tracks, { createRow: (track, index, all) => context.decorateLibraryRow(context.createTrackElement(track, index, all, currentTrack), track, index), renderIcons: root => iconRoots.push(root) }); }
function click(row, modifiers = {}) { return row.emit('click', { target: row, ...modifiers }); }
"""


def run_library(body):
    run_node("const UTILS = " + source("utils.js") + ";\nconst VIEW = " + source("library-view.js") +
             ";\nconst VIRTUAL = " + source("library-virtual-list.js") + ";\n" + HARNESS + body)


def test_long_list_has_bounded_dom_and_exact_scroll_extent_without_fetching():
    run_library(r"""
const list = mount();
const expected = tracks.length * (rowHeight + rowGap) - rowGap;
for (const index of [0, 500, 9000, 9999, 120, 0]) {
    scrollTo(index, 3);
    assert.equal(container.scrollHeight, expected, 'spacers must preserve every original flex gap');
    assert.equal(scroller.scrollTop, listTop + index * 56 + 3);
    assert.ok(rowAt(index));
    assert.ok(rows().length <= Math.ceil(scroller.clientHeight / 56) + 18);
    assert.ok(Math.abs(rowAt(index).getBoundingClientRect().top - 17) < .01);
}
assert.ok(iconRoots.length > 0 && iconRoots.every(root => root?.classList.contains('track-item')));
click(rowAt(4)); assert.equal(playCalls.at(-1)[1], tracks); assert.equal(playCalls.at(-1)[1].length, 10000); assert.equal(playCalls.at(-1)[2], 4);
rowAt(4).emit('contextmenu', { target: rowAt(4) }); assert.equal(menuCalls.at(-1)[2], tracks); assert.equal(menuCalls.at(-1)[3], 4);
list.destroy(); assert.equal(scroller.listeners.get('scroll').size, 0); assert.equal(document.listeners.get('dragend').size, 0);
""")


def test_focus_and_drag_keep_original_nodes_and_tab_crosses_virtual_boundaries():
    run_library(r"""
const list = mount();
const focused = rowAt(3), button = focused.querySelector('.like-btn'); button.focus(); flush();
scrollTo(9000); assert.equal(document.activeElement, button); assert.equal(rowAt(3), focused);
assert.ok(rows().length < 35, 'a distant focused row must not mount all intervening rows');
container.emit('dragstart', { target: rowAt(9000) }); const dragged = rowAt(9000);
document.activeElement = document.body; container.emit('focusout'); scrollTo(100);
assert.equal(rowAt(9000), dragged); assert.ok(!rowAt(3));
document.emit('dragend'); flush(); assert.ok(!rowAt(9000));
const last = rows().at(-1), lastIndex = last._trackIndex; last.querySelector('.track-more-btn').focus();
let event = container.emit('keydown', { key: 'Tab', target: last.querySelector('.track-more-btn') });
assert.ok(event.prevented); assert.equal(document.activeElement, rowAt(lastIndex + 1));
event = container.emit('keydown', { key: 'Tab', shiftKey: true, target: document.activeElement });
assert.ok(event.prevented); assert.equal(document.activeElement, rowAt(lastIndex).querySelector('.track-more-btn'));
list.destroy();
""")


def test_entrance_scale_does_not_shrink_virtual_scroll_extent():
    run_library(r"""
const original = Element.prototype.getBoundingClientRect;
Object.defineProperty(Element.prototype, 'offsetHeight', {get(){return this.height;}});
Element.prototype.getBoundingClientRect = function(){
 const rect=original.call(this); return {...rect,height:rect.height*.995};
};
const list=mount();
assert.equal(container.scrollHeight,tracks.length*56-4);
scrollTo(9000); assert.ok(rowAt(9000));
assert.equal(container.scrollHeight,tracks.length*56-4);
list.destroy();
""")


def test_selection_and_playing_state_survive_recycling_and_batch_data_stays_complete():
    run_library(r"""
const list = mount(); scrollTo(100); click(rowAt(100), { ctrlKey: true });
scrollTo(1000); click(rowAt(1000), { shiftKey: true });
assert.equal(vm.runInContext('selectedTracksMap.size', context), 901);
assert.equal(vm.runInContext('selectedTracksMap.get("track-500").title', context), 'Track 500');
for (const row of rows()) assert.equal(row.classList.contains('selected'), row._trackIndex >= 100 && row._trackIndex <= 1000);
currentTrack = tracks[500]; scrollTo(500);
assert.ok(rowAt(500).classList.contains('playing')); assert.ok(rowAt(500).classList.contains('selected'));
context.clearTrackSelection(); scrollTo(700); scrollTo(500); assert.ok(!rowAt(500).classList.contains('selected'));
const other = [tracks[0], tracks[1]]; const otherRow = context.createTrackElement(other[1], 1, other, null); container.appendChild(otherRow);
click(rowAt(500), { ctrlKey: true }); click(otherRow, { shiftKey: true });
assert.equal(vm.runInContext('selectedTracksMap.size', context), 2, 'shift anchor belongs to its collection');
list.destroy();
""")


def test_measured_resize_and_mini_player_visibility_keep_the_top_track_and_offset():
    run_library(r"""
const list = mount(); scrollTo(500, 17); const before = rowAt(500).getBoundingClientRect().top;
rowHeight = 64; rowGap = 6; listTop += 70; resize();
assert.equal(scroller.scrollTop, listTop + 500 * 70 + 17);
assert.equal(rowAt(500).getBoundingClientRect().top, before);
assert.equal(container.scrollHeight, tracks.length * 70 - 6);
scroller.clientHeight = 0; resize(); const saved = scroller.scrollTop;
rowHeight = 55; rowGap = 4; scroller.clientHeight = 400; resize();
assert.equal(scroller.scrollTop, listTop + 500 * 59 + 17); assert.notEqual(scroller.scrollTop, saved);
assert.ok(rows().length < 30); assert.equal(rowAt(500).getBoundingClientRect().top, before);
list.destroy();
""")


def test_pending_downloads_rehydrate_and_completion_updates_offscreen_track_objects():
    run_library(r"""
window.pywebview.api.download_track = async () => {};
const list = mount(); rowAt(3).querySelector('.download-btn').emit('click');
assert.ok(rowAt(3).querySelector('.download-btn').classList.contains('downloading'));
scrollTo(500); scrollTo(0);
assert.ok(rowAt(3).querySelector('.download-btn').classList.contains('downloading'));
const replacement = { ...tracks[3] }; const replacementRow = context.createTrackElement(replacement, 3, tracks, null);
assert.ok(replacementRow.querySelector('.download-btn').classList.contains('downloading'));
scrollTo(500); document.emit('nedotify:track_downloaded', { detail: { track_id: tracks[3].id } });
assert.equal(tracks[3].is_downloaded, true); assert.equal(replacement.is_downloaded, true);
scrollTo(0); assert.ok(rowAt(3).querySelector('.download-btn').classList.contains('downloaded'));
rowAt(5).querySelector('.download-btn').emit('click'); scrollTo(500);
document.emit('nedotify:track_download_failed', { detail: { source_id: tracks[5].source_id } }); scrollTo(0);
assert.ok(!rowAt(5).querySelector('.download-btn').classList.contains('downloading'));
let reject; window.pywebview.api.download_track = () => new Promise((resolve, fail) => { reject = fail; });
rowAt(6).querySelector('.download-btn').emit('click'); scrollTo(500); scrollTo(0);
assert.ok(rowAt(6).querySelector('.download-btn').classList.contains('downloading'));
reject(Error('download failed')); for(let i=0;i<4;i++) await Promise.resolve();
assert.ok(!rowAt(6).querySelector('.download-btn').classList.contains('downloading'), 'rejected request clears a recreated button too');
list.destroy();
""")


LIBRARY_SETUP = r"""
for (const id of ['lib-active-title','lib-active-sub','lib-empty-selection','lib-active-view','lib-btn-download-all','lib-card-favorites','lib-card-offline','lib-fav-count','lib-offline-count']) element(id);
let favoriteCount = null;
context.updateLibraryFavoriteCount = count => { favoriteCount = count; };
context.updateLibraryHero = () => {};
context.initPlaylistRecommendations = context.showPlaylistRecommendations = context.hidePlaylistRecommendations = () => {};
load(LIBRARY);
"""


def run_library_module(body):
    run_library("\nconst LIBRARY = " + source("library.js") + ";\n" + LIBRARY_SETUP + body)


def test_compact_summary_skips_full_collections_and_legacy_fallback_deduplicates_ids():
    run_library_module(r"""
storage.set('nedotify_favorites', JSON.stringify(['source-one','99','legacy','legacy']));
let fullCalls = 0; window.pywebview.api.get_favorites = async () => { fullCalls++; return [{ id:99, source_id:'source-one' }]; };
window.pywebview.api.get_downloaded_tracks = async () => { fullCalls++; return [{id:1},{id:2}]; };
window.pywebview.api.get_library_summary = async () => ({favorite_count:1, favorite_ids:['99','source-one'], downloaded_count:2});
await context.loadLibrarySummary(); assert.equal(fullCalls, 0); assert.equal(favoriteCount, 2); assert.equal(document.getElementById('lib-offline-count').textContent, '2 треков');
window.pywebview.api.get_library_summary = async () => { throw Error('Old bridge'); };
await context.loadLibrarySummary(); assert.equal(fullCalls, 2); assert.equal(favoriteCount, 2);
window.pywebview.api.get_library_summary = async () => ({favorite_count:-1});
await context.loadLibrarySummary(); assert.equal(fullCalls, 4); assert.equal(favoriteCount, 2);
delete window.pywebview.api.get_library_summary; await context.loadLibrarySummary(); assert.equal(fullCalls, 6);
""")


def test_show_more_is_explicit_and_appends_data_without_losing_scroll_or_queue():
    run_library_module(r"""
const calls = []; window.pywebview.api.get_library = async (limit, offset, metadata) => { calls.push([limit,offset,metadata]); return {tracks:tracks.slice(offset,offset+200),total:400,has_more:offset===0}; };
await context.selectSection('all'); assert.equal(calls.length, 1); assert.ok(rows().length < 40);
scrollTo(190, 5); assert.equal(calls.length, 1, 'scrolling must not fetch another loaded page');
const before = scroller.scrollTop, original = rowAt(190);
const more = document.getElementById('lib-all-more'); assert.ok(more); await more.onclick();
assert.deepEqual(calls, [[200,0,true],[200,200,true]]); assert.equal(scroller.scrollTop,before); assert.equal(rowAt(190),original);
assert.equal(container.scrollHeight,400*56-4); assert.equal(document.getElementById('lib-all-more'),null);
click(rowAt(190)); assert.equal(playCalls.at(-1)[1].length,400); assert.equal(playCalls.at(-1)[2],190);
context.showLibraryOverview = () => {};
""")


def test_collection_collages_request_only_four_tracks():
    run_library(r"""
const calls = []; window.pywebview.api.get_playlist_tracks = async (...args) => { calls.push(args); return tracks.slice(0,4); };
context.renderPlaylistCoverCollage = () => '<span>cover</span>';
const cover = element('cover'); context.setCollectionCover(cover,{id:99});
for (let i=0;i<8;i++) await Promise.resolve();
assert.deepEqual(calls,[[99,'local',4]]);
""")


def test_reverse_scroll_populates_visible_rows_in_the_scroll_event():
    run_library(r"""
const list=mount();
scrollTo(9999);
scroller.scrollTop=listTop;scroller.emit('scroll');
assert.ok(rowAt(0),'top rows must exist immediately on reverse scroll, before a deferred animation frame');
assert.ok(rows().length<40,'scroll fix must retain bounded DOM');
flush();assert.equal(container.scrollHeight,tracks.length*56-4);
list.destroy();
""")


def test_small_playlist_keeps_all_rows_ready_across_scroll_jumps():
    run_library(r"""
tracks.splice(42);
const list=mount();
assert.equal(rows().length,42,'small playlists must have no unmounted blank ranges');
const originals=rows();
scrollTo(40);scrollTo(0);
assert.deepEqual(rows(),originals,'scrolling must retain the ready rows and covers');
list.destroy();
""")
