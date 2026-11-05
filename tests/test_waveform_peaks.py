"""Actual PCM waveform and bounded request lifecycle, without live audio/network."""
from tests.jsdom import run_node, source


def test_waveform_preserves_silence_stereo_peaks_and_the_final_sample():
    run_node(r"""
import assert from 'node:assert/strict';
const code=SOURCE;
let channels=[new Float32Array(1200)];
class Decoder {
 constructor(){}
 async decodeAudioData(){return {length:channels[0].length,numberOfChannels:channels.length,getChannelData:i=>channels[i]};}
 async close(){}
}
globalThis.window={OfflineAudioContext:Decoder};
globalThis.fetch=async()=>({ok:true,headers:{get:()=>8},arrayBuffer:async()=>new ArrayBuffer(8)});
const {fetchRealPeaks}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const silence=await fetchRealPeaks({source:'local',id:'silence',stream_url:'/silence'});
assert.equal(silence.length,600);
assert.ok(silence.every(v=>v===0),'Silence must remain silent instead of gaining fabricated bars');
channels=[new Float32Array(1200),new Float32Array(1200)];
channels[1][200]=-.5;channels[1][1000]=1;
const stereo=await fetchRealPeaks({source:'local',id:'stereo',stream_url:'/stereo'});
assert.equal(stereo[100],.5,'Right-channel sound must appear at its actual position');
assert.equal(stereo[500],1);assert.equal(stereo[0],0);
channels=[new Float32Array(601)];channels[0][600]=1;
const tail=await fetchRealPeaks({source:'local',id:'tail',stream_url:'/tail'});
assert.equal(tail[599],1,'The final sample must not be discarded by bucket rounding');
assert.equal(tail[0],0);
""".replace('SOURCE', source('waveform-peaks.js')))


def test_pcm_buckets_match_known_envelope_without_an_artificial_floor():
    run_node(r"""
import assert from 'node:assert/strict';
const {audioBufferToPeaks}=await import('data:text/javascript;base64,'+Buffer.from(SOURCE).toString('base64'));
const audio=channels=>({length:channels[0].length,numberOfChannels:channels.length,getChannelData:i=>channels[i]});
const left=new Float32Array([0,0,.0001,-.0001,0,0,.5,-1]);
const right=Float32Array.from(left,v=>-v);
const peaks=audioBufferToPeaks(audio([left,right]),4);
assert.equal(peaks[0],0);assert.ok(Math.abs(peaks[1]-.0001)<1e-10);
assert.equal(peaks[2],0);assert.equal(peaks[3],1,'Opposite phase must not cancel');
assert.deepEqual(audioBufferToPeaks(audio([new Float32Array(8)]),4),[0,0,0,0]);
assert.deepEqual(audioBufferToPeaks(audio([new Float32Array([.25])]),4),[1,1,1,1]);
assert.equal(audioBufferToPeaks(audio([new Float32Array(0)])),null);
""".replace('SOURCE', source('waveform-peaks.js')))


def test_requests_coalesce_cache_and_allow_one_subscriber_to_abort():
    run_node(r"""
import assert from 'node:assert/strict';
let fetches=0,decodes=0,closed=0,release;let fetchSignal;
globalThis.window={OfflineAudioContext:class {
 async decodeAudioData(){decodes++;return {length:2,numberOfChannels:1,getChannelData:()=>new Float32Array([0,1])};}
 async close(){closed++;}
}};
globalThis.fetch=async(url,{signal})=>{fetches++;fetchSignal=signal;await new Promise(resolve=>release=resolve);return {ok:true,headers:{get:()=>8},arrayBuffer:async()=>new ArrayBuffer(8)};};
const {fetchRealPeaks,peekCachedPeaks}=await import('data:text/javascript;base64,'+Buffer.from(SOURCE).toString('base64'));
const track={source:'local',id:'same'},first=new AbortController(),second=new AbortController();
const one=fetchRealPeaks(track,{url:'/resolved',signal:first.signal});
const two=fetchRealPeaks(track,{url:'/resolved',signal:second.signal});
first.abort();assert.equal(await one,null);assert.equal(fetchSignal.aborted,false);
release();const peaks=await two;
assert.equal(fetches,1);assert.equal(decodes,1);assert.equal(closed,1);
assert.equal(peekCachedPeaks(track),peaks);
assert.equal(await fetchRealPeaks(track,{url:'/refreshed-signed-url'}),peaks);
assert.equal(fetches,1,'A cached envelope must not download/decode again');
second.abort();assert.equal(fetchSignal.aborted,false,'Completed consumer must detach its abort handler');
const cancelled=new AbortController();cancelled.abort();
assert.equal(await fetchRealPeaks(track,{url:'/resolved',signal:cancelled.signal}),null);
""".replace('SOURCE', source('waveform-peaks.js')))


def test_cancelled_decode_does_not_overlap_or_cache_stale_work():
    run_node(r"""
import assert from 'node:assert/strict';
const tick=()=>new Promise(setImmediate),pcm={length:2,numberOfChannels:1,getChannelData:()=>new Float32Array([0,1])};
let fetches=0,decodes=0,closed=0,release;
globalThis.window={OfflineAudioContext:class {
 async decodeAudioData(){decodes++;if(decodes===1)await new Promise(resolve=>release=resolve);return pcm;}
 async close(){closed++;}
}};
globalThis.fetch=async()=>{fetches++;return {ok:true,headers:{get:()=>8},arrayBuffer:async()=>new ArrayBuffer(8)};};
const {fetchRealPeaks,peekCachedPeaks}=await import('data:text/javascript;base64,'+Buffer.from(SOURCE).toString('base64'));
const old={id:'old',stream_url:'/old'},current={id:'current',stream_url:'/current'},controller=new AbortController();
const stale=fetchRealPeaks(old,{signal:controller.signal});await tick();assert.equal(decodes,1);
controller.abort();assert.equal(await stale,null);
const next=fetchRealPeaks(current);await tick();
assert.equal(fetches,1,'Native decode still in flight must retain the sole work slot');
release();assert.ok(await next);assert.equal(closed,2);assert.equal(fetches,2);
assert.equal(peekCachedPeaks(old),null,'Late decode results from a cancelled track must be discarded');
""".replace('SOURCE', source('waveform-peaks.js')))


