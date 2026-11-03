"""Built-in backgrounds must stay available without the public image proxy."""
import json
from pathlib import Path
import re
import shutil
import subprocess

from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / 'ui/web_new_v2'


def test_local_catalog_covers_presets_and_legacy_workshop_urls():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node unavailable')
    settings = (UI / 'js/settings.js').read_text(encoding='utf-8')
    presets = re.findall(r"id: '([^']+)'", settings.split('const PRESET_THEMES = [')[1].split('];', 1)[0])
    old_urls = sorted(set(re.findall(r'https://images.unsplash.com/[^\s\x27]+', settings)))
    script = f"""
    const vm=require('node:vm'),assert=require('node:assert/strict');
    const window={{}};vm.runInNewContext({json.dumps((UI/'js/appearance-assets.js').read_text(encoding='utf-8'))},{{window,URL}});
    const a=window.NeDotifyAssets;
    const old={json.dumps(old_urls)};
    const paths={json.dumps(presets)}.map(id=>a.themeBackgroundPath(id));
    for(const url of old){{
      const resolved=a.resolveBackground(url);
      assert.match(resolved,/^assets\\/backgrounds\\/photo-[\\w-]+\\.webp$/);
      assert.equal(a.resolveBackground('https://wsrv.nl/?url='+encodeURIComponent(url)),resolved);
      paths.push(resolved);
    }}
    for(const custom of ['data:image/png;base64,abc','https://example.org/custom.jpg','assets/mine.jpg'])assert.equal(a.resolveBackground(custom),custom);
    assert.equal(a.resolveBackground('assets/backgrounds/photo-1448375240586-882707db888b.jpg'),'assets/backgrounds/photo-1448375240586-882707db888b.webp');
    console.log(JSON.stringify([...new Set([...paths,...a.backgroundPaths])]));
    """
    result = subprocess.run([node, '-e', script], capture_output=True, text=True, encoding='utf-8', timeout=10)
    assert result.returncode == 0, result.stderr
    paths = json.loads(result.stdout)
    assert len(presets) == 22
    assert len(paths) == 27
    for path in paths:
        with Image.open(UI / path) as image:
            assert image.format == 'WEBP'
            assert max(image.size) >= 1600
            image.verify()


def test_home_collage_uses_history_and_ignores_stale_image_loads():
    from tests.jsdom import run_node, source
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const nodes = new Map(), classes = new Set(), pending = [];
class Element {
 constructor(){this.children=[];this.className='';this.classList={contains:k=>k==='active'};}
 setAttribute(){} animate(){} get childElementCount(){return this.children.length;}
 get firstElementChild(){return this.children[0]} get lastElementChild(){return this.children.at(-1)}
 append(node){node.parent=this;this.children.push(node);if(node.id)nodes.set(node.id,node)}
 prepend(node){node.parent=this;this.children.unshift(node);if(node.id)nodes.set(node.id,node)}
 replaceChildren(){this.children=[]} remove(){this.parent.children=this.parent.children.filter(n=>n!==this)}
}
class Picture extends Element {
 set src(value){this.url=value;pending.push(this)} get src(){return this.url}
 cloneNode(){const n=new Element();n.url=this.url;return n}
}
nodes.set('app-container',new Element());nodes.set('view-home',new Element());
const document={readyState:'loading',addEventListener(){},getElementById:id=>nodes.get(id),createElement:()=>new Element(),
 documentElement:{classList:{toggle:(key,on)=>on?classes.add(key):classes.delete(key)}}};
const context=vm.createContext({document,window:{settings:{theme:{decorations_enabled:true}}},Image:Picture,
 getCoverUrl:t=>t.cover_url||'',setTimeout,clearTimeout,Promise,Set,Map,JSON,Array,Boolean});
const code=SOURCE.replace(/^import .*;$/m,'').replaceAll('export ','');
vm.runInContext(code,context);
const first=context.updateHomeCoverCollage([{cover_url:'old'}]);
const second=context.updateHomeCoverCollage([{cover_url:'new'},{cover_url:'new'},{cover_url:'broken'}]);
pending.find(p=>p.url==='new').onload();pending.find(p=>p.url==='broken').onerror();await second;
pending.find(p=>p.url==='old').onload();await first;
const host=nodes.get('home-cover-collage');
assert.equal(host.childElementCount,1);assert.equal(host.children[0].children.length,6);
assert.ok(host.children[0].children.every(n=>n.url==='new'));
assert.ok(classes.has('has-home-collage'));assert.equal(host.inert,true);
const count=pending.length;await context.updateHomeCoverCollage([{cover_url:'new'},{cover_url:'new'},{cover_url:'broken'}]);
assert.equal(pending.length,count,'unchanged history must not load artwork again');
await context.updateHomeCoverCollage([]);assert.equal(host.childElementCount,0);assert.ok(!classes.has('has-home-collage'));
""".replace('SOURCE', source('home-atmosphere.js')))
