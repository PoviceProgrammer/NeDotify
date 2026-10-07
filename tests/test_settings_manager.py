"""SettingsManager: loading, aliasing, key coercion, categories, properties.

Covers core/settings.py. ``flush()`` / ``sync_flush_now()`` durability is
already covered by tests/test_settings_flush.py and is not repeated here.

The manager never touches the filesystem or the network: every test drives it
with an in-process dict-backed DB double. The write-behind writer thread is
pushed far into the future so it cannot flush in the middle of an assertion.
"""

import pytest

from core.settings import DEFAULT_SETTINGS, SettingsManager


class _FakeDb:
    """Dict-backed stand-in for the settings tables."""

    def __init__(self, stored=None, batch=True):
        self.rows = dict(stored or {})
        self.batches = []
        self._batch = batch

    def get_all_settings(self):
        return dict(self.rows)

    def set_settings_batch(self, items):
        self.batches.append(list(items))
        for key, value, _category in items:
            self.rows[key] = value
        return len(items)

    def set_setting(self, key, value, category="general"):
        self.rows[key] = value


class _NoSettingsDb:
    """A DB object without get_all_settings() at all (very old schema)."""

    def get_setting(self, key, default=None):  # pragma: no cover - unused
        return default


def _manager(stored=None, db=None):
    sm = SettingsManager(db if db is not None else _FakeDb(stored))
    # Keep the write-behind thread asleep for the whole session: these tests
    # assert on cache/_dirty state and must not race a background flush.
    sm.FLUSH_INTERVAL_SECONDS = 3600.0
    return sm


# --------------------------------------------------------------------------- #
# _load_all
# --------------------------------------------------------------------------- #

def test_stored_values_win_over_the_defaults():
    sm = _manager({"audio.volume": 11, "theme.name": "Light"})

    assert sm.get("audio", "volume") == 11
    assert sm.get("theme", "name") == "Light"


def test_keys_missing_from_the_db_are_filled_from_the_defaults():
    sm = _manager({"audio.volume": 11})

    assert sm.get("audio", "quality") == DEFAULT_SETTINGS["audio"]["quality"]
    assert sm.get("theme", "accent_color") == DEFAULT_SETTINGS["theme"]["accent_color"]
    assert set(sm.get_category("audio")) == set(DEFAULT_SETTINGS["audio"]), (
        "every default key must be present in the cache after loading"
    )


def test_an_empty_db_yields_the_whole_default_schema():
    sm = _manager({})

    for category, defaults in DEFAULT_SETTINGS.items():
        assert sm.get_category(category) == defaults


def test_a_bare_key_in_the_db_fills_every_category_that_declares_it():
    """Legacy rows were written without the category prefix (see the
    ``elif key in stored_all`` branch on core/settings.py:297)."""
    sm = _manager({"autostart": True})

    assert sm.get("app", "autostart") is True
    assert sm.get("general", "autostart") is True, (
        "a bare key applies to every category that declares it"
    )


def test_a_bare_key_that_no_category_declares_is_ignored():
    sm = _manager({"totally_unknown_key": 1})

    assert all("totally_unknown_key" not in cat for cat in sm._cache.values())


def test_a_dotted_key_for_a_known_category_is_parsed():
    sm = _manager({"audio.quality": "low", "interface.border_radius": 20})

    assert sm.get("audio", "quality") == "low"
    assert sm.get("interface", "border_radius") == 20


def test_a_dotted_key_creates_a_category_that_does_not_exist_yet():
    """Unknown categories are preserved, not dropped - that is what keeps a
    settings.json written by a newer build readable by an older one."""
    sm = _manager({"custom.mode": "turbo"})

    assert sm.get("custom", "mode") == "turbo"
    assert sm.get_category("custom") == {"mode": "turbo"}


def test_a_dotted_key_can_add_a_new_key_to_a_known_category():
    sm = _manager({"audio.custom_preset": "bass-boost"})

    assert sm.get("audio", "custom_preset") == "bass-boost"
    assert sm.get("audio", "volume") == DEFAULT_SETTINGS["audio"]["volume"], (
        "one unknown key must not cost the category its defaults"
    )


def test_a_db_without_get_all_settings_loads_the_defaults():
    """The loader uses getattr(..., lambda: {})() so an old DB shim is fine."""
    sm = _manager(db=_NoSettingsDb())

    assert sm.get("audio", "volume") == DEFAULT_SETTINGS["audio"]["volume"]


# --------------------------------------------------------------------------- #
# get(): the alias pairs
# --------------------------------------------------------------------------- #

# The aliases only exist for settings that are NOT in DEFAULT_SETTINGS: both
# halves of each pair are declared there, so for the "audio" category the cache
# always answers first. They are reachable for a category that declares neither
# key - which is exactly how the frontend's legacy keys are served.

