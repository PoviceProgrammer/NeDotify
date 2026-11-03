"""Guard settings controls for folder import and measured-history clearing."""
from pathlib import Path
from tests.jsdom import run_node, source


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "ui/web_new_v2/index.html").read_text(encoding="utf-8")
SETTINGS = (ROOT / "ui/web_new_v2/js/settings-panel.js").read_text(encoding="utf-8")
EVENTS = (ROOT / "ui/web_new_v2/js/events.js").read_text(encoding="utf-8")


def test_storage_panel_exposes_folder_import_and_separate_history_action():
    panel = HTML.split('id="settings-storage"', 1)[1].split('id="settings-import"', 1)[0]
    for element_id in (
        "btn-import-music-folder",
        "music-folder-import-status",
        "music-folder-import-progress",
        "btn-clear-listening-history",
    ):
        assert f'id="{element_id}"' in panel


def test_folder_import_uses_native_picker_and_scan_events_refresh_library():
    assert "api.import_music_folder()" in SETTINGS
    assert "nedotify:scan_progress" in SETTINGS
    assert "nedotify:scan_complete" in SETTINGS
    assert "event.detail?.current" in SETTINGS and "event.detail?.total" in SETTINGS
    assert "window.refreshActiveLibraryView?.()" in SETTINGS
    assert "case 'scan_progress'" in EVENTS and "case 'scan_complete'" in EVENTS


def test_measured_history_clear_requires_confirmation_and_handles_backend_event():
    assert "confirm('Удалить историю прослушивания" in SETTINGS
    assert "clear_listening_history(false)" in SETTINGS
    assert "clear_listening_history(true)" in SETTINGS
    assert "case 'listening_history_cleared'" in EVENTS


def test_history_clear_event_rotates_the_live_track_session_without_restarting_it():
    run_node(r"""
import assert from 'node:assert/strict';import vm from 'node:vm';
const track={id:7,listening_session:'old'};const dispatched=[];
const context=vm.createContext({console,window:{addEventListener(){},dispatchEvent:event=>dispatched.push(event)},
  document:{getElementById(){return null}},CustomEvent:class {constructor(type,options){this.type=type;this.detail=options.detail}},
  getCurrentTrack:()=>track});
vm.runInContext(SOURCE.replace(/^import .*;\r?$/gm,'').replace(/\bexport\s+/g,'')+'\ninitEvents();flushPythonEvents();',context);
context.window.onPythonEvent('listening_history_cleared',{success:true,listening_session:'new-session'});
assert.equal(track.listening_session,'new-session');
assert.equal(dispatched.at(-1).type,'nedotify:listening_history_cleared');
assert.equal(dispatched.at(-1).detail.success,true);
""".replace("SOURCE", source("events.js")))

