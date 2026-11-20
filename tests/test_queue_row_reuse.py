"""Queue re-renders must move live rows instead of recreating them.

`renderQueue` used to wipe `#queue-drawer-content` and rebuild every row on each
`queue_updated` / `track_changed`. Besides the layout cost, that replayed every
row's entrance animation and defeated `settleList` (which cross-fades the *same*
nodes). The renderer is now keyed by `entry_id`: a row whose painted shape is
unchanged is reused verbatim, a moved row keeps its node, and only genuinely
different rows are rebuilt.

These tests drive the real `renderQueue` against a minimal DOM stub - no
jsdom, no browser, no audio.
"""

import json

from tests.jsdom import run_node, source

HARNESS = r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';

let created = 0;
class El {
    constructor(tag) {
        this.tagName = String(tag || 'div').toUpperCase();
        this.childNodes = [];
        this.dataset = {};
        this.style = {};
        this._classes = new Set();
        this.textContent = '';
        this.parent = null;
        this._html = '';
        created++;
    }
    get children() { return this.childNodes; }
    get firstChild() { return this.childNodes[0] || null; }
    get nextSibling() {
        if (!this.parent) return null;
        const at = this.parent.childNodes.indexOf(this);
        return this.parent.childNodes[at + 1] || null;
    }
    get classList() {
        const classes = this._classes;
        return {
            contains: name => classes.has(name),
            add: (...names) => names.forEach(name => classes.add(name)),
            remove: (...names) => names.forEach(name => classes.delete(name)),
            toggle: (name, on) => { (on === undefined ? !classes.has(name) : on) ? classes.add(name) : classes.delete(name); },
        };
    }
    set className(value) { this._classes = new Set(String(value).split(/\s+/).filter(Boolean)); }
    get className() { return [...this._classes].join(' '); }
    set innerHTML(value) { this._html = String(value); this.childNodes = []; }
    get innerHTML() { return this._html; }
    appendChild(node) { this.insertBefore(node, null); return node; }
    insertBefore(node, ref) {
        if (node.parent) node.parent.childNodes = node.parent.childNodes.filter(child => child !== node);
        const at = ref ? this.childNodes.indexOf(ref) : this.childNodes.length;
        this.childNodes.splice(at < 0 ? this.childNodes.length : at, 0, node);
        node.parent = this;
        return node;
    }
    remove() {
        if (this.parent) this.parent.childNodes = this.parent.childNodes.filter(child => child !== this);
        this.parent = null;
    }
    querySelector(selector) {
        // Only the three selectors buildQueueRow asks for, plus the numbered cell.
        if (selector === '.track-number') {
            this._number ||= Object.assign(new El('span'), {parent: this});
            return this._number;
        }
        return Object.assign(new El('div'), {parent: this});
    }
    querySelectorAll() { return []; }
    closest() { return null; }
    addEventListener() {}
}

const content = new El('div');
const context = vm.createContext({
    console, Date, Math, Set, Map, Number, String, Boolean, JSON, Promise, Object, Array,
    document: {
        getElementById: id => (id === 'queue-drawer-content' ? content : null),
        querySelectorAll: () => [],
        createElement: tag => new El(tag),
        createDocumentFragment: () => new El('fragment'),
        addEventListener() {},
    },
    window: {},
    formatTime: seconds => String(seconds || 0),
    renderIcons() {},
    getCoverUrl: track => track?.cover_url || '',
    escapeHtml: text => String(text ?? ''),
    showToast() {},
    getCurrentTrack: () => null,
    playTrack() {},
    incrementQueueVersion() {},
    getTrackWaveState: () => ({active: false, status: ''}),
    stopTrackWave() {},
    retryTrackWave() {},
});

const code = SOURCE.replace(/^import .*;\r?$/gm, '').replace(/\bexport\s+/g, '');
vm.runInContext(code + '\nglobalThis.renderQueue = renderQueue; globalThis.setTab = value => { queueTab = value; };', context);

const track = (id, title) => ({id, entry_id: `entry-${id}`, source: 'youtube', source_id: String(id),
    title: title || `Song ${id}`, artist: 'Artist', duration: 120});