def test_network_and_queued_work_cancel_with_the_last_consumer():
    run_node(r"""
import assert from 'node:assert/strict';
const calls=[];let release;
globalThis.window={OfflineAudioContext:class {
 async decodeAudioData(){return {length:1,numberOfChannels:1,getChannelData:()=>new Float32Array([1])};}
}};
globalThis.fetch=async(url,{signal})=>{
 calls.push([url,signal]);if(url==='/old')await new Promise(resolve=>release=resolve);
 return {ok:true,headers:{get:()=>8},arrayBuffer:async()=>new ArrayBuffer(8)};
};
const {fetchRealPeaks}=await import('data:text/javascript;base64,'+Buffer.from(SOURCE).toString('base64'));
const oldController=new AbortController(),queuedController=new AbortController();
const old=fetchRealPeaks({id:'old',stream_url:'/old'},{signal:oldController.signal});
const queued=fetchRealPeaks({id:'queued',stream_url:'/queued'},{signal:queuedController.signal});
const current=fetchRealPeaks({id:'current',stream_url:'/current'});
assert.equal(await fetchRealPeaks({id:'overflow',stream_url:'/overflow'}),null,'Queue must remain bounded');
queuedController.abort();assert.equal(await queued,null);oldController.abort();assert.equal(await old,null);
assert.equal(calls[0][1].aborted,true);release();assert.ok(await current);
assert.deepEqual(calls.map(([url])=>url),['/old','/current'],'Cancelled queued work must never start');
""".replace('SOURCE', source('waveform-peaks.js')))


def test_response_size_is_bounded_and_stream_readers_are_released():
    run_node(r"""
import assert from 'node:assert/strict';
let decodes=0,cancelled=0,released=0,reads=0;
globalThis.window={OfflineAudioContext:class {
 async decodeAudioData(){decodes++;return {length:1,numberOfChannels:1,getChannelData:()=>new Float32Array([1])};}
}};
let response={ok:true,headers:{get:()=>25*1024*1024},body:{async cancel(){cancelled++;}}};
globalThis.fetch=async()=>response;
const {fetchRealPeaks}=await import('data:text/javascript;base64,'+Buffer.from(SOURCE).toString('base64'));
assert.equal(await fetchRealPeaks({id:'header',stream_url:'/huge'}),null);assert.equal(cancelled,1);
response={ok:true,headers:{get:()=>null},body:{getReader:()=>({
 async read(){reads++;return {done:false,value:new Uint8Array(13*1024*1024)};},
 async cancel(){cancelled++;},releaseLock(){released++;}
})}};
assert.equal(await fetchRealPeaks({id:'stream',stream_url:'/unbounded'}),null);
assert.equal(reads,2);assert.equal(cancelled,2);assert.equal(released,1);assert.equal(decodes,0);
response={ok:true,headers:{get:()=>null},body:{getReader:()=>({
 async read(){return reads++===2?{done:false,value:new Uint8Array(8)}:{done:true};},
 async cancel(){cancelled++;},releaseLock(){released++;}
})}};
assert.ok(await fetchRealPeaks({id:'chunked',stream_url:'/small-without-length'}));
assert.equal(decodes,1);assert.equal(released,2);
assert.equal(await fetchRealPeaks({id:'long',stream_url:'/long',duration_ms:11*60000}),null);
""".replace('SOURCE', source('waveform-peaks.js')))


def test_peak_cache_is_lru_bounded_and_decoder_failure_can_retry():
    run_node(r"""
import assert from 'node:assert/strict';
let fetches=0,closed=0,fail=true;
globalThis.window={AudioContext:class {
 constructor(...args){assert.equal(args.length,0,'Live AudioContext does not accept OfflineAudioContext arguments');}
 async decodeAudioData(){if(fail)throw Error('unsupported codec');return {length:1,numberOfChannels:1,getChannelData:()=>new Float32Array([1])};}
 async close(){closed++;}
}};
globalThis.fetch=async()=>{fetches++;return {ok:true,headers:{get:()=>8},arrayBuffer:async()=>new ArrayBuffer(8)};};
const {fetchRealPeaks,peekCachedPeaks}=await import('data:text/javascript;base64,'+Buffer.from(SOURCE).toString('base64'));
const track=id=>({source:'local',id,stream_url:`/${id}`});
assert.equal(await fetchRealPeaks(track(0)),null);assert.equal(closed,1);
fail=false;assert.ok(await fetchRealPeaks(track(0)),'Retry immediately after failure must settle');
for(let id=1;id<24;id++)assert.ok(await fetchRealPeaks(track(id)));
assert.ok(peekCachedPeaks(track(0)));assert.ok(await fetchRealPeaks(track(24)));
assert.equal(peekCachedPeaks(track(1)),null,'Least recently used envelope must be evicted');
assert.ok(peekCachedPeaks(track(0)));assert.equal(closed,26);assert.equal(fetches,26);
""".replace('SOURCE', source('waveform-peaks.js')))
