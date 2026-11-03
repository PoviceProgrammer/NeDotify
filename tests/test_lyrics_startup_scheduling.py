"""Run the shipped lyric loader against resolving/playing/paused facts."""
from tests.jsdom import run_node, source


def test_autoplay_network_lyrics_wait_for_audio_but_restore_and_local_do_not():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
let calls=0;
let track={source:'soundcloud',source_id:'new',title:'Song',artist:'Artist',duration:180,autoplay:true};
let clock={paused:true,buffering:true,positionMs:0};
const context=vm.createContext({
 getCurrentTrack:()=>track,getLyricsPlaybackClock:()=>clock,getContainers:()=>[],
 lyricsTrackKey:t=>t.source_id,normalizeDurationMs:v=>v*1000,
 pendingLyricsRequest:null,lastLoadedTrackKey:'old',lastLyricsData:null,
 requestedLyricsDurationMs:0,lyricsMemoryCache:new Map(),currentOffsetMs:0,
 lyricsLoadGeneration:0,activeLyricsRequestId:'old-request',lastLyricsRevision:0,
 parsedLyrics:[],currentLineIndex:-1,currentTranslationMap:{},currentRawLyricsText:'',
 deferredLyricsRequest:null,LYRICS_PENDING_MAX_AGE_MS:15000,
 clearWordLyrics(){},resetLyricsScroll(){},updateOffsetBadges(){},renderLyrics(){},
 document:{getElementById(){return null}},
 localStorage:{getItem(){return null}},
 window:{pywebview:{api:{get_lyrics(){calls++;return {status:'loading'}}}}},console,
});
const code=SOURCE;
const loader=code.slice(code.indexOf('export function loadCurrentTrackLyrics('),code.indexOf('export function renderLyrics('));
vm.runInContext(code.slice(code.indexOf('function resumeDeferredLyrics('),code.indexOf('export function initLyrics(')),context);
vm.runInContext(loader.replace('export ',''),context);
context.loadCurrentTrackLyrics();
assert.equal(calls,0,'resolving autoplay must not start lyric network work');
track={...track,file_path:'https://example.com/audio'};
context.loadCurrentTrackLyrics();assert.equal(calls,0,'remote file_path must not bypass scheduling');
track={...track,file_path:null};
assert.notEqual(context.activeLyricsRequestId,'old-request','old response id must be invalidated immediately');
clock={paused:false,buffering:false,positionMs:50};track.stream_url='https://example.com/audio';
context.resumeDeferredLyrics();assert.equal(calls,1);
context.resumeDeferredLyrics();assert.equal(calls,1,'clock events must not duplicate requests');
track={...track,source_id:'restore',autoplay:false};clock={paused:true,buffering:true,positionMs:0};
context.loadCurrentTrackLyrics();assert.equal(calls,2,'paused restore still loads lyrics');
track={...track,source_id:'local',source:'local',file_path:'C:/music/test.mp3',autoplay:true};
context.loadCurrentTrackLyrics();assert.equal(calls,3,'local sidecar lookup remains immediate');
track={...track,source:'soundcloud',source_id:'deferred',file_path:null,stream_url:null};
context.loadCurrentTrackLyrics();assert.equal(calls,3);
track={...track,source_id:'different'};
context.resumeDeferredLyrics();assert.equal(context.deferredLyricsRequest,null,'track replacement cancels deferred work');
context.loadCurrentTrackLyrics(0,true);assert.equal(calls,4,'manual request bypasses autoplay defer');
track={...track,source_id:'cached'};
context.lyricsMemoryCache.set('cached',{durationMs:180000,data:{plainLyrics:'Cached lyrics'}});
context.loadCurrentTrackLyrics();assert.equal(calls,4,'cached text stays immediate without a network request');
assert.equal(context.deferredLyricsRequest,null);
""".replace('SOURCE',source('lyrics.js')))

