"""Search discovery must contain real, distinct listening-history entries."""
import json
from pathlib import Path
import shutil
import subprocess
import pytest

UI = Path(__file__).resolve().parents[1] / 'ui' / 'web_new_v2'

def discovery_entries(history):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is unavailable')
    source = (UI / 'js' / 'search-discovery.js').read_text(encoding='utf-8')
    script = f"""
        import vm from 'node:vm';
        const context = vm.createContext({{}});
        const source = {json.dumps(source)}.replace(/^import .*;\\r?$/gm, '').replace(/\\bexport\\s+/g, '');
        vm.runInContext(source + '\\nglobalThis.result = historyToDiscovery(' + {json.dumps(json.dumps(history))} + ');', context);
        process.stdout.write(JSON.stringify(context.result));
    """
    result = subprocess.run([node,'--input-type=module'],input=script,text=True,encoding='utf-8',capture_output=True,timeout=10)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)

def test_recent_artists_are_unique_and_preserve_recent_order():
    history = [
        {'id':1,'title':'Недавняя песня','artist':' Полюс '},
        {'id':2,'title':'Другой трек','artist':'Свет внутри'},
        {'id':3,'title':'Старая песня','artist':'ПОЛЮС'},
    ]
    entries = discovery_entries(history)
    assert [item['name'] for item in entries] == ['Полюс','Свет внутри']
    assert entries[0]['track']['id'] == 1
    assert all(item['isArtist'] for item in entries)

def test_unknown_artists_fall_back_to_real_tracks_and_empty_history_stays_empty():
    history = [
        {'id':1,'source':'local','title':'Мой трек','artist':'Unknown Artist'},
        {'id':1,'source':'local','title':'Мой трек','artist':'?'},
        {'id':2,'source':'local','title':'Ещё трек','artist':''},
        None,
    ]
    entries = discovery_entries(history)
    assert [item['name'] for item in entries] == ['Мой трек','Ещё трек']
    assert not any(item['isArtist'] for item in entries)
    assert discovery_entries([]) == []