def test_queue_autopilot_aliases_flow_enabled_in_an_undeclared_category():
    sm = _manager({"player.flow_enabled": False})

    assert sm.get("player", "queue_autopilot") is False


def test_flow_enabled_aliases_queue_autopilot_in_an_undeclared_category():
    sm = _manager({"player.queue_autopilot": False})

    assert sm.get("player", "flow_enabled") is False


def test_crossfade_duration_sec_aliases_crossfade_duration():
    sm = _manager({"player.crossfade_duration": 9})

    assert sm.get("player", "crossfade_duration_sec") == 9


def test_crossfade_duration_aliases_crossfade_duration_sec():
    sm = _manager({"player.crossfade_duration_sec": 7})

    assert sm.get("player", "crossfade_duration") == 7


def test_the_alias_falls_back_to_the_other_keys_default():
    sm = _manager()

    assert sm.get("player", "queue_autopilot", "no-alias") == "no-alias"


def test_an_alias_never_reaches_into_another_category():
    """``general`` exists but declares neither key of the pair, so the alias
    must not borrow audio's flow_enabled for it."""
    sm = _manager({"audio.flow_enabled": False})

    assert sm.get("general", "queue_autopilot", "fallback") == "fallback"
    assert sm.get("general", "crossfade_duration", "fallback") == "fallback"


def test_a_cached_alias_target_beats_the_other_key():
    sm = _manager()
    sm.set("player", "flow_enabled", False)

    assert sm.get("player", "queue_autopilot") is False
    sm.set("player", "flow_enabled", True)
    assert sm.get("player", "queue_autopilot") is True


def test_the_alias_does_not_fire_when_the_key_exists_in_the_defaults():
    """The real reason the audio pair is never aliased: DEFAULT_SETTINGS
    declares both keys, so the cache/default branch answers first."""
    sm = _manager({"audio.flow_enabled": False})

    assert sm.get("audio", "queue_autopilot") is True, (
        "queue_autopilot is its own default (True); the pair is independent in "
        "the declared category"
    )
    assert sm.get("audio", "flow_enabled") is False


# --------------------------------------------------------------------------- #
# get(): the dotted-key overloads
# --------------------------------------------------------------------------- #

def test_get_accepts_a_dotted_key():
    sm = _manager({"audio.volume": 33})

    assert sm.get("audio.volume") == 33


def test_get_dotted_key_takes_the_default_as_second_argument():
    """The second positional argument becomes the *fallback*, not an override -
    it is handed to the three-argument get() as its ``default``."""
    sm = _manager()

    assert sm.get("audio.volume", 55) == DEFAULT_SETTINGS["audio"]["volume"]
    assert sm.get("audio.no_such_key", 55) == 55, "a missing key does fall back"


def test_get_dotted_key_for_an_unknown_key_returns_the_default():
    sm = _manager()

    assert sm.get("audio.no_such_key") is None
    assert sm.get("audio.no_such_key", "dflt") == "dflt"


def test_get_dotted_key_splits_on_the_first_dot_only():
    sm = _manager({"weird.key.with.dots": 5})

    assert sm.get("weird.key.with.dots") == 5


# --------------------------------------------------------------------------- #
# get()/set(): "true"/"false" coercion
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("stored,expected", [
    ("true", True),
    ("TRUE", True),
    ("True", True),
    ("false", False),
    ("FALSE", False),
])
def test_the_strings_true_and_false_are_returned_as_bools(stored, expected):
    sm = _manager({"audio.autoplay": stored})

    value = sm.get("audio", "autoplay")

    assert value is expected, f"{stored!r} must come back as {expected!r}, not str"


def test_other_strings_are_left_alone():
    sm = _manager({"audio.quality": "truthy"})

    assert sm.get("audio", "quality") == "truthy"


def test_real_booleans_survive_the_coercion():
    sm = _manager({"audio.autoplay": True})

    assert sm.get("audio", "autoplay") is True


def test_a_literal_true_string_in_the_auth_category_comes_back_as_a_bool():
    """Pinned footgun: the coercion is type-blind, so a *string* setting whose
    value happens to be "true" is handed to the caller as a bool.

    ``auth`` has no boolean field that could want this - the values are tokens,
    cookie profiles and file paths - so a user/paste that stores the string
    "true" gets ``True`` back and any downstream ``if settings.get(...)`` /
    string concatenation silently changes meaning. Fixing it means knowing the
    declared type of the key, which DEFAULT_SETTINGS does not carry.
    """
    sm = _manager({"auth.yandex_token": "true", "auth.proxy_url": "false"})

    assert sm.get("auth", "yandex_token") is True
    assert sm.get("auth", "proxy_url") is False
    assert sm.get("auth", "cookies_file_path") == "", "other auth keys are strings"


