"""History IDs and saved timestamps must retain their actual meaning in Profile."""
import json
from pathlib import Path
import shutil
import subprocess
import pytest

SOURCE=Path(__file__).resolve().parents[1]/'ui/web_new_v2/js/profile.js'

def run_profile(assertions):
    node=shutil.which('node')
    if not node:
        pytest.skip('Node unavailable')
    script=f"""
    import vm from 'node:vm';import assert from 'node:assert/strict';
    const context=vm.createContext({{}});
    vm.runInContext({json.dumps(SOURCE.read_text(encoding='utf-8'))}.replace(/^import .*;\\r?$/gm,'').replace(/\\bexport\\s+/g,'')+'\\nglobalThis.subject={{normalizeProfileTrack,profileTimestamp,relativeProfileTime}};',context);
    {assertions}
    """
    result=subprocess.run([node,'--input-type=module'],input=script,text=True,encoding='utf-8',capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr

def test_history_track_ids_are_used_for_playback_without_mutating_the_response():
    run_profile("""
    const original={id:501,track_id:7,title:'Трек'};
    assert.equal(context.subject.normalizeProfileTrack(original).id,7);
    assert.equal(original.id,501);
    assert.equal(context.subject.normalizeProfileTrack({id:11}).id,11);
    """)

def test_activity_uses_real_utc_timestamps_and_never_fabricates_missing_dates():
    run_profile("""
    const now=Date.parse('2026-10-15T10:00:00Z');
    assert.equal(context.subject.relativeProfileTime(null,now),'');
    assert.equal(context.subject.relativeProfileTime('invalid',now),'');
    assert.equal(context.subject.profileTimestamp('2026-10-15 09:00:00').toISOString(),'2026-10-15T09:00:00.000Z');
    assert.equal(context.subject.profileTimestamp('2026-10-15T12:00:00+03:00').toISOString(),'2026-10-15T09:00:00.000Z');
    assert.match(context.subject.relativeProfileTime('2026-10-15 09:00:00',now),/час/);
    """)
