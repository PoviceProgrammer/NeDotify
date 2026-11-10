"""Continuous radio keeps a buffer and respects newer playback intent."""
from tests.jsdom import run_node, source


HARNESS = r"""
import assert from 'node:assert/strict';
const {createTrackWaveController} = await import('data:text/javascript;base64,' + Buffer.from(SOURCE).toString('base64'));
const timers = new Map(); let timerSequence = 0, entrySequence = 0;
const requests = [], added = [], messages = [], states = [];
let snapshot = {tracks: [], current_index: -1, queue_revision: 0, history: []};
let nextCalls = 0, appendRace = false, feedback = {track: true, artist: false};
const track = (id, artist='Artist') => ({source:'youtube', source_id:id, id:id, title:id, artist});
const api = {
    play_track: async seed => { snapshot={tracks:[{...seed,entry_id:String(++entrySequence)}], current_index:0, queue_revision:snapshot.queue_revision+1, history:[]}; return {success:true}; },
    get_queue: async () => structuredClone(snapshot),
    get_track_wave: async (...args) => { requests.push(args); return []; },
    add_tracks_to_queue: async (tracks, entry, revision) => {
        if (appendRace) { snapshot={...snapshot, tracks:[{...track('manual'),entry_id:'manual'}],current_index:0,queue_revision:snapshot.queue_revision+1}; }
        if (revision !== snapshot.queue_revision || entry !== snapshot.tracks[snapshot.current_index]?.entry_id) return {success:false,code:'stale_queue'};
        added.push(...tracks);snapshot.tracks.push(...tracks.map(t=>({...t,entry_id:String(++entrySequence)})));snapshot.queue_revision++;return {success:true};
    },
    remove_from_queue: async (index, entry) => {
        assert.equal(snapshot.tracks[index].entry_id,entry); assert.ok(index>snapshot.current_index);
        snapshot.tracks.splice(index,1);snapshot.queue_revision++;return {success:true};
    },
    next_track: async () => {nextCalls++;snapshot.current_index++;snapshot.queue_revision++;},
    get_recommendation_feedback: async () => feedback,
};
const wave=createTrackWaveController({api:()=>api, onChange:s=>states.push(s),toast:m=>messages.push(m),
    setTimer:(fn,ms)=>{const id=++timerSequence;timers.set(id,{fn,ms});return id;},clearTimer:id=>timers.delete(id)});
const respond = async tracks => wave.handlePythonEvent('track_wave_ready',{request_id:requests.at(-1)[3],tracks});
const update = async () => wave.handlePythonEvent('queue_updated',structuredClone(snapshot));
"""


def run_wave(assertions):
    run_node(HARNESS.replace("SOURCE", source("track-wave.js")) + assertions)


def test_wave_refills_at_five_remaining_and_keeps_anchor_and_deduplicates():
    run_wave(r"""
await wave.start(track('seed'));
assert.equal(requests.length,1);assert.equal(wave.state().status,'loading');
await respond(Array.from({length:8},(_,i)=>track('first'+i)));
assert.equal(added.length,8);assert.equal(timers.size,0);assert.equal(wave.state().upcoming,8);
snapshot.current_index=2;await update();assert.equal(requests.length,1);
snapshot.current_index=3;await update();assert.equal(requests.length,2);
assert.equal(requests[1][0].source_id,'seed');
assert.ok(requests[1][2].includes('first0'));assert.ok(requests[1][2].includes('artist:first0'));
await respond([track('first0'),{...track('alternate'),title:'first1'},...Array.from({length:7},(_,i)=>track('new'+i))]);
assert.equal(added.length,15);assert.equal(wave.state().status,'ready');
await update();assert.equal(requests.length,2,'a full buffer must not keep requesting');
wave.stop();assert.equal(timers.size,0);
""")


def test_wave_ignores_replaced_sessions_and_manual_queue_and_cleans_deadline():
    run_wave(r"""
await wave.start(track('old'));const oldRequest=requests.at(-1)[3];
await wave.start(track('new'));assert.notEqual(requests.at(-1)[3],oldRequest);
await wave.handlePythonEvent('track_wave_ready',{request_id:oldRequest,tracks:[track('wrong')]});
assert.equal(added.length,0);assert.equal(timers.size,1);
const deadline=[...timers.values()][0];deadline.fn();assert.equal(timers.size,0);assert.equal(wave.state().status,'waiting');
await respond([track('late')]);assert.equal(added.length,0);
await update();assert.equal(requests.length,2,'failure must require an explicit retry');
await wave.retry();assert.equal(requests.length,3);
snapshot={tracks:[{...track('manual'),entry_id:'manual'}],current_index:0,queue_revision:999};
await update();assert.equal(wave.state().active,false);assert.equal(timers.size,0);
await respond([track('stale')]);assert.equal(added.length,0);
""")