# --------------------------------------------------------------------------- #
# set(): the dotted-key overload
# --------------------------------------------------------------------------- #

def test_set_accepts_a_dotted_key():
    sm = _manager()

    sm.set("audio.volume", 42)

    assert sm.get("audio", "volume") == 42
    assert ("audio", "volume") in sm._dirty, "the dirty entry must stay split"


def test_set_dotted_key_splits_on_the_first_dot_only():
    sm = _manager()

    sm.set("weird.key.with.dots", 5)

    assert sm._cache["weird"]["key.with.dots"] == 5


def test_set_dotted_key_with_a_none_value_does_not_reach_the_category():
    """Pinned BUG core/settings.py:374 - the dotted-key branch needs
    ``key is not None``, and in the ``set("cat.key", None)`` form ``key`` *is*
    None (the value lives in ``value``, which is also None).

    So the documented dotted form silently takes the three-argument path
    instead: it creates a junk category literally named "cat.key" holding the
    key ``None``, and the real setting is left untouched. Clearing a value
    through the dotted form is therefore impossible, and the junk category is
    persisted as the row "cat.key.None" on the next flush. Not reachable from
    the app today (every call site - core/api.py:2357, core/session.py:57,
    services/youtube_service.py:620 - uses the three-argument form), which is
    why it is pinned here instead of fixed in this branch.
    """
    sm = _manager({"session.last_track_id": 7})

    sm.set("session.last_track_id", None)

    assert sm.get("session", "last_track_id") == 7, "the real setting is untouched"
    assert sm._cache["session.last_track_id"] == {None: None}, (
        "the dotted form degenerated into a category named 'session.last_track_id'"
    )


def test_set_accepts_none_as_a_value_in_the_three_argument_form():
    """The dotted branch is only taken when the *value* is None AND a key was
    passed, so an explicit ``set(cat, key, None)`` is a normal write."""
    sm = _manager({"session.last_position": 12})

    sm.set("session", "last_position", None)

    assert sm._cache["session"]["last_position"] is None
    assert ("session", "last_position") in sm._dirty


def test_set_creates_an_unknown_category():
    sm = _manager()

    sm.set("brand_new", "key", 1)

    assert sm.get("brand_new", "key") == 1
    assert sm._is_known_category("brand_new")


def test_set_makes_the_value_visible_before_it_is_flushed():
    sm = _manager()

    sm.set("audio", "volume", 5)

    assert sm.get("audio", "volume") == 5
    assert sm._dirty == {("audio", "volume")}


def test_a_set_key_is_not_created_by_another_category():
    sm = _manager({"audio.volume": 3})

    sm.set("theme", "volume", 9)

    assert sm.get("audio", "volume") == 3
    assert sm.get("theme", "volume") == 9


# --------------------------------------------------------------------------- #
# get_category / reset_category / reset_all
# --------------------------------------------------------------------------- #

def test_get_category_returns_a_copy():
    sm = _manager({"audio.volume": 3})

    snapshot = sm.get_category("audio")
    snapshot["volume"] = 999

    assert sm.get("audio", "volume") == 3


def test_get_category_for_an_unknown_category_is_empty():
    sm = _manager()

    assert sm.get_category("nope") == {}


def test_reset_category_restores_every_default():
    sm = _manager({"audio.volume": 3, "audio.quality": "low"})

    sm.reset_category("audio")

    assert sm.get_category("audio") == DEFAULT_SETTINGS["audio"]
    assert sm.get("audio", "volume") == DEFAULT_SETTINGS["audio"]["volume"]
    assert {cat for cat, _ in sm._dirty} == {"audio"}


def test_reset_category_keeps_keys_that_are_not_in_the_defaults():
    """Unknown keys are never dropped - same rule as _load_all."""
    sm = _manager({"audio.custom_preset": "bass-boost"})

    sm.reset_category("audio")

    assert sm.get("audio", "custom_preset") == "bass-boost"
    assert sm.get("audio", "volume") == DEFAULT_SETTINGS["audio"]["volume"]


def test_reset_category_for_an_unknown_category_is_a_noop():
    sm = _manager()
    sm.set("player", "mode", "turbo")

    sm.reset_category("player")

    assert sm.get("player", "mode") == "turbo"
    assert sm._dirty == {("player", "mode")}, "nothing new was queued for writing"


def test_reset_all_restores_every_category_and_leaves_the_extras():
    sm = _manager({"audio.volume": 3, "theme.name": "Light"})
    sm.set("player", "mode", "turbo")

    sm.reset_all()

    for category, defaults in DEFAULT_SETTINGS.items():
        assert sm.get_category(category) == defaults
    assert sm.get("player", "mode") == "turbo", "reset_all only walks the schema"


# --------------------------------------------------------------------------- #
# the property accessors
# --------------------------------------------------------------------------- #

