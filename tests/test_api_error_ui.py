"""Bridge error events log diagnostics without duplicating Promise UI feedback."""

from tests.jsdom import run_node, source


def test_api_error_does_not_raise_duplicate_toast_or_operation_panel():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const logs = [], uiEvents = [];
const context = vm.createContext({
  console: {error: (...args) => logs.push(args)},
  document: {dispatchEvent: event => uiEvents.push(event)},
  CustomEvent: class {constructor(type, options) {this.type = type; this.detail = options.detail}},
  showToast() {throw Error('api_error must not trigger a duplicate toast')},
});
const code = SOURCE;
const start = code.indexOf("case 'api_error': {");
const end = code.indexOf("case 'lyrics_ready':", start);
assert.ok(start >= 0 && end > start);
const caseBody = code.slice(start, end);
vm.runInContext(`function handleApiError(data) { switch ('api_error') { ${caseBody} } }`, context);
context.handleApiError({method: 'save_settings', code: 'storage_write_failed', error: 'raw exception'});
assert.equal(logs.length, 1);
assert.equal(logs[0][0], 'Bridge API Error:');
assert.equal(logs[0][1], 'save_settings');
assert.equal(logs[0][2], 'storage_write_failed');
assert.equal(uiEvents.length, 0, 'Promise caller is the sole user-facing error channel');
""".replace('SOURCE', source('events.js')))
