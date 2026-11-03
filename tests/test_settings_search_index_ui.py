"""Settings search builds its DOM index once and reuses it for keystrokes."""

from tests.jsdom import run_node, source


def test_settings_search_reuses_index_and_searches_cached_row_text():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
let panelScans = 0, timerCallback;
const input = {value: '', listeners: {}, addEventListener(type, fn) {this.listeners[type] = fn;}};
const row = {hidden: false, textContent: 'Изменить прозрачность', querySelectorAll: () => []};
const section = {hidden: false, textContent: 'Внешний вид Изменить прозрачность', querySelector: () => ({textContent: 'Внешний вид'}), querySelectorAll: selector => selector === '.setting-row, .setting-card-group, .custom-theme-box, .setting-item, .theme-card, .theme-mode-switcher, .font-cards-grid, .font-categories, .settings-background-shortcuts, .saved-custom-themes' ? [row] : []};
const button = {hidden: false, textContent: 'Внешний вид', dataset: {panel: 'appearance'}, classList: {contains: () => true}, click() {}};
const panel = {id: 'settings-appearance', hidden: false, classList: {contains: () => true}, querySelectorAll: selector => selector === '.settings-section' ? [section] : []};
const root = {querySelectorAll(selector) {if (selector === '.settings-panel') panelScans++; return selector === '.settings-panel' ? [panel] : [];}, querySelector(selector) {return selector.includes('[data-panel=') ? button : selector === '.settings-nav-btn.active' ? button : null;}};
const empty = {hidden: true};
const document = {getElementById(id) {return id === 'settings-search' ? input : id === 'view-settings' ? root : id === 'settings-search-empty' ? empty : null;}};
const context = vm.createContext({document, MutationObserver: undefined, clearTimeout() {}, setTimeout(fn) {timerCallback = fn; return 1;}});
const code = SOURCE;
const start = code.indexOf('export function initSettingsSearchFilter()');
const end = code.indexOf('\n}\n', start) + 3;
vm.runInContext(code.slice(start, end).replace('export ', ''), context);
context.initSettingsSearchFilter();
input.value = 'прозрач'; input.listeners.input(); timerCallback();
assert.equal(row.hidden, false);
assert.equal(panelScans, 1);
input.value = 'неизвестно'; input.listeners.input(); timerCallback();
assert.equal(row.hidden, true);
assert.equal(empty.hidden, false);
assert.equal(panelScans, 1, 'typing should not rescan settings panels');
""".replace('SOURCE', source('settings-panel.js')))
