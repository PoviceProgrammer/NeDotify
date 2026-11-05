"""Preference changes commit before refreshing all recommendation surfaces."""
from tests.jsdom import run_node, source


def test_preference_commit_failure_and_single_flight():
    run_node("""
    import vm from 'node:vm';
    import assert from 'node:assert/strict';
    const events=[],stored=[],buttons=[{dataset:{recommendationMode:'familiar'},setAttribute(k,v){this[k]=v}},{dataset:{recommendationMode:'discovery'},setAttribute(k,v){this[k]=v}}];
    let finish,calls=0;
    const window={settings:{personalization:{recommendation_mode:'balanced'}},
      dispatchEvent:e=>events.push(e),pywebview:{api:{save_setting:(key,value,category)=>{
        calls++;assert.equal(key,'recommendation_mode');assert.equal(category,'personalization');
        return new Promise(resolve=>finish=resolve);
      }}}};
    const context=vm.createContext({window,document:{querySelectorAll:()=>buttons},
      localStorage:{setItem:(k,v)=>stored.push([k,v])},CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail}}});
    vm.runInContext(__SOURCE__.replace(/\\bexport\\s+/g,'')+'\\nglobalThis.subject={setRecommendationMode,recommendationMode}',context);
    const subject=context.subject;
    assert.equal(await subject.setRecommendationMode('invalid'),false);
    assert.equal(calls,0);
    const pending=subject.setRecommendationMode('discovery');
    assert.equal(window.settings.personalization.recommendation_mode,'balanced');
    assert.equal(events.length,0);assert.ok(buttons.every(b=>b.disabled));
    assert.equal(await subject.setRecommendationMode('familiar'),false);
    assert.equal(calls,1);
    finish({success:true});assert.equal(await pending,true);
    assert.equal(subject.recommendationMode(),'discovery');
    assert.equal(events[0].type,'nedotify:recommendation_mode_changed');
    assert.equal(buttons[1]['aria-pressed'],'true');assert.ok(buttons.every(b=>!b.disabled));
    assert.equal(stored.length,1);
    const failed=subject.setRecommendationMode('familiar');finish({success:false});
    assert.equal(await failed,false);assert.equal(subject.recommendationMode(),'discovery');
    assert.equal(events.filter(e=>e.type==='nedotify:recommendation_mode_changed').length,1);
    assert.equal(stored.length,1);assert.ok(buttons.every(b=>!b.disabled));
    """.replace("__SOURCE__", source("recommendation-controls.js")))

