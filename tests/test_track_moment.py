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


def test_track_moment_is_reachable_through_every_identity_of_the_track(api, tmp_path):
    bridge = BridgeApi(api)
    canonical = '["youtube","dQw4w9WgXcQ"]'
    aliases = ['["id","412"]', 'youtube|dQw4w9WgXcQ', 'rick astley - never gonna give you up']

    assert bridge.set_track_moment(canonical, 64100, aliases)
    # The marker survives a view that only knows a different identity of the track.
    for alias in aliases:
        assert bridge.get_track_moment(alias) == 64100
    assert bridge.get_track_moment(canonical) == 64100
    # An identity that was never registered stays unmarked.
    assert bridge.get_track_moment('["id","999"]') is None


def test_track_moment_removal_clears_every_alias(api):
    bridge = BridgeApi(api)
    canonical = '["soundcloud","777"]'
    assert bridge.set_track_moment(canonical, 30000, ['["id","1"]', 'artist - title'])
    assert bridge.set_track_moment(canonical, None)
    assert bridge.get_track_moment(canonical) is None
    assert bridge.get_track_moment('["id","1"]') is None
    assert bridge.get_track_moment('artist - title') is None


def test_track_moment_rejects_malformed_aliases(api):
    bridge = BridgeApi(api)
    key = '["youtube","abc"]'
    assert not bridge.set_track_moment(key, 1000, 'not-a-list')
    assert not bridge.set_track_moment(key, 1000, ['ok', 42])
    assert not bridge.set_track_moment(key, 1000, [''])
    assert bridge.get_track_moment(key) is None
    # Duplicates and the primary key itself are harmless, not a refusal.
    assert bridge.set_track_moment(key, 1000, [key, 'a', 'a'])
    assert bridge.get_track_moment(key) == 1000
    assert bridge.get_track_moment('a') == 1000


def test_moment_icon_setting_is_closed(api):
    assert api.save_setting('moment_icon', 'fire', 'ui')
    assert api.get_settings_by_category('ui')['moment_icon'] == 'fire'
    assert not api.save_setting('moment_icon', 'skull', 'ui')
    assert api.get_settings_by_category('ui')['moment_icon'] == 'fire'


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
    slider.addEventListener = () => {};
    elements.set(prefix + '-moment-pin', {parentElement: slider, dataset: {}, style: {setProperty() {}}, addEventListener() {}});
}
const clickHandlers = new Map();
const label = {textContent: ''};
const markButton = {
    querySelector: () => label,
    addEventListener: (name, handler) => clickHandlers.set('mark', handler),
};
const removeButton = {
    addEventListener: (name, handler) => clickHandlers.set('remove', handler),
};
elements.set('pp-btn-moment', markButton);
elements.set('pp-btn-moment-remove', removeButton);
vm.runInContext('bindTrackMomentPins()', context);
const actions = vm.runInContext('getTrackMomentActions', context);
player.onTrackChanged(first);
await flush();
assert.equal(markButton.disabled, true);
assert.equal(removeButton.hidden, true);
player.active.readyState = 4;
player.active.events.get('loadedmetadata')();
assert.equal(markButton.disabled, false);
player.active.currentTime = 37.25;
const [mark] = actions(first);
assert.match(mark.label, /0:37$/);
player.active.currentTime = 39;
await mark.run();
for (const prefix of ['pb', 'pp', 'mp']) {
    assert.equal(elements.get(prefix + '-moment-pin').hidden, false);
    assert.equal(elements.get(prefix + '-progress-track').getAttribute('aria-keyshortcuts'), 'Enter');
}
assert.equal(removeButton.hidden, false);
assert.equal(label.textContent, 'К лучшему моменту · 0:37');
const [jump, remove] = actions(first);
clickHandlers.get('mark')();
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
clickHandlers.get('remove')();
await flush();
assert.equal(elements.get('mp-moment-pin').hidden, true);
assert.equal(saved.size, 0);
assert.equal(label.textContent, 'Отметить лучший момент');
player.active.currentTime = 42;
clickHandlers.get('mark')();
await flush();
assert.equal(label.textContent, 'К лучшему моменту · 0:42');
assert.equal(saved.values().next().value, 42000);
''')
