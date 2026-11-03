import json
from pathlib import Path

from tests.jsdom import run_node, source


def test_full_frontend_module_graph_resolves_named_exports_without_running_app():
    directory = Path(__file__).resolve().parents[1] / 'ui' / 'web_new_v2' / 'js'
    sources = {path.name: path.read_text(encoding='utf-8') for path in directory.glob('*.js') if not path.name.endswith('.min.js')}
    run_node(r"""
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
const program = `import vm from 'node:vm';
const sources = ${JSON.stringify(SOURCES)};
const modules = new Map(), context = vm.createContext({});
function getModule(name) {
    if (!modules.has(name)) {
        if (!(name in sources)) throw new Error('Missing module: ' + name);
        modules.set(name, new vm.SourceTextModule(sources[name], {context, identifier:name}));
    }
    return modules.get(name);
}
await getModule('main.js').link(name => getModule(name.startsWith('./') ? name.slice(2) : name));
`;
const result = spawnSync(process.execPath, ['--experimental-vm-modules', '--input-type=module'], {input:program, encoding:'utf8'});
assert.equal(result.status, 0, result.stderr);
""".replace('SOURCES', json.dumps(sources)))


def test_zapret_update_check_is_request_correlated_and_exposes_feedback():
    root = Path(__file__).resolve().parents[1] / 'ui/web_new_v2'
    html = (root / 'index.html').read_text(encoding='utf-8')
    settings = (root / 'js/settings-panel.js').read_text(encoding='utf-8')
    events = (root / 'js/events.js').read_text(encoding='utf-8')
    assert 'id="btn-check-zapret-update"' in html
    assert 'check_zapret_update(requestId)' in settings
    assert "'nedotify:zapret_update_checked'" in settings
    assert "case 'zapret_update_checked'" in events
    assert 'result.request_id !== activeZapretCheckId' in settings


def test_retired_offline_switch_does_not_remove_downloaded_library():
    from core.bridge import PUBLIC_METHODS
    root = Path(__file__).resolve().parents[1] / 'ui/web_new_v2'
    html = (root / 'index.html').read_text(encoding='utf-8')
    library = (root / 'js/library.js').read_text(encoding='utf-8')
    controls = (root / 'js/feature-controls.js').read_text(encoding='utf-8')
    assert 'id="offline-mode-toggle"' not in html
    assert 'applyOfflineState' not in controls
    assert 'get_offline_library' in PUBLIC_METHODS
    assert 'get_downloaded_tracks' in library
    assert 'id="lib-card-offline"' in html


def test_comparison_is_requested_only_when_open_and_stale_results_are_ignored():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const pending = [], callbacks = new Map(), windowEvents = new Map();
const panel = {open:false,addEventListener(name, callback) {callbacks.set(name,callback)}};
const result = {textContent:'',innerHTML:'',setAttribute() {},querySelector() {return {append() {}}}};
const button = {disabled:false}, period = {value:'week'};
const elements = new Map([['profile-comparison',panel],['profile-comparison-result',result],['profile-comparison-refresh',button],['profile-comparison-period',period]]);
const context = vm.createContext({console,Date,Intl,
    document:{getElementById:id=>elements.get(id),createElement:()=>({})},
    window:{addEventListener(name, callback) {windowEvents.set(name,callback)},pywebview:{api:{get_listening_comparison(...args) {return new Promise(resolve=>pending.push({resolve,args}))}}}},
    escapeHtml:value=>String(value),formatListeningTimeShort:ms=>String(ms),renderIcons() {},
});
vm.runInContext(SOURCE.replace(/^import .*;\r?$/gm,'').replace(/\bexport\s+/g,'')+'\ninitProfileComparison();',context);
assert.equal(pending.length,0);
callbacks.get('toggle')();
assert.equal(pending.length,0);
panel.open=true;callbacks.get('toggle')();
await new Promise(setImmediate);
assert.equal(pending[0].args[0],'week');
period.value='month';period.onchange();
await new Promise(setImmediate);
assert.equal(pending.length,2);
const data={days:30,current:{seconds:10,plays:2,tracks:1,top_artists:[]},previous:{seconds:0,plays:0,tracks:0},delta:{seconds:{absolute:10,percent:null},plays:{absolute:2,percent:null},tracks:{absolute:1,percent:null}},new_artists:[]};
pending[1].resolve(data);await new Promise(setImmediate);
assert.ok(result.innerHTML.includes('30 дней'));
const html=result.innerHTML;
pending[0].resolve({...data,days:7});await new Promise(setImmediate);
assert.equal(result.innerHTML,html);
assert.equal(button.disabled,false);
""".replace('SOURCE', source('profile-comparison.js')))