def test_the_properties_read_the_loaded_values():
    sm = _manager()

    assert sm.theme_name == DEFAULT_SETTINGS["theme"]["name"]
    assert sm.theme_mode == DEFAULT_SETTINGS["theme"]["mode"]
    assert sm.accent_color == DEFAULT_SETTINGS["theme"]["accent_color"]
    assert sm.volume == DEFAULT_SETTINGS["audio"]["volume"]
    assert sm.border_radius == DEFAULT_SETTINGS["interface"]["border_radius"]
    assert sm.crossfade_enabled is DEFAULT_SETTINGS["audio"]["crossfade_enabled"]
    assert sm.crossfade_duration == DEFAULT_SETTINGS["audio"]["crossfade_duration"]
    assert sm.overlay_mode == DEFAULT_SETTINGS["overlay"]["mode"]
    assert sm.font_family == DEFAULT_SETTINGS["interface"]["font_family"]


def test_the_properties_follow_a_set():
    sm = _manager()

    sm.set("theme", "name", "Light")
    sm.set("theme", "mode", "light")
    sm.set("theme", "accent_color", "#00ff00")
    sm.set("audio", "volume", 5)
    sm.set("interface", "border_radius", 4)
    sm.set("audio", "crossfade_enabled", True)
    sm.set("audio", "crossfade_duration", 11)
    sm.set("overlay", "mode", "full")
    sm.set("interface", "font_family", "Inter")

    assert sm.theme_name == "Light"
    assert sm.theme_mode == "light"
    assert sm.accent_color == "#00ff00"
    assert sm.volume == 5
    assert sm.border_radius == 4
    assert sm.crossfade_enabled is True
    assert sm.crossfade_duration == 11
    assert sm.overlay_mode == "full"
    assert sm.font_family == "Inter"


def test_gapless_defaults_to_false_not_to_the_properties_literal():
    """AUDIT-F finding: the ``gapless`` property passes ``True`` as its default
    argument while ``DEFAULT_SETTINGS['audio']['gapless_playback']`` is False.

    The property argument is unreachable for a loaded manager (the cache always
    has the key), so the effective default is False - the ``True`` is dead code
    that reads as "gapless is on by default" to anyone auditing the call site.
    """
    sm = _manager()

    assert DEFAULT_SETTINGS["audio"]["gapless_playback"] is False
    assert sm.gapless is False, "the schema wins, not the property's own default"

    sm.set("audio", "gapless_playback", True)
    assert sm.gapless is True


def test_the_accent_color_property_literal_never_applies():
    """Same dead-default pattern as ``gapless``: the property says #6366f1,
    the schema says #a855f7."""
    sm = _manager()

    assert DEFAULT_SETTINGS["theme"]["accent_color"] == "#a855f7"
    assert sm.accent_color == "#a855f7"


def test_border_radius_coerces_a_string():
    """The property wraps the lookup in int() - the only one that does."""
    sm = _manager({"interface.border_radius": "20"})

    assert sm.border_radius == 20


def test_border_radius_raises_on_a_non_numeric_value():
    """Pinned footgun: int() is unguarded, so a corrupt row makes the property
    raise instead of returning the default."""
    sm = _manager({"interface.border_radius": "round"})

    with pytest.raises(ValueError):
        sm.border_radius


# --------------------------------------------------------------------------- #
# properties vs. the keys the app actually writes
# --------------------------------------------------------------------------- #

def test_the_font_family_property_reads_a_category_nobody_writes():
    """Pinned drift: ui/web_new_v2/js/settings.js:160 and :584 save font_family
    into the *theme* category (and :746 reads it back from there), while this
    property reads interface.font_family.

    DEFAULT_SETTINGS declares font_family in BOTH theme and interface, so both
    lookups succeed and neither errors - the property just keeps reporting the
    interface default forever, whatever the user picks.
    """
    sm = _manager()
    sm.set("theme", "font_family", "Inter")

    assert sm.get("theme", "font_family") == "Inter", "the frontend's key"
    assert sm.font_family == DEFAULT_SETTINGS["interface"]["font_family"], (
        "the property never sees it"
    )


def test_the_theme_mode_property_reads_a_different_key_than_the_frontend():
    """Same drift: settings.js:1489 saves ``theme_mode`` and :673-676 reads
    ``settings.theme.theme_mode``, but this property reads ``theme.mode`` -
    a second, parallel key (DEFAULT_SETTINGS['theme'] has both 'mode' and
    'theme_mode')."""
    sm = _manager()
    sm.set("theme", "theme_mode", "light")

    assert sm.get("theme", "theme_mode") == "light", "the frontend's key"
    assert sm.theme_mode == DEFAULT_SETTINGS["theme"]["mode"], (
        "the property still reports the untouched 'mode' key"
    )