const first = [track(1), track(2), track(3), track(4)];
context.renderQueue(first, 0);
const rowsOf = () => content.childNodes.filter(node => node._classes.has('track-item'));
let knownRows = new Set();
const newRowsSince = () => rowsOf().filter(row => !knownRows.has(row)).length;
const rememberRows = () => { knownRows = new Set(rowsOf()); };
assert.equal(rowsOf().length, 4, 'current + three upcoming rows');
const initial = rowsOf();
assert.deepEqual(initial.map(row => row.dataset.rowKey), ['entry-1', 'entry-2', 'entry-3', 'entry-4']);
assert.equal(initial[0]._classes.has('playing'), true, 'the current track is marked playing');
rememberRows();

// 1. Advancing the current track moves the marker. `queueRows` renders
// "current + upcoming", so the played row is dropped; the surviving rows keep
// their nodes and only the state marker moves between them.
rememberRows();
context.renderQueue(first, 1);
const advanced = rowsOf();
assert.deepEqual(advanced.map(row => row.dataset.rowKey), ['entry-2', 'entry-3', 'entry-4']);
assert.equal(advanced[0], initial[1], 'the row that becomes current is the same node');
assert.equal(advanced[1], initial[2], 'untouched rows are reused');
assert.equal(advanced[2], initial[3]);
assert.equal(initial[0].parent, null, 'the played row left the list');
assert.equal(newRowsSince(), 0, 'a track change must not rebuild any row');
assert.equal(advanced[0]._classes.has('playing'), true, 'the marker followed the track');
assert.equal(initial[1]._classes.has('playing'), true);
// The rectangle is refreshed in place, without re-creating the row.
assert.equal(initial[1].dataset.index, 1);

// 2. Same list again: nothing is rebuilt at all.
rememberRows();
context.renderQueue(first, 1);
const idle = rowsOf();
for (let index = 0; index < idle.length; index++) assert.equal(idle[index], advanced[index]);
assert.equal(newRowsSince(), 0, 'an unchanged queue must not create nodes');

// 3. Reorder: nodes travel with their entry.
const reordered = [first[1], first[3], first[2], first[0]];
context.renderQueue(reordered, 0);
const moved = rowsOf();
assert.deepEqual(moved.map(row => row.dataset.rowKey), ['entry-2', 'entry-4', 'entry-3', 'entry-1']);
assert.equal(moved[0], initial[1], 'a moved row keeps its node');
assert.equal(moved[1], initial[3]);
assert.equal(moved[2], initial[2], 'a row that only changed position is reused');
// `entry-1` had left the list in step 1, so this is a fresh row.
assert.equal(moved[3] === initial[0], false, 'a row that left the list is rebuilt on return');

// 4. Removing an entry drops exactly one node. (`entry-1` was re-created in
// step 3, so the live node to compare against is `moved[3]`, not `initial[0]`.)
context.renderQueue([first[1], first[3], first[0]], 0);
const trimmed = rowsOf();
assert.deepEqual(trimmed.map(row => row.dataset.rowKey), ['entry-2', 'entry-4', 'entry-1']);
assert.equal(trimmed[0], moved[0]);
assert.equal(trimmed[1], moved[1]);
assert.equal(trimmed[2], moved[3]);
assert.equal(moved[2].parent, null, 'the removed row left the DOM');

// 5. A changed title is a changed shape: that row (and only that row) rebuilds.
const renamed = [first[1], first[3], { ...first[0], title: 'Renamed' }];
context.renderQueue(renamed, 0);
const rebuilt = rowsOf();
assert.deepEqual(rebuilt.map(row => row.dataset.rowKey), ['entry-2', 'entry-4', 'entry-1']);
assert.equal(rebuilt[0], moved[0], 'untouched rows stay');
assert.equal(rebuilt[1], moved[1]);
assert.equal(rebuilt[2] === moved[3], false, 'the renamed row is rebuilt');
assert.match(rebuilt[2].innerHTML, /Renamed/);

// 6. Switching tabs must not reuse upcoming rows as history rows.
const upcomingNodes = rowsOf();
context.setTab('history');
context.renderQueue([first[0]], 0, [{...first[0], queue_index: 0}]);
assert.equal(rowsOf().length, 1);
assert.equal(upcomingNodes[0].parent, null, 'upcoming rows are gone while history is shown');
assert.deepEqual(rowsOf().map(row => row.dataset.rowKey), ['entry-1']);
assert.equal(rowsOf()[0] === rebuilt[2], false, 'a history row is not an upcoming row');
context.setTab('upcoming');
"""


def test_queue_rows_are_reused_across_rerenders():
    run_node(HARNESS.replace("SOURCE", source("queue.js")))
