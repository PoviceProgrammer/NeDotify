"""Independent regression probes for rich-lyrics integration boundaries."""
import json
from io import BytesIO

import pytest

from services.lyrics_service import LyricsService
from tests.jsdom import run_node, source


def test_word_painter_forward_and_backward_seek_updates_skipped_rows():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const ctx=vm.createContext({});
vm.runInContext(SOURCE.replaceAll('export ',''),ctx);
const painter=vm.runInContext('new WordPainter([0,1,2,3].map(i=>({startMs:i*1000,endMs:i*1000+900,words:[{text:String(i),startMs:i*1000,endMs:i*1000+900}]})))',ctx);
const spans=[0,1,2,3].map(()=>({dataset:{},style:{setProperty(k,v){this[k]=v}}}));
const rows=[spans.map(span=>[span])];
painter.paint(rows,100,'standard',true);
painter.paint(rows,3200);
assert.equal(spans[1].style['--lyric-word-fill'],'100.00%','forward seek skips completed rows');
assert.equal(spans[2].style['--lyric-word-fill'],'100.00%');
painter.paint(rows,100);
assert.equal(spans[1].style['--lyric-word-fill'],'0.00%','backward seek resets skipped future rows');
assert.equal(spans[2].style['--lyric-word-fill'],'0.00%');
""".replace('SOURCE', source('lyrics-word-engine.js')))


def test_playback_clock_uses_incoming_audio_on_crossfade_pause_seek_and_rate():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const code=SOURCE;
const outgoing={currentTime:100,paused:false,readyState:4,playbackRate:1};
const incoming={currentTime:1.25,paused:false,readyState:4,playbackRate:1.5};
const ctx=vm.createContext({Number,JSON,Math,activeAudio:outgoing,isSeeking:false,
  playbackState:{status:'playing',positionMs:0,track:{source:'youtube',source_id:'firstid1234',title:'Old'}}});
vm.runInContext(code.slice(code.indexOf('export function getLyricsPlaybackClock('),code.indexOf('function notifyLyricsClock(')).replace('export ',''),ctx);
assert.equal(ctx.getLyricsPlaybackClock().positionMs,100000);
const previousKey=ctx.getLyricsPlaybackClock().trackKey;
ctx.activeAudio=incoming;ctx.playbackState.track={source:'youtube',source_id:'abcdefghijk',title:'Incoming'};
assert.equal(ctx.getLyricsPlaybackClock().positionMs,1250);
assert.notEqual(ctx.getLyricsPlaybackClock().trackKey,previousKey);
assert.equal(ctx.getLyricsPlaybackClock().playbackRate,1.5);
incoming.paused=true;assert.equal(ctx.getLyricsPlaybackClock().paused,true);
incoming.paused=false;incoming.currentTime=30;incoming.seeking=true;
assert.equal(ctx.getLyricsPlaybackClock().positionMs,30000);
assert.equal(ctx.getLyricsPlaybackClock().seeking,true);
incoming.readyState=2;assert.equal(ctx.getLyricsPlaybackClock().buffering,true);
""".replace('SOURCE', source('player.js')))


def test_track_incompatible_cached_word_times_fall_through_to_provider(tmp_path, monkeypatch):
    service=LyricsService(cache_path=tmp_path/'lyrics.db')
    for name in ('netease','qqmusic','genius','megalobiz'):
        monkeypatch.setattr(service._lookup,name,lambda *a:None)
    calls=[]
    def provider(form,*args):
        calls.append(1)
        return service._lookup.accept(form,'A Song','Artist',120,'[00:01] Right','Right','Fixture')
    monkeypatch.setattr(service._lookup,'lrclib',provider)
    assert service.get_lyrics('A Song','Artist',120000)['plainLyrics']=='Right'
    key=next(iter(service._cache))
    bad=dict(service._cache[key][1])
    bad.update(syncType='word',lines=[{'startMs':500000,'endMs':501000,
                'words':[{'text':'Wrong','startMs':500000,'endMs':501000}]}])
    service._lookup.disk_cache.put(key,bad,86400)
    service._cache.clear()
    result=service.get_lyrics('A Song','Artist',120000)
    assert result['plainLyrics']=='Right' and len(calls)==2


@pytest.mark.rich_lyrics
def test_rich_transport_keeps_word_intervals_in_disk_cache_and_request_envelopes(tmp_path, monkeypatch):
    service=LyricsService(cache_path=tmp_path/'lyrics.db')
    for name in ('lrclib','netease','qqmusic','genius','megalobiz'):
        monkeypatch.setattr(service._lookup,name,lambda *a:None)
    calls=[]
    def request(req,**kwargs):
        calls.append(req.full_url)
        if 'unison.' not in req.full_url:
            return BytesIO(b'{}')
        return BytesIO(json.dumps({'success':True,'data':{'song':'Апрель','artist':'Скриптонит',
            'duration':120,'album':'Album','videoId':'abcdefghijk','confidence':1,
            'format':'lrc','syncType':'richsync','lyrics':'[00:01]<00:01>А<00:01.1>прель<00:02>'}}).encode())
    monkeypatch.setattr(service,'_open_url',request)
    seen=[]
    result=service.get_lyrics('Апрель','Скриптонит',120000,album_name='Album',source='youtube',source_id='abcdefghijk',on_update=seen.append)
    assert result['syncType']=='word'
    assert [word['endMs'] for word in result['lines'][0]['words']]==[1100,2000]
    assert seen[-1]['phase']=='final'
    calls.clear()
    restarted=LyricsService(cache_path=tmp_path/'lyrics.db')
    monkeypatch.setattr(restarted,'_open_url',lambda *a,**kw: (_ for _ in ()).throw(AssertionError('cache miss')))
    cached=restarted.get_lyrics('Апрель','Скриптонит',120000,album_name='Album',source='youtube',source_id='abcdefghijk')
    assert cached['lines']==result['lines'] and cached['syncType']=='word'