def test_wave_append_is_atomic_against_a_manual_playback_race():
    run_wave(r"""
await wave.start(track('seed'));appendRace=true;
await respond([track('stale')]);
assert.equal(added.length,0);assert.equal(snapshot.tracks[0].source_id,'manual');
await update();assert.equal(wave.state().active,false);assert.equal(timers.size,0);
""")


def test_wave_rejects_duplicate_delivery_and_resume_only_after_queue_end():
    run_wave(r"""
await wave.start(track('seed'));
const response={request_id:requests.at(-1)[3],tracks:[track('one')]};
await Promise.all([wave.handlePythonEvent('track_wave_ready',response),wave.handlePythonEvent('track_wave_ready',response)]);
assert.equal(added.length,1);
snapshot.current_index=1;await update();await wave.handlePythonEvent('queue_ended');
await respond([track('two')]);assert.equal(nextCalls,1);
await update();await wave.handlePythonEvent('queue_ended');await wave.handlePythonEvent('state_changed','paused');
await respond([track('three')]);assert.equal(nextCalls,1,'Pause cancels automatic resume');
wave.stop();assert.equal(timers.size,0);
""")


def test_wave_mode_change_refreshes_only_generated_future_tracks_and_feedback_filters():
    run_wave(r"""
await wave.start(track('seed'));
await respond([track('remove','Blocked'),track('keep','Other')]);
snapshot.tracks.push({...track('manual'),entry_id:'manual'});snapshot.queue_revision++;await update();
await wave.feedbackChanged({track:track('remove','Blocked'),kind:'track'});
assert.ok(!snapshot.tracks.some(t=>t.source_id==='remove'));
assert.ok(snapshot.tracks.some(t=>t.source_id==='keep'));assert.ok(snapshot.tracks.some(t=>t.source_id==='manual'));
await respond([track('remove','Blocked'),track('fresh')]);assert.ok(!snapshot.tracks.some(t=>t.source_id==='remove'));
await wave.refreshFuture();
assert.deepEqual(snapshot.tracks.map(t=>t.source_id),['seed','manual']);
assert.equal(wave.state().status,'loading');wave.stop();assert.equal(timers.size,0);
""")


def test_wave_bridge_rejection_waits_for_retry_without_repeated_requests():
    run_wave(r"""
api.get_track_wave=async (...args)=>{requests.push(args);throw new Error('offline');};
await wave.start(track('seed'));assert.equal(wave.state().status,'waiting');assert.equal(timers.size,0);
await update();await update();assert.equal(requests.length,1);
await wave.retry();assert.equal(requests.length,2);assert.equal(wave.state().active,true);
wave.stop();assert.equal(timers.size,0);
""")


def test_wave_continuation_uses_recent_played_verified_neighbors_and_keeps_anchor():
    run_wave(r"""
await wave.start(track('seed'));assert.equal(requests[0][4].length,0);
await respond([{...track('neighbor1','First'),recommendation_relevance:.8},{...track('neighbor2','Second'),recommendation_relevance:.8},track('unverified','Third')]);
snapshot.current_index=2;
await update();
assert.deepEqual(requests.at(-1)[4].map(t=>t.source_id),['neighbor2','neighbor1']);
assert.ok(requests.at(-1)[4].every(t=>t.recommendation_origin==='wave'));
assert.equal(requests.at(-1)[0].source_id,'seed');
await respond([{...track('later1','Fourth'),recommendation_relevance:.8},{...track('later2','Fifth'),recommendation_relevance:.8}]);
snapshot.current_index=4;
await update();
assert.deepEqual(requests.at(-1)[4].map(t=>t.source_id),['later1','neighbor2'],'only played verified neighbors may expand discovery');
assert.equal(requests.at(-1)[0].source_id,'seed','original anchor remains fixed even when neighbors advance');
wave.stop();
""")
