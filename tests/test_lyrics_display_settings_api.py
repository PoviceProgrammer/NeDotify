"""The lyrics display settings bridge must accept every shape the UI sent.

`save_lyrics_display_settings(self, settings: dict)` used to reject the UI's
four positional numbers with `isinstance(settings, dict) == False`, returned
`False` and persisted nothing. `get_lyrics_display_settings` returned a flat
camelCase dict, which the popover ignored because it required
`{success, settings}`. Both sides are now tolerant; these tests pin the backend
half so a future signature change cannot silently drop saves again.
"""

from types import SimpleNamespace

from core.api import AppApi


class _FakeDb:
    def __init__(self):
        self.values = {}

    def set_settings_batch(self, items):
        for key, value, _category in items:
            self.values[key] = value
        return len(items)

    def get_settings_by_category(self, _category):
        return dict(self.values)


def _api():
    db = _FakeDb()
    return db, SimpleNamespace(_core=SimpleNamespace(db=db))


def test_save_accepts_camel_case_dict():
    db, api = _api()
    assert AppApi.save_lyrics_display_settings(api, {
        'fontSize': 31, 'fontWeight': 600, 'lineHeight': 1.9, 'textAlign': 'left',
    }) is True
    assert db.values == {
        'lyrics_display.fontSize': 31,
        'lyrics_display.fontWeight': 600,
        'lyrics_display.lineHeight': 1.9,
        'lyrics_display.textAlign': 'left',
    }


def test_save_accepts_legacy_positional_arguments():
    db, api = _api()
    assert AppApi.save_lyrics_display_settings(api, 30, 700, 1.45, 'center') is True
    assert db.values == {
        'lyrics_display.fontSize': 30,
        'lyrics_display.fontWeight': 700,
        'lyrics_display.lineHeight': 1.45,
        'lyrics_display.textAlign': 'center',
    }


def test_save_accepts_snake_case_and_json_string():
    db, api = _api()
    assert AppApi.save_lyrics_display_settings(api, {
        'font_size': 28, 'font_weight': 500, 'line_height': '1.7', 'text_align': 'left',
    }) is True
    assert db.values == {
        'lyrics_display.fontSize': 28,
        'lyrics_display.fontWeight': 500,
        'lyrics_display.lineHeight': 1.7,
        'lyrics_display.textAlign': 'left',
    }

    db, api = _api()
    assert AppApi.save_lyrics_display_settings(api, '{"fontSize": 26, "textAlign": "left"}') is True
    assert db.values == {
        'lyrics_display.fontSize': 26,
        'lyrics_display.textAlign': 'left',
    }


def test_save_rejects_unusable_payloads():
    db, api = _api()
    assert AppApi.save_lyrics_display_settings(api, 'not json') is False
    assert AppApi.save_lyrics_display_settings(api) is False
    assert AppApi.save_lyrics_display_settings(api, None) is False
    assert db.values == {}


def test_save_clamps_out_of_range_values():
    db, api = _api()
    AppApi.save_lyrics_display_settings(api, {
        'fontSize': 999, 'fontWeight': 10, 'lineHeight': 9, 'textAlign': 'weird',
    })
    assert db.values == {
        'lyrics_display.fontSize': 36,
        'lyrics_display.fontWeight': 400,
        'lyrics_display.lineHeight': 2.2,
        'lyrics_display.textAlign': 'center',
    }


def test_get_returns_only_stored_keys():
    _db, api = _api()
    # A fresh database must not hand back defaults: the UI merges this over its
    # localStorage copy, and full defaults would wipe a value cached before the
    # save path was fixed.
    assert AppApi.get_lyrics_display_settings(api) == {}

    AppApi.save_lyrics_display_settings(api, {'fontSize': 33, 'textAlign': 'left'})
    assert AppApi.get_lyrics_display_settings(api) == {'fontSize': 33, 'textAlign': 'left'}
