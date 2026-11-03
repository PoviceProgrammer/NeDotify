"""The retired infinite queue cannot be activated by persisted preferences."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_infinite_queue_and_pip_are_removed():
    player = (ROOT / 'ui/web_new_v2/js/player.js').read_text(encoding='utf-8')
    html = (ROOT / 'ui/web_new_v2/index.html').read_text(encoding='utf-8')
    assert 'get_flow_tracks' not in player
    assert 'requestFlowAutoplay' not in player
    assert 'pb-btn-flow' not in html
    assert 'mini-lyrics-widget' not in html
    assert 'queue-drawer' in html