@pytest.mark.rich_lyrics
@pytest.mark.parametrize('changed', [
    {'videoId':'otherid1234'}, {'artist':'Другой артист'}, {'song':'Май'},
    {'song':'Апрель (Live)'}, {'duration':180}, {'album':'Different album'},
])
def test_explicit_rich_identity_mismatch_rejected(monkeypatch, changed):
    service=LyricsService()
    for name in ('lrclib','netease','qqmusic','genius','megalobiz'):
        monkeypatch.setattr(service._lookup,name,lambda *a:None)
    row={'song':'Апрель','artist':'Скриптонит','duration':120,'album':'Album',
         'videoId':'abcdefghijk','confidence':1,'format':'lrc','syncType':'richsync',
         'lyrics':'[00:01]<00:01>Апрель<00:02>'}
    row.update(changed)
    monkeypatch.setattr(service._lookup,'_json',lambda url,*a: {'success':True,'data':row} if 'unison.' in url else {})
    result=service.get_lyrics('Апрель','Скриптонит',120000,album_name='Album',source='youtube',source_id='abcdefghijk')
    assert result['status']!='found'


@pytest.mark.rich_lyrics
def test_non_youtube_source_id_is_not_used_as_video_identity(monkeypatch):
    import urllib.parse
    service=LyricsService()
    for name in ('lrclib','netease','qqmusic','genius','megalobiz'):
        monkeypatch.setattr(service._lookup,name,lambda *a:None)
    urls=[]
    def request(url,*args):
        urls.append(url)
        return {}
    monkeypatch.setattr(service._lookup,'_json',request)
    service.get_lyrics('Апрель','Скриптонит',120000,source='soundcloud',source_id='abcdefghijk')
    assert not any('api-lyrics.simpmusic.org' in url for url in urls)
    assert all('v' not in urllib.parse.parse_qs(urllib.parse.urlsplit(url).query) for url in urls)


@pytest.mark.rich_lyrics
def test_old_line_cache_is_shown_then_upgraded_once_to_rich_source(tmp_path, monkeypatch):
    path=tmp_path/'lyrics.db'
    initial=LyricsService(cache_path=path)
    for name in ('netease','qqmusic','genius','megalobiz'):
        monkeypatch.setattr(initial._lookup,name,lambda *a:None)
    for name in ('unison','betterlyrics','simpmusic'):
        monkeypatch.setattr(initial._lookup.rich,name,lambda *a:None)
    monkeypatch.setattr(initial._lookup,'lrclib',lambda form,*a:initial._lookup.accept(form,'A Song','Artist',120,'[00:01] Hello','Hello','Old source'))
    initial.get_lyrics('A Song','Artist',120000)
    key=next(iter(initial._cache))
    old=dict(initial._cache[key][1])
    for field in ('syncType','lines','originalFormat','originalLyrics','updatedAt','trackIdentity'):
        old.pop(field,None)
    initial._lookup.disk_cache.put(key,old,86400)

    restarted=LyricsService(cache_path=path)
    for name in ('lrclib','netease','qqmusic','genius','megalobiz'):
        monkeypatch.setattr(restarted._lookup,name,lambda *a:None)
    calls=[]
    def request(url,*a):
        calls.append(url)
        return {'success':True,'data':{'song':'A Song','artist':'Artist','duration':120,
            'format':'lrc','confidence':1,'lyrics':'[00:01]<00:01>Hel<00:01.2>lo<00:02>'}} if 'unison.' in url else {}
    monkeypatch.setattr(restarted._lookup,'_json',request)
    seen=[]
    result=restarted.get_lyrics('A Song','Artist',120000,on_update=seen.append)
    assert seen[0]['source']=='Old source' and seen[0]['phase']=='partial'
    assert result['syncType']=='word' and result['source']=='Unison'
    count=len(calls)
    assert restarted.get_lyrics('A Song','Artist',120000)['lines']==result['lines']
    assert len(calls)==count


@pytest.mark.parametrize('yrc,sync_type', [('[1000,1000](1000,100,0)При(1100,900,0)вет','word'), ('malformed YRC','line')])
def test_existing_netease_prefers_genuine_yrc_and_recovers_to_lrc(monkeypatch,yrc,sync_type):
    service=LyricsService()
    for name in ('lrclib','qqmusic','genius','megalobiz'):
        monkeypatch.setattr(service._lookup,name,lambda *a:None)
    urls=[]
    def request(url,*a):
        urls.append(url)
        if '/cloudsearch/' in url:
            return {'code':200,'result':{'songs':[{'id':123,'name':'Апрель','ar':[{'name':'Скриптонит'}],'dt':120000}]}}
        return {'lrc':{'lyric':'[00:01] Привет'},'yrc':{'lyric':yrc}}
    monkeypatch.setattr(service._lookup,'_json',request)
    result=service.get_lyrics('Апрель','Скриптонит',120000)
    assert result['source']=='Netease' and result['syncType']==sync_type
    assert any('yv=1' in url for url in urls)
    if sync_type=='word':
        assert result['lines'][0]['words'][0]['endMs']==1100
