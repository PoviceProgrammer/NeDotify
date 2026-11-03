"""Repeated cover sampling should reuse its tiny surface without caching failures."""
import json
from pathlib import Path

from tests.jsdom import run_node


def test_cover_sampler_reuses_surface_and_invalidates_on_source_change():
    code = (Path(__file__).resolve().parents[1] / 'ui/web_new_v2/js/utils.js').read_text(encoding='utf-8')
    start = code.find('// Shared cover sampler')
    if start < 0:
        start = code.index('export function extractDominantColor')
    code = code[start:code.index('export function handleImageError')].replace('export ', '')
    run_node(f'''
import assert from 'node:assert/strict';import vm from 'node:vm';
let canvases=0,reads=0,blocked=false;
const context={{console,WeakMap,document:{{createElement(){{canvases++;return {{width:0,height:0,getContext(){{return {{
drawImage(){{if(blocked)throw Error('CORS')}},getImageData(){{reads++;return {{data:new Uint8ClampedArray([120,80,40,255])}}}}
}}}}}}}}}}}};
vm.createContext(context);vm.runInContext({json.dumps(code)}+';this.sample=extractDominantColor;',context);
const image={{src:'cover-a',currentSrc:'cover-a',complete:true,naturalWidth:100,naturalHeight:100}};
for(let n=0;n<20;n++)assert.equal(JSON.stringify(context.sample(image)),JSON.stringify({{r:120,g:80,b:40}}));
assert.equal(canvases,1,'Repeated artwork extraction allocates canvas contexts');
assert.equal(reads,1,'Unchanged cover repeats GPU/CPU pixel reads');
image.src=image.currentSrc='cover-b';context.sample(image);assert.equal(reads,2);
image.src=image.currentSrc='cover-c';blocked=true;assert.equal(context.sample(image),null);
blocked=false;assert.ok(context.sample(image));assert.equal(reads,3,'A failed sample must be retryable');
''')


def test_fallback_youtube_clients_are_shared(monkeypatch):
    from services.base_service import BaseMusicService
    from services.soundcloud_service import SoundCloudService
    import services.youtube_service as youtube
    service = SoundCloudService.__new__(SoundCloudService)
    BaseMusicService.__init__(service)
    service.settings = None
    created = []
    monkeypatch.setattr(youtube, 'YouTubeService', lambda settings: created.append(object()) or created[-1])
    first = service._get_youtube_fallback()
    assert all(service._get_youtube_fallback() is first for _ in range(20))
    assert len(created) == 1
    shared = object()
    service.youtube_service = shared
    assert service._get_youtube_fallback() is shared
    assert len(created) == 1
