from core.bridge import BridgeApi
from core.database import DatabaseManager
from tests.test_player_recovery_transitions import player_test


def test_track_moment_is_persisted_and_removable(api, tmp_path):
    bridge = BridgeApi(api)
    youtube_key = '["youtube","same-id"]'
    soundcloud_key = '["soundcloud","same-id"]'
    assert bridge.get_track_moment(youtube_key) is None
    assert bridge.set_track_moment(youtube_key, 0)
    assert bridge.get_track_moment(youtube_key) == 0
    assert bridge.set_track_moment(youtube_key, 47350)
    assert bridge.set_track_moment(soundcloud_key, 12500)
    assert not bridge.set_track_moment(youtube_key, -1)
    assert not bridge.set_track_moment(youtube_key, True)
    reopened = DatabaseManager(str(tmp_path / 'test.db'))
    try:
        assert reopened.get_track_moment(youtube_key) == 47350
        assert reopened.get_track_moment(soundcloud_key) == 12500
        assert bridge.set_track_moment(youtube_key, None)
        assert reopened.get_track_moment(youtube_key) is None
        assert reopened.get_track_moment(soundcloud_key) == 12500
    finally:
        reopened.close()


def test_track_moment_captures_menu_time_and_seeks_without_moving_between_tracks():
    player_test(r'''
const saved = new Map();
context.showToast = () => {};
context.window.pywebview.api.get_track_moment = async key => saved.get(key) ?? null;
context.window.pywebview.api.set_track_moment = async (key, value) => {
    if (value === null) saved.delete(key);
    else saved.set(key, value);
    return true;
};
for (const prefix of ['pb', 'pp', 'mp']) {
    const slider = elements.get(prefix + '-progress-track');
    slider.removeAttribute = name => slider.setAttribute(name, null);
    elements.set(prefix + '-moment-pin', {parentElement: slider, style: {setProperty() {}}});
}
const actions = vm.runInContext('getTrackMomentActions', context);
player.onTrackChanged(first);
await flush();
player.active.readyState = 4;
player.active.currentTime = 37.25;
const [mark] = actions(first);
assert.match(mark.label, /0:37$/);
player.active.currentTime = 39;
await mark.run();
for (const prefix of ['pb', 'pp', 'mp']) {
    assert.equal(elements.get(prefix + '-moment-pin').hidden, false);
    assert.equal(elements.get(prefix + '-progress-track').getAttribute('aria-keyshortcuts'), 'Enter');
}
const [jump, remove] = actions(first);
jump.run();
assert.equal(player.active.currentTime, 37.25);
player.onTrackChanged(second);
await flush();
jump.run();
await remove.run();
assert.equal(elements.get('pb-moment-pin').hidden, true);
assert.equal(actions(first).length, 0);
player.onTrackChanged(first);
await flush();
assert.equal(elements.get('pp-moment-pin').hidden, false);
await actions(first)[1].run();
assert.equal(elements.get('mp-moment-pin').hidden, true);
assert.equal(saved.size, 0);
''')
