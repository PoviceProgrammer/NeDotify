"""The preparation UI exposes measured progress, never a timer-driven estimate."""
from tests.jsdom import run_node, source


def test_setup_progress_is_indeterminate_until_backend_has_real_bytes():
    run_node(r"""
import assert from 'node:assert/strict';import vm from 'node:vm';
const code=SOURCE,context=vm.createContext({});
vm.runInContext(code.slice(code.indexOf('export function setupProgressView('),code.indexOf('\nasync function call(')).replace('export ',''),context);
for(const status of ['checking','resolving','verifying']) {
 const view=context.setupProgressView({status});
 assert.equal(view.value,null);assert.equal(view.busy,true);
}
assert.equal(context.setupProgressView({status:'downloading',percent:42.5}).value,42.5);
assert.equal(context.setupProgressView({status:'downloading',percent:null}).value,null);
assert.equal(context.setupProgressView({status:'failed',error:{message:'Проверьте сеть'}}).error,'Проверьте сеть');
assert.equal(context.setupProgressView({status:'cancelled'}).busy,false);
""".replace('SOURCE',source('setup-panel.js')))
