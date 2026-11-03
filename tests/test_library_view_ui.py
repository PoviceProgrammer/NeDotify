"""Persisted cover preferences and library dates must not blank the UI."""
import json
from pathlib import Path
import shutil
import subprocess
import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'ui/web_new_v2/js/library-view.js'

def run_library_js(assertions):
    node=shutil.which('node')
    if not node:
        pytest.skip('Node unavailable')
    script=f"""
    import vm from 'node:vm';
    import assert from 'node:assert/strict';
    const storage=new Map();
    class FixedDate extends Date {{constructor(...args){{super(...(args.length?args:['2026-10-14T12:00:00Z']));}}}}
    const context=vm.createContext({{window:{{}},Date:FixedDate,localStorage:{{getItem:key=>storage.get(key)??null}}}});
    vm.runInContext({json.dumps(SOURCE.read_text(encoding='utf-8'))}.replace(/^import .*;\\r?$/gm,'').replace(/\\bexport\\s+/g,'')+'\\nglobalThis.subject={{formatLibraryDate,getPlaylistCover}};',context);
    {assertions}
    """
    result=subprocess.run([node,'--input-type=module'],input=script,text=True,encoding='utf-8',capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr

def test_dates_only_use_valid_saved_metadata():
    run_library_js("""
    assert.equal(context.subject.formatLibraryDate(null),'');
    assert.equal(context.subject.formatLibraryDate('not-a-date'),'');
    assert.equal(context.subject.formatLibraryDate('2026-10-14 12:00:00'),'Сегодня');
    assert.notEqual(context.subject.formatLibraryDate('2026-10-10 12:00:00'),'Сегодня');
    """)

def test_invalid_cover_store_recovers_and_changed_store_refreshes():
    run_library_js("""
    storage.set('nedotify_v2_playlist_covers','null');assert.equal(context.subject.getPlaylistCover(11),'');
    storage.set('nedotify_v2_playlist_covers','{invalid');assert.equal(context.subject.getPlaylistCover(11),'');
    storage.set('nedotify_v2_playlist_covers',JSON.stringify({'11':'data:image/png;base64,one'}));assert.equal(context.subject.getPlaylistCover(11),'data:image/png;base64,one');
    storage.set('nedotify_v2_playlist_covers',JSON.stringify({'11':'data:image/png;base64,two'}));assert.equal(context.subject.getPlaylistCover(11),'data:image/png;base64,two');
    """)
