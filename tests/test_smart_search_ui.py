import json
from pathlib import Path
import shutil
import subprocess

import pytest


UI = Path(__file__).resolve().parents[1] / "ui/web_new_v2/js"


def run_module(filename, setup, assertions, exports):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable; headless behavior is unverified")
    source = (UI / filename).read_text(encoding="utf-8")
    script = f"""
        import vm from 'node:vm';
        import assert from 'node:assert/strict';
        {setup}
        // Pagination is tested independently of the separately exercised DOM virtualizer.
        if ({json.dumps(filename)} === 'library.js') context.createLibraryVirtualList = () => ({{destroy(){{}},refresh(){{}},update(){{}},renderNext(){{}}}});
        const source = {json.dumps(source)}.replace(/^import[\\s\\S]*?from ['"][^'"]+['"];?\\r?$/gm, '').replace(/\\bexport\\s+/g, '');
        vm.runInContext(source + '\\nglobalThis.subject = {{ {exports} }};', context);
        {assertions}
    """
    result = subprocess.run(
        [node, "--input-type=module"], input=script, text=True, encoding="utf-8", capture_output=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr


SEARCH_SETUP = """
    class Element {
        constructor(){this.children=[];this.dataset={};this.className='';this.value='';this._html='';}
        set innerHTML(value){this._html=value;this.children=[];}
        get innerHTML(){return this._html;}
        append(...items){this.children.push(...items);}
        appendChild(item){this.children.push(item);return item;}
        prepend(item){this.children.unshift(item);}
        querySelector(selector){
            if(selector==='.spinner')return this._html.includes('spinner')?{}:null;
            if(selector==='[data-original-query]')return this.children.find(child=>child.dataset?.originalQuery)||null;
            return null;
        }
    }
    const results=new Element(),input=new Element();
    const storage=new Map(), calls=[];
    const bridge={search:(...args)=>{calls.push(['search',...args]);return Promise.resolve();},get_search_suggestions:query=>{calls.push(['suggest',query]);return Promise.resolve([{query:'Radiohead',reason:'typo'}]);}};
    const context=vm.createContext({window:{pywebview:{api:bridge}},document:{getElementById:id=>id==='search-results'?results:id==='search-input'?input:null,createElement:()=>new Element()},clearTimeout:()=>{},localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)}});
"""


def test_repeated_same_query_rejects_old_completion_by_request_id():
    run_module('search.js', SEARCH_SETUP, """
        context.subject.setQuery('Radiohed');
        context.subject.runSearchQuery('Radiohed'); await Promise.resolve();
        const oldId = calls.at(-1)[4];
        context.subject.runSearchQuery('Radiohed'); await Promise.resolve();
        const newId = calls.at(-1)[4];
        assert.notEqual(oldId, newId);
        context.subject.onSearchResults({query:'Radiohed',source:'__completion__',request_id:oldId});
        await new Promise(setImmediate);
        assert.equal(calls.filter(row=>row[0]==='suggest').length,0);
        context.subject.onSearchResults({query:'Radiohed',source:'__completion__',request_id:newId});
        await new Promise(setImmediate);
        assert.equal(calls.filter(row=>row[0]==='suggest').length,1);
    """, 'runSearchQuery, onSearchResults, setQuery:query=>{currentSearchQuery=query;allResults=[];}')


def test_corrections_wait_for_empty_completion_and_only_search_after_click():
    run_module("search.js", SEARCH_SETUP, """
        context.subject.setQuery('Radiohed');
        context.subject.runSearchQuery('Radiohed');
        await Promise.resolve();
        assert.equal(calls.filter(row=>row[0]==='search').length,1);
        context.subject.onSearchResults({query:'Radiohed',source:'youtube',tracks:[]});
        assert.equal(calls.filter(row=>row[0]==='suggest').length,0);
        context.subject.onSearchResults({query:'Radiohed',source:'__completion__'});
        await new Promise(setImmediate);
        assert.equal(calls.filter(row=>row[0]==='suggest').length,1);
        assert.equal(calls.filter(row=>row[0]==='search').length,1);
        const alternatives=results.children.find(child=>child.className==='search-query-alternatives');
        assert.ok(alternatives);
        alternatives.children[1].onclick();
        await Promise.resolve();
        assert.equal(input.value,'Radiohead');
        assert.equal(calls.filter(row=>row[0]==='search').length,2);
        assert.equal(calls.at(-1)[1],'Radiohead');
        context.subject.onSearchResults({query:'Radiohead',source:'__completion__'});
        await new Promise(setImmediate);
        const original=results.children.find(child=>child.dataset.originalQuery==='Radiohed');
        assert.ok(original);
        original.children[1].onclick();
        await Promise.resolve();
        assert.equal(input.value,'Radiohed');
        assert.equal(calls.at(-1)[1],'Radiohed');
    """, "runSearchQuery, onSearchResults, setQuery:query=>{currentSearchQuery=query;allResults=[];}")


def test_stale_suggestions_cannot_replace_new_search():
    run_module("search.js", SEARCH_SETUP, """
        let resolveSuggestion;
        bridge.get_search_suggestions=()=>new Promise(resolve=>{resolveSuggestion=resolve;});
        context.subject.setQuery('Radiohed');
        const request=context.subject.offerSearchCorrections();
        context.subject.setQuery('Different');
        resolveSuggestion([{query:'Radiohead',reason:'typo'}]);
        await request;
        assert.equal(results.children.length,0);
        assert.equal(calls.filter(row=>row[0]==='search').length,0);
    """, "offerSearchCorrections, setQuery:query=>{currentSearchQuery=query;allResults=[];}")


def test_all_library_collection_pages_beyond_200_with_total_and_dedup():
    run_module("library.js", """
        const elements=new Map(), calls=[];
        class Element {
            constructor(){this.children=[];this.style={};this.value='';this.textContent='';this.scrollHeight=1000;this.clientHeight=100;this.classList={add:()=>{},remove:()=>{},toggle:()=>{},contains:()=>false};}
            set innerHTML(value){this.children=[];}
            appendChild(child){this.children.push(child);return child;}
            after(child){elements.set(child.id,child);}
            remove(){elements.delete(this.id);}
            addEventListener(){}
            querySelector(){return null;}
        }
        const body=new Element(), parent=new Element();parent.parentElement=body;
        const lookup=id=>{if(!elements.has(id)){const element=new Element();element.id=id;element.parentElement=id==='lib-active-tracks'?parent:null;elements.set(id,element);}return elements.get(id);};
        const tracks=Array.from({length:450},(_,index)=>({id:index+1,source:'local',title:`Song ${index}`}));
        const context=vm.createContext({
            window:{awaitBridge:()=>Promise.resolve(),pywebview:{api:{get_library:(...args)=>{calls.push(args);const [,offset]=args;return Promise.resolve({tracks:tracks.slice(offset,offset+200),total:450,limit:200,offset,has_more:offset+200<450});}}}},
            document:{body,getElementById:lookup,querySelectorAll:()=>[],createElement:()=>new Element(),createDocumentFragment:()=>new Element(),addEventListener:()=>{}},
            updateLibraryHero:()=>{},createTrackElement:()=>new Element(),decorateLibraryRow:element=>element,getCurrentTrack:()=>null,renderIcons:()=>{},getComputedStyle:()=>({overflowY:'auto'})
        });
    """, """
        await context.subject.selectSection('all');
        assert.deepEqual(calls[0],[200,0,true]);
        assert.equal(context.subject.tracks().length,200);
        assert.equal(elements.get('lib-active-sub').textContent,'450 треков');
        const more=elements.get('lib-all-more');
        await more.onclick();
        assert.deepEqual(calls[1],[200,200,true]);
        assert.equal(context.subject.tracks().length,400);
        await more.onclick();
        assert.deepEqual(calls[2],[200,400,true]);
        assert.equal(context.subject.tracks().length,450);
        assert.equal(new Set(context.subject.tracks().map(track=>track.id)).size,450);
        assert.ok(!elements.has('lib-all-more'));
    """, "selectSection, tracks:()=>currentActiveTracks")


def test_all_library_collection_supports_legacy_array_pages():
    run_module("library.js", """
        const elements=new Map(), calls=[];
        class Element {
            constructor(){this.children=[];this.style={};this.value='';this.textContent='';this.scrollHeight=1000;this.clientHeight=100;this.classList={add:()=>{},remove:()=>{},toggle:()=>{},contains:()=>false};}
            set innerHTML(value){this.children=[];}
            appendChild(child){this.children.push(child);return child;}
            after(child){elements.set(child.id,child);}
            remove(){elements.delete(this.id);}
            addEventListener(){}
            querySelector(){return null;}
        }
        const body=new Element(), parent=new Element();parent.parentElement=body;
        const lookup=id=>{if(!elements.has(id)){const element=new Element();element.id=id;element.parentElement=id==='lib-active-tracks'?parent:null;elements.set(id,element);}return elements.get(id);};
        const tracks=Array.from({length:225},(_,index)=>({id:index+1,title:`Song ${index}`}));
        const context=vm.createContext({window:{awaitBridge:()=>Promise.resolve(),pywebview:{api:{get_library:(limit,offset)=>{calls.push([limit,offset]);return Promise.resolve(tracks.slice(offset,offset+limit));}}}},document:{body,getElementById:lookup,querySelectorAll:()=>[],createElement:()=>new Element(),createDocumentFragment:()=>new Element(),addEventListener:()=>{}},updateLibraryHero:()=>{},createTrackElement:()=>new Element(),decorateLibraryRow:element=>element,getCurrentTrack:()=>null,renderIcons:()=>{},getComputedStyle:()=>({overflowY:'auto'})});
    """, """
        await context.subject.selectSection('all');
        assert.equal(elements.get('lib-active-sub').textContent,'200 треков загружено');
        const more=elements.get('lib-all-more');
        await more.onclick();
        assert.deepEqual(calls,[[200,0],[200,200]]);
        assert.equal(context.subject.tracks().length,225);
        assert.equal(elements.get('lib-active-sub').textContent,'225 треков');
        assert.ok(!elements.has('lib-all-more'));
    """, "selectSection, tracks:()=>currentActiveTracks")


def test_library_overview_requests_eight_tracks_but_displays_total():
    run_module("library-view.js", """
        class Element {
            constructor(){this.children=[];this.textContent='';this._html='';this.dataset={};}
            set innerHTML(value){this._html=value;}
            get innerHTML(){return this._html;}
            replaceChildren(...children){this.children=[...children];}
            appendChild(child){this.children.push(child);return child;}
            querySelector(){return {onclick:null};}
        }
        const container=new Element(),count=new Element(),calls=[];
        const context=vm.createContext({window:{awaitBridge:()=>Promise.resolve(),pywebview:{api:{get_library:(...args)=>{calls.push(args);return Promise.resolve({tracks:[],total:731,limit:8,offset:0,has_more:true});}}}},document:{getElementById:id=>id==='lib-recent-tracks'?container:id==='lib-overview-count'?count:null},renderIcons:()=>{}});
    """, """
        await context.subject.loadLibraryOverview();
        assert.deepEqual(calls,[[8,0,true]]);
        assert.equal(count.textContent,'731 треков в коллекции');
    """, "loadLibraryOverview")


def test_library_overview_accepts_legacy_array_response():
    run_module("library-view.js", """
        class Element {
            constructor(){this.children=[];this.textContent='';this._html='';this.dataset={};}
            set innerHTML(value){this._html=value;}
            get innerHTML(){return this._html;}
            replaceChildren(...children){this.children=[...children];}
            appendChild(child){this.children.push(child);return child;}
            querySelector(){return {onclick:null};}
        }
        const container=new Element(),count=new Element(),calls=[];
        const context=vm.createContext({window:{awaitBridge:()=>Promise.resolve(),pywebview:{api:{get_library:(...args)=>{calls.push(args);return Promise.resolve([]);}}}},document:{getElementById:id=>id==='lib-recent-tracks'?container:id==='lib-overview-count'?count:null},renderIcons:()=>{}});
    """, """
        await context.subject.loadLibraryOverview();
        assert.deepEqual(calls,[[8,0,true]]);
        assert.equal(count.textContent,'0 треков в коллекции');
    """, "loadLibraryOverview")


@pytest.mark.parametrize("filename", ["search.js", "library.js", "library-view.js"])
def test_feature_modules_parse(filename, tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable; syntax is unverified")
    path = tmp_path / filename.replace(".js", ".mjs")
    path.write_text((UI / filename).read_text(encoding="utf-8"), encoding="utf-8")
    result = subprocess.run([node, "--check", str(path)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